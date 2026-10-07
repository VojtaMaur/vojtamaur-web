import copy
import json
import tempfile
import unittest
from pathlib import Path

from metaweb_swarm.backend import _Progress
from metaweb_swarm.budget import reserve
from metaweb_swarm.config import load_config
from metaweb_swarm.dedup import identity, merge_submission, resolve
from metaweb_swarm.engine import Engine, ToolAPI, initialize
from metaweb_swarm.hosted_search import classify
from metaweb_swarm.run_memory import build_run_memory, matching_prior, prior_candidates, search_prior
from metaweb_swarm.workspace import Workspace
from tests.test_dedup import candidate
from tests.test_backend import Tools, SDK_AVAILABLE


def card(scope='scan-trigger bootstrap artifact', key='qr-xmp-provenance-card'):
    return candidate('QR code / XMP / ORCID', 'QR-coded XMP provenance card with ORCID recovery pointer',
                     'Create a QR card embedding XMP recovery metadata and an ORCID attribution pointer',
                     summary='A shareable two-channel bootstrap card', mechanism_key=key, mechanism_scope=scope, id='')


def searches(completed=3, pending=True):
    result = [{'id': f'ws-{n}', 'type': 'web_search_call', 'status': 'completed',
               'action': {'type': 'search', 'query': 'primary'}} for n in range(completed)]
    if pending:
        result.append({'id': 'ws-pending', 'type': 'web_search_call', 'status': 'searching',
                       'action': {'type': 'search', 'query': 'ignored extra attempt'}})
    return result


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        project = self.root/'project'; project.mkdir(); (project/'site.txt').write_text('Production sentinel')
        runs = self.root/'runs'; old = runs/'prior'; old.mkdir(parents=True)
        previous_card = card(); previous_card['id'] = 'IDEA-0002'
        ideas = [candidate(summary='Public identifier recovery pointer', id='IDEA-0001', mechanism_scope='public-id-pointer'), previous_card]
        # A fourth candidate must survive the old first-three-title summary limit.
        ideas += [candidate('Other service', title=f'Other mechanism {n}', summary='Unfinished research', id=f'IDEA-000{n+2}') for n in (1,2)]
        state = {'schema_version':1,'backend':'openai','status':'LIMIT_REACHED','ideas':ideas,'agents':[]}
        (old/'checkpoint.json').write_text(json.dumps(state)); self.old_bytes=(old/'checkpoint.json').read_bytes()
        config=load_config(); config.update(prior_work_policy='novelty-first', max_web_search_calls_per_request=3)
        self.run=initialize(project,runs,config)
        class NeverDispatch:
            async def step(inner, *args):
                raise AssertionError('Provider must not be dispatched with unknown reservation')
        self.engine=Engine(self.run,NeverDispatch(),'openai'); self.engine.state['backend']='openai'
        self.agent=self.engine.state['agents'][1]
        self.workspace=Workspace(self.run/'snapshot',self.run/'agents'/self.agent['id']/'workspace')
        self.api=ToolAPI(self.engine,self.agent,self.workspace)

    def tearDown(self):
        self.engine.close(); self.temp.cleanup()

    def test_real_composite_qr_card_merges_without_becoming_orcid_record(self):
        a=card(); b=card('scan-trigger embedded-metadata card','qr-xmp-orcid-bootstrap')
        self.assertEqual(identity(a),identity(b)); self.assertTrue(identity(a).startswith('v1:qr-xmp:'))
        self.assertNotEqual(identity(a),identity(candidate()))
        merged=merge_submission(a,b,'AGENT-004','2026-10-07')
        self.assertIs(resolve([a],b),a); self.assertEqual(len(merged['submissions']),2)
        variant=card(); variant['mechanism_scope']='full-byte-payload'; self.assertNotEqual(identity(a),identity(variant))

    def test_all_prior_candidates_are_queryable_and_old_ledgers_unchanged(self):
        self.assertEqual(len(self.engine.prior_candidates),4)
        result=self.api.check_prior_work(['Other mechanism 2']); self.assertEqual(result['total_matches'],1)
        self.assertEqual((self.root/'runs/prior/checkpoint.json').read_bytes(),self.old_bytes)
        self.assertTrue(matching_prior(self.engine.prior_candidates,candidate(mechanism_scope='public profile metadata pointer')))
        self.assertTrue(matching_prior(self.engine.prior_candidates,card('scan-trigger embedded-metadata card')))

    def test_unchanged_discovery_is_deferred_not_rejected_and_local_continuation_is_allowed(self):
        result=self.api.submit_idea(card('scan-trigger embedded-metadata card'))
        self.assertEqual(result['status'],'DEFERRED'); self.assertEqual(self.engine.state['ideas'],[])
        self.assertIn('prior/',result['prior_matches'][0]['ref'])
        self.agent['work_kind']='LOCAL'; self.agent['role']='Prototyper'
        created=self.api.submit_idea(card()); self.assertEqual(created['id'],'IDEA-0001')
        self.assertNotEqual(created['status'],'REJECTED')
        self.assertEqual(created['prior_work_refs'],['prior/IDEA-0002'])

    def test_coordinator_cannot_create_a_discovery_in_novelty_first(self):
        self.agent['role']='Meta-Archivist / Orchestrator'
        result=self.api.submit_idea(candidate(summary='A candidate', id=''))
        self.assertEqual(result['reason'],'COORDINATION_ROLE_NOT_DISCOVERY'); self.assertFalse(self.engine.state['ideas'])

    def test_binding_owner_rejection_takes_precedence_over_prior_deferral(self):
        self.engine.owner_rejections=[{'id':'OWNER-TEST','aliases':['ORCID'],'reason':'Owner explicitly rejected this direction'}]
        result=self.api.submit_idea(candidate(summary='A candidate',id=''))
        self.assertEqual(result['status'],'REJECTED')
        self.assertTrue(result['rejection_reason'].startswith('OWNER_REJECTED:'))

    def test_known_response_at_api_cap_settles_with_ignored_attempt_audited(self):
        output=searches(); tools=Tools(); progress=_Progress([],tools,100000,3)
        class Response:
            def model_dump(inner, **kwargs):
                return {'output':output,'usage':{'input_tokens':100,'output_tokens':10,'total_tokens':110},'raw_usage':{'total_tokens':110}}
        progress.add_response(Response())
        self.assertEqual(progress.usage()['web_search_calls'],3)
        self.assertEqual(sum(k=='web_search_attempt_ignored_at_cap' for k,d in tools.events),1)
        reserve(self.engine.state,self.agent['id'],500,100,3,self.agent['model'])
        for kind,data in tools.events: self.api.record_sdk_event(kind,data)
        self.assertFalse(self.engine.state['budget_reservations']); self.assertEqual(self.engine.state['usage']['web_search_calls'],3)
        self.engine.store.verify()

    def test_unknown_or_genuinely_excessive_search_work_is_not_silently_ignored(self):
        self.assertEqual(len(classify(searches(4),3)[0]),5)
        self.assertEqual(len(classify(searches(2),3)[0]),3)
        output=searches(); output[-1]['action']['sources']=[{'url':'https://example.org'}]
        self.assertEqual(len(classify(output,3)[0]),4)

    async def test_global_unknown_request_stops_scheduler_before_cascade(self):
        record=reserve(self.engine.state,self.agent['id'],500,100,3,self.agent['model'])
        self.engine.state['budget_reservations'][record['id']]['status'] = 'UNKNOWN'
        self.engine.store.commit(self.engine.state,'fixture_request_reserved',record)
        result=await self.engine.run()
        self.assertEqual(result['status'],'BLOCKED'); self.assertIn('RECONCILIATION',result['stop_reason'])
        self.assertEqual(result['steps'],0); self.assertTrue(all(a['status']=='PENDING' for a in result['agents']))


@unittest.skipUnless(SDK_AVAILABLE,'SDK optional dependency unavailable')
class SearchSDKTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_preserves_three_completed_plus_ignored_attempt(self):
        from tests.test_backend import FakeProvider, response, final_response, CONFIG, AGENT
        from openai.types.responses import ResponseFunctionWebSearch
        from metaweb_swarm.backend import OpenAIBackend
        output=[ResponseFunctionWebSearch.model_validate(i) for i in searches()]
        provider=FakeProvider([response([*output,*final_response().output])]); tools=Tools()
        result=await OpenAIBackend(provider).step(AGENT,'Review primary evidence',[],tools,CONFIG|{'max_web_search_calls_per_request':3})
        self.assertEqual(result['usage']['web_search_calls'],3)
        self.assertEqual(len([i for i in result['raw']['responses'][0]['output'] if i['type']=='web_search_call']),4)
        self.assertEqual(provider.model.calls[0][1]['model_settings'].extra_args['max_tool_calls'],3)
