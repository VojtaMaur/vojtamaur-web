import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from metaweb_swarm.backend import OpenAIBackend, _make_sdk_tools
from metaweb_swarm.candidate_gate import comparison_request, validate_decision
from metaweb_swarm.config import load_config
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine, ToolAPI, initialize
from metaweb_swarm.workspace import Workspace
from tests.test_backend import SDK_AVAILABLE

if SDK_AVAILABLE:
    import agents as sdk
    from tests.test_backend import FakeProvider, tool_response, final_response, FINAL


class CandidateGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        project = self.root/'project'; project.mkdir(); (project/'site.txt').write_text('Sentinel')
        config = load_config(); config.update(semantic_dedupe=True, run_mode='autonomous', experiments='docker', model='research-model', model_tiers={'cheap':'judge-model'}, max_total_tokens=3000000)
        self.run = initialize(project, self.root/'runs', config)
        self.engine = Engine(self.run, DemoBackend(), 'demo')
        self.agent = self.engine.state['agents'][1]
        self.workspace = Workspace(self.run/'snapshot', self.run/'agents'/self.agent['id']/'workspace')
        self.api = ToolAPI(self.engine, self.agent, self.workspace)

    def tearDown(self):
        self.engine.close(); self.temp.cleanup()

    def dns(self, scope='multi-string recovery pointer'):
        value = DemoBackend.idea('DNS TXT recovery pointer', 'DNS TXT embeds a manifest hash and recovery URL; concatenate TXT character strings to decode.', 'FREE', 'INVESTIGATING')
        value.update(provider='DNS TXT', mechanism_key='dns-txt-bootstrap', mechanism_scope=scope)
        return value

    def decision(self, candidate, verdict='SAME', target='IDEA-0001'):
        request = self.api.duplicate_request(candidate)
        return {'verdict':verdict, 'existing_id':target, 'reason':'Same DNS transport, pointer payload and concatenating decoder.',
                'candidate_digest':request['candidate_digest'], 'registry_digest':request['registry_digest']}

    def test_real_dns_duplicate_keeps_id_and_both_authors(self):
        first = self.api.submit_idea(self.dns())
        other = self.engine.state['agents'][2]
        api = ToolAPI(self.engine, other, Workspace(self.run/'snapshot', self.run/'agents'/other['id']/'workspace'))
        data = self.dns('self-describing recovery pointer')
        second = api.submit_idea(data, self.decision(data))
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.engine.state['ideas']), 1)
        self.assertEqual(set(second['contributors']), {self.agent['id'], other['id']})
        self.assertEqual(second['submissions'][-1]['claimed']['mechanism_scope'], data['mechanism_scope'])
        self.assertNotEqual(second['status'], 'REJECTED')

    def test_materially_different_payload_gets_own_id(self):
        self.api.submit_idea(self.dns())
        data = self.dns('full-embedded-archive'); data['mechanism'] = 'DNS TXT stores the full archive bytes, no external retrieval URL.'
        record = self.api.submit_idea(data, self.decision(data, 'DISTINCT', ''))
        self.assertEqual(record['id'], 'IDEA-0002')

    def test_same_agent_family_label_is_not_proof_of_same_payload(self):
        self.api.submit_idea(self.dns())
        data=self.dns(); data['mechanism']='DNS TXT stores the complete embedded archive rather than a pointer.'
        self.assertIsNotNone(self.api.duplicate_request(data))
        record=self.api.submit_idea(data,self.decision(data,'DISTINCT',''))
        self.assertEqual(record['id'],'IDEA-0002')

    def test_uncertain_retains_proposal_without_new_id_or_rejection(self):
        self.api.submit_idea(self.dns())
        data = self.dns('ambiguous-feature')
        record = self.api.submit_idea(data, self.decision(data, 'UNCERTAIN', ''))
        self.assertEqual(record['status'], 'DEFERRED')
        self.assertEqual(len(self.engine.state['ideas']), 1)
        self.assertEqual(self.engine.state['pending_candidate_reviews'][0]['candidate']['title'], data['title'])

    def test_stale_or_unknown_comparison_cannot_merge(self):
        self.api.submit_idea(self.dns()); data = self.dns('other-wording')
        decision = self.decision(data); decision['existing_id'] = 'IDEA-9999'
        with self.assertRaises(ValueError): self.api.submit_idea(data, decision)
        decision = self.decision(data)
        self.api.submit_idea(DemoBackend.idea('Different carrier', 'Distinct independent physical storage', 'FREE', 'INVESTIGATING'))
        with self.assertRaises(ValueError): self.api.submit_idea(data, decision)

    def test_files_only_cannot_claim_prototype(self):
        self.api.write_file('work/example.txt', 'example hash')
        data = self.dns(); data.update(status='PROTOTYPED', artifacts=['work/example.txt'])
        result = self.api.submit_idea(data)
        self.assertEqual(result['status'], 'INVESTIGATING')
        self.assertFalse(result['prototype_tested'])

    async def test_successful_test_promotes_but_changed_artifact_cannot_reuse_receipt(self):
        self.api.write_file('work/parser.py', 'assert 2+2==4')
        data=self.dns(); data['artifacts']=['work/parser.py']
        idea=self.api.submit_idea(data)
        with patch('metaweb_swarm.engine.DockerExecutor') as executor:
            executor.return_value.run.return_value={'status':'COMPLETED','returncode':0,'output':'assertion passed'}
            experiment=await self.api.run_experiment(['python','work/parser.py'],idea['id'])
        self.api.record_test(idea['id'],experiment['experiment_id'],'Verify actual parser assertions')
        self.assertEqual(self.api.idea(idea['id'])['status'],'PROTOTYPED')
        self.api.write_file('work/parser.py','raise AssertionError("changed")')
        with self.assertRaisesRegex(ValueError,'Artifact changed'):
            self.api.record_test(idea['id'],experiment['experiment_id'],'Try claiming newer bytes were tested')

    async def test_generated_outputs_can_be_declared_after_captured_experiment(self):
        self.api.write_file('prototype/check.py', 'assert True')
        data = self.dns(); data['artifacts'] = []
        idea = self.api.submit_idea(data)
        def execute(*args):
            self.api.write_file('prototype/specimen.txt', 'generated bytes')
            return {'status':'COMPLETED', 'returncode':0}
        with patch('metaweb_swarm.engine.DockerExecutor') as executor:
            executor.return_value.run.side_effect = execute
            experiment = await self.api.run_experiment(['python','prototype/check.py'], idea['id'])
        data.update(id=idea['id'], artifacts=['prototype/check.py','prototype/specimen.txt'])
        self.api.submit_idea(data)
        receipt = self.api.record_test(idea['id'], experiment['experiment_id'], 'Assertions against generated bytes')
        self.assertEqual({a['path'] for a in receipt['artifacts']}, {'prototype/check.py','prototype/specimen.txt'})
        self.assertEqual(self.api.idea(idea['id'])['status'], 'PROTOTYPED')
        self.api.write_file('prototype/specimen.txt', 'changed later')
        with self.assertRaises(ValueError):
            self.api.record_test(idea['id'], experiment['experiment_id'], 'Cannot reuse with changed bytes')

    async def test_input_export_even_renamed_cannot_be_a_prototype_receipt(self):
        self.api.write_file('exports/input.txt', 'captured public export')
        info = self.workspace.file_info('exports/input.txt')
        self.agent['materialized_exports'] = [{'path':'exports/input.txt', 'export':'original.txt', **info}]
        self.api.write_file('prototype/renamed.txt', 'captured public export')
        data = self.dns(); data['artifacts'] = ['exports/input.txt', 'prototype/renamed.txt']
        idea = self.api.submit_idea(data)
        with patch('metaweb_swarm.engine.DockerExecutor') as executor:
            executor.return_value.run.return_value = {'status':'COMPLETED', 'returncode':0}
            experiment = await self.api.run_experiment(['python','test.py'], idea['id'])
        with self.assertRaisesRegex(ValueError, 'exports alone are inputs'):
            self.api.record_test(idea['id'], experiment['experiment_id'], 'Only input bytes were declared')
        self.assertFalse(self.api.idea(idea['id'])['prototype_tested'])

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK required')
    async def test_real_sdk_semantic_gate_counts_cheap_usage_without_replacing_history(self):
        self.api.submit_idea(self.dns()); data = self.dns('self-describing recovery pointer')
        tools, _ = _make_sdk_tools(sdk, self.api)
        schema = next(t.params_json_schema for t in tools if t.name == 'submit_idea')['properties']['idea']
        # Nested Idea schema is a $ref in current SDK.
        model_schema = next(t.params_json_schema for t in tools if t.name == 'submit_idea')
        if '$ref' in schema: schema = model_schema['$defs'][schema['$ref'].split('/')[-1]]
        defaults = {'scores_json':'{}', 'payment':'FREE', 'status':'INVESTIGATING', 'novelty_class':'UNASSESSED', 'mechanism_kind':'OTHER', 'requires_ongoing_payments':False}
        arrays = {'evidence','failure_domains','artifacts','baseline_evidence_ids'}
        payload = {k: data.get(k, defaults.get(k, [] if k in arrays else '')) for k in schema['properties']}
        provider = FakeProvider([tool_response('submit_idea', {'idea':payload}),
            final_response('judge', {'verdict':'SAME','existing_id':'IDEA-0001','reason':'Same DNS TXT custody, pointer payload and recovery method.'}), final_response()])
        config = dict(self.engine.state['config'], max_web_search_calls_per_request=0)
        result = await OpenAIBackend(provider).step(self.agent, 'Submit this DNS proposal', [], self.api, config)
        self.assertEqual(len(self.engine.state['ideas']), 1)
        self.assertIn('judge-model', provider.models_requested)
        self.assertEqual(self.engine.state['usage']['requests'], 3)
        self.assertEqual(self.engine.state['usage']['by_model']['judge-model']['requests'], 1)
        self.assertFalse(self.engine.state.get('budget_reservations'))
        self.assertEqual(result['output'], FINAL)
        self.assertNotIn('current_run_candidates', json.dumps(self.agent['history']))
