"""Last-run regression: known pseudo-improvement and unrelated docs never dispatch HTTP."""
import copy
import json
import unittest
from metaweb_swarm.baseline import BaselineCorpus
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine
from metaweb_swarm.config import load_config, validate_config
from tests import test_focused_tasking as fixture
from tests.test_backend import SDK_AVAILABLE

ARCHIVE='''ARCHIVAL COPIES AND DISTRIBUTIONS:
    Zenodo
    https://doi.org/10.5281/zenodo.19691321
    Figshare
    https://doi.org/10.6084/m9.figshare.33077810
    Perma.cc
    https://perma.cc/EXAMPLE
ALTERNATIVE DEPLOYMENTS:
    Cloudflare Pages
    https://owner.pages.dev/
'''

class ScopeTests(unittest.IsolatedAsyncioTestCase):
    tearDown=fixture.FocusedTests.tearDown
    for_agent=fixture.FocusedTests.for_agent
    def setUp(self):
        fixture.FocusedTests.setUp(self)
        self.engine.state['config'].update(carrier_screening=True,allow_known_carrier_improvements=False)
        p=self.run/'snapshot/public/ARCHIVE.txt';p.parent.mkdir(exist_ok=True);p.write_text(ARCHIVE,encoding='utf-8')
        self.engine.baseline=BaselineCorpus(self.run)
    def candidate_plan(self,**changes):
        p=dict(provider='Independent fixture',export_path='build.epub',documentation_urls=[self.origin+'/docs',self.origin+'/terms'],
               upload_url=self.origin+'/file',method='POST',authentication='ACCOUNT_REQUIRED',credential_id='',required_external_actions=1,
               novelty_class='POTENTIALLY_NEW',baseline_evidence_ids=[],baseline_behavior='',proposed_change='',validation_plan='',operation_steps=[])
        p.update(changes);return p
    async def docs(self):
        self.api.screen_carrier('Independent fixture',self.origin+'/docs')
        for path in ('/docs','/terms'): await self.api.read_document(self.origin+path,'Read primary candidate API and terms')

    async def test_exact_last_run_zenodo_fake_improvement_cannot_open_figshare(self):
        result=self.api.screen_carrier('Zenodo','https://zenodo.org/',
            'User context says Zenodo is already used',
            'Find whether Zenodo can preserve the retained EPUB bytes as an independent deposit',
            'Check official deposit/upload/publish docs and public download')
        self.assertEqual(result['status'],'EXISTING_LAYER');self.assertFalse(result['research_allowed'])
        self.assertTrue(result['registered_entries'])
        for url in ['https://zenodo.org/developers','https://docs.figshare.com/v2/']:
            self.assertEqual((await self.api.read_document(url,'Read prospective carrier API'))['reason'],'SWITCH_CARRIER_REQUIRED')
        self.assertFalse(self.engine.state.get('http_requests'));self.assertFalse(self.server.calls)
        result=self.api.screen_carrier('Figshare','https://docs.figshare.com/v2/')
        self.assertEqual(result['status'],'EXISTING_LAYER')

    async def test_unknown_provider_screen_does_not_cover_other_origin_or_new_provider_name(self):
        self.api.screen_carrier('Independent fixture',self.origin+'/docs')
        before=len(self.engine.state.get('http_requests',[]))
        r=await self.api.read_document('https://docs.figshare.com/v2/','Read unrelated carrier documentation')
        self.assertEqual(r['reason'],'CARRIER_DOCUMENT_ORIGIN_NOT_SCREENED')
        self.assertEqual(len(self.engine.state.get('http_requests',[])),before)
        self.assertEqual(self.api.screen_carrier('Figshare v2 API','https://docs.figshare.com/v2/')['status'],'EXISTING_LAYER')
        self.assertEqual(self.api.screen_carrier('Perma API','https://docs.perma.cc/')['status'],'EXISTING_LAYER')
        self.assertEqual(self.api.screen_carrier('Cloudflare R2','https://developers.cloudflare.com/r2/')['status'],'NO_MATCH_FOUND')

    async def test_allowed_origin_does_not_need_repeat_screen_for_paging_or_same_origin_redirect(self):
        self.api.screen_carrier('Independent fixture',self.origin+'/redirect')
        redirect=await self.api.read_document(self.origin+'/redirect','Read explicitly screened API redirect')
        doc=await self.api.read_document(redirect['redirect_url'],'Read same-origin redirected API')
        cached=await self.api.read_document(self.origin+'/docs','Read cached screened primary document',offset=10,limit=100)
        self.assertEqual(doc['status'],'COMPLETED');self.assertTrue(cached['cached'])
        self.assertEqual(self.server.calls,['/redirect','/docs'])

    async def test_free_account_based_new_candidate_is_admitted_and_saved_blocked(self):
        await self.docs()
        q=self.api.check_deposit_target(self.candidate_plan())
        self.assertEqual(q['status'],'ACCOUNT_SETUP_REQUIRED');self.assertTrue(q['admissible'])
        data=DemoBackend.idea('Independent free EPUB carrier','Exact retained EPUB public recovery','FREE','DISCOVERED')
        data.update(provider='Independent fixture',qualification_id=q['id'])
        i=self.api.submit_idea(data)
        self.assertEqual(i['status'],'BLOCKED');self.assertEqual(i['payment'],'FREE')
        self.assertEqual(self.engine.state['approvals'],[])

    async def test_qualification_cannot_rename_known_carrier_or_claim_unscreened_docs(self):
        await self.docs()
        known=self.candidate_plan(provider='Figshare v2 API',upload_url='https://api.figshare.com/v2/account/articles',
             novelty_class='IMPROVEMENT',baseline_behavior='Existing Figshare copy',proposed_change='Upload this EPUB',validation_plan='Compare bytes')
        q=self.api.check_deposit_target(known)
        self.assertIn('ALREADY_KNOWN_BASELINE',q['reasons']);self.assertFalse(q['admissible']);self.assertTrue(q['registered_entries'])
        p=self.candidate_plan(documentation_urls=[self.origin+'/docs','https://different.example.org/terms'])
        # Even a claimed observed URL never replaces provider-bound screening.
        self.agent.setdefault('external_sources',[]).append('https://different.example.org/terms')
        q=self.api.check_deposit_target(p)
        self.assertIn('CARRIER_SCOPE_REQUIRED',q['reasons']);self.assertFalse(q['admissible'])

    async def test_screen_scope_survives_restart_and_review_role_stays_independent(self):
        await self.docs()
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        self.agent=self.engine.state['agents'][0];self.api=self.for_agent(self.agent)
        r=await self.api.read_document('https://new.example.org/docs','Read unrelated docs after checkpoint')
        self.assertEqual(r['reason'],'CARRIER_DOCUMENT_ORIGIN_NOT_SCREENED')
        self.assertEqual((await self.api.read_document(self.origin+'/docs','Read correct cached provider docs'))['status'],'COMPLETED')
        reviewer=self.for_agent(self.engine.state['agents'][1])
        self.assertEqual((await reviewer.read_document(self.origin+'/terms','Independent own audit docs'))['status'],'COMPLETED')

    async def test_historical_improvement_screen_does_not_reopen_strict_or_legacy_focused_run(self):
        self.engine.state['config']['allow_known_carrier_improvements']=True
        self.api.screen_carrier('Zenodo',self.origin+'/docs','Existing DOI copy','New bounded alternative recovery representation','Test recovery')
        self.engine.state['config'].pop('allow_known_carrier_improvements')
        r=await self.api.read_document(self.origin+'/docs','Try old improvement after policy default changes')
        self.assertEqual(r['reason'],'SWITCH_CARRIER_REQUIRED');self.assertFalse(self.server.calls)

    def test_profile_preserves_budget_and_allows_general_research_improvements(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        profile=load_config(root/'config.deposit-trial.json');general=load_config(root/'config.research.json')
        self.assertFalse(profile['allow_known_carrier_improvements']);self.assertTrue(general['allow_known_carrier_improvements'])
        self.assertEqual(profile['max_external_actions'],1);self.assertEqual(profile['estimated_budget_usd'],5)
        with self.assertRaises(ValueError):validate_config(dict(profile,allow_known_carrier_improvements='false'))

    def test_old_ready_receipt_cannot_publish_known_carrier_after_strict_policy(self):
        from metaweb_swarm.deposit_qualification import execution_gate
        from metaweb_swarm.deposit_execution import gate
        plan=self.candidate_plan(provider='Zenodo',upload_url='https://zenodo.org/api/deposit/depositions')
        self.engine.state['deposit_qualifications']=[dict(id='QUAL-legacy',status='READY_FOR_AUDIT',plan=plan)]
        idea={'id':'IDEA-legacy','qualification_id':'QUAL-legacy'}
        self.engine.state['ideas'].append(idea)
        self.assertEqual(execution_gate(self.api,idea,{}),'ALREADY_KNOWN_BASELINE')
        self.assertEqual(gate(self.api,{'idea_id':idea['id'],'qualification_id':'QUAL-legacy'}),'ALREADY_KNOWN_BASELINE')

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_installed_sdk_cannot_repeat_last_run_provider_bypass(self):
        from metaweb_swarm.backend import OpenAIBackend
        from tests.test_backend import FakeProvider,tool_response,final_response
        provider=FakeProvider([
            tool_response('screen_carrier',dict(provider='Zenodo',service_url='https://zenodo.org/',baseline_behavior='Existing archive',proposed_change='Upload EPUB',validation_plan='Read docs'),ident='known'),
            tool_response('read_document',dict(url='https://docs.figshare.com/v2/',purpose='Read unscreened carrier',offset=0,limit=1000),ident='other'),final_response()])
        await OpenAIBackend(provider).step(self.agent,self.engine.prompt(self.agent),[],self.api,self.engine.state['config'])
        self.assertFalse(self.engine.state.get('http_requests'));self.assertFalse(self.engine.state['ideas'])
