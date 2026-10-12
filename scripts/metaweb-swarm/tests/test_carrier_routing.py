"""Real local HTTP and installed SDK; no OpenAI API or public mutations."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from metaweb_swarm.baseline import BaselineCorpus
from metaweb_swarm.carrier_screening import registry_matches
from metaweb_swarm.config import validate_config
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine, refresh_reports
from tests import test_focused_tasking as focused
from tests.test_backend import SDK_AVAILABLE

ARCHIVE = """ALTERNATIVE DEPLOYMENTS:
    ArDrive / Arweave
    https://app.ardrive.io/#/file/deployed/view
    https://arweave.net/deployed
    Cloudflare Pages
    https://owner.pages.dev/
ARCHIVAL COPIES AND DISTRIBUTIONS:
    OSF registration (proposed)
    https://osf.io/proposal
VIDEO SNAPSHOTS (YouTube-derived archival copies):
    YouTube
    https://youtube.com/watch?v=existing
NOTES:
    Bare mention service
    https://mentioned.example.org/
"""

class RoutingTests(unittest.IsolatedAsyncioTestCase):
    tearDown = focused.FocusedTests.tearDown
    for_agent = focused.FocusedTests.for_agent
    def setUp(self):
        focused.FocusedTests.setUp(self)
        self.engine.state['config']['carrier_screening']=True
        self.engine.state['config']['allow_known_carrier_improvements']=True
        archive=self.run/'snapshot/public/ARCHIVE.txt'
        archive.parent.mkdir(exist_ok=True)
        archive.write_text(ARCHIVE,encoding='utf-8')
        self.engine.baseline=BaselineCorpus(self.run)

    def test_register_pair_mentions_and_product_boundaries(self):
        r=self.api.screen_carrier('ArDrive','https://upload.ardrive.io/')
        self.assertEqual(r['status'],'EXISTING_LAYER');self.assertFalse(r['research_allowed'])
        entry=r['registered_entries'][0]
        self.assertEqual(entry['label'],'ArDrive / Arweave');self.assertEqual(entry['label_line'],2)
        self.assertEqual(entry['url_line'],3);self.assertEqual(len(entry['document_sha256']),64)
        self.assertEqual(self.api.screen_carrier('Arweave','https://arweave.net/')['status'],'EXISTING_LAYER')
        self.assertEqual(self.api.screen_carrier('OSF','https://osf.io/')['status'],'BASELINE_MENTION_REVIEW')
        self.assertEqual(self.api.screen_carrier('Bare mention service','https://mentioned.example.org/')['status'],'BASELINE_MENTION_REVIEW')
        self.assertEqual(self.api.screen_carrier('Cloudflare R2','https://developers.cloudflare.com/r2/')['status'],'NO_MATCH_FOUND')
        self.assertEqual(self.api.screen_carrier('YouTube','https://youtube.com/')['status'],'EXISTING_LAYER')
        self.assertEqual(self.api.screen_carrier('Unknown fixture','https://unknown.example.org/')['status'],'NO_MATCH_FOUND')

    def test_non_archive_post_or_missing_url_does_not_prove_existing(self):
        baseline=SimpleNamespace(documents=[
            {'path':'snapshot/src/content/posts/essay.mdx','sha256':'a'*64,'lines':ARCHIVE.splitlines()},
            {'path':'snapshot/public/ARCHIVE.txt','sha256':'b'*64,'lines':['ALTERNATIVE DEPLOYMENTS:', '    Unknown fixture', '    No actual URL']}
        ])
        self.assertEqual(registry_matches(baseline,'ArDrive','app.ardrive.io'),[])
        self.assertEqual(registry_matches(baseline,'Unknown fixture','unknown.example.org'),[])

    async def test_switch_is_enforced_persisted_and_new_carrier_unlocks_docs(self):
        r=await self.api.read_document(self.origin+'/docs','Read concrete candidate API')
        self.assertEqual(r['reason'],'CARRIER_SCREEN_REQUIRED');self.assertEqual(self.server.calls,[])
        self.api.screen_carrier('ArDrive','https://upload.ardrive.io/')
        r=await self.api.read_document(self.origin+'/docs','Attempt unchanged known carrier docs')
        self.assertEqual(r['reason'],'SWITCH_CARRIER_REQUIRED');self.assertEqual(self.server.calls,[])
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        self.agent=self.engine.state['agents'][0];self.api=self.for_agent(self.agent)
        self.assertIn('EXISTING_LAYER',self.engine.prompt(self.agent))
        self.assertEqual((await self.api.read_document(self.origin+'/docs','Attempt after resume'))['reason'],'SWITCH_CARRIER_REQUIRED')
        self.api.screen_carrier('Unrelated carrier',self.origin+'/docs')
        self.assertEqual((await self.api.read_document(self.origin+'/docs','Read new concrete candidate API'))['status'],'COMPLETED')
        self.assertEqual(self.server.calls,['/docs'])
        self.engine.store.verify()

    async def test_explicit_improvement_reopens_research_but_not_approval(self):
        self.api.screen_carrier('ArDrive','https://upload.ardrive.io/')
        r=self.api.screen_carrier('ArDrive','https://upload.ardrive.io/',
            'Existing web deployment', 'Additional independent exact EPUB custody', 'Verify independent public EPUB bytes')
        self.assertEqual(r['status'],'IMPROVEMENT_REVIEW')
        self.assertTrue(r['research_allowed']);self.assertNotIn('carrier_switch_required',self.agent)
        self.assertTrue(self.engine.state['config']['approval_required'])
        self.assertEqual(self.engine.state['approvals'],[]);self.assertEqual(self.engine.state['ideas'],[])
        self.assertEqual((await self.api.read_document(self.origin+'/docs','Read unscreened improved API'))['reason'],'CARRIER_DOCUMENT_ORIGIN_NOT_SCREENED')
        self.api.screen_carrier('ArDrive',self.origin+'/docs','Existing web deployment','Additional independent exact EPUB custody','Verify independent public EPUB bytes')
        self.assertEqual((await self.api.read_document(self.origin+'/docs','Read screened improved API'))['status'],'COMPLETED')
        self.assertIn('independent audit',r['meaning'])

    def test_owner_rejection_and_write_policy_are_not_credential_setup(self):
        self.assertEqual(self.api.screen_carrier('WACZ','https://example.org/')['status'],'OWNER_REJECTED')
        self.assertEqual(self.api.screen_carrier('GitLab','https://gitlab.com/')['status'],'POLICY_FORBIDDEN')
        r=self.api.screen_carrier('GitLab','https://gitlab.com/', 'Old', 'New', 'Test')
        self.assertEqual(r['status'],'POLICY_FORBIDDEN')

    async def test_known_qualification_routes_even_with_other_missing_details(self):
        self.api.screen_carrier('Unrelated fixture',self.origin+'/docs')
        for path in ('/docs','/terms'):
            await self.api.read_document(self.origin+path,'Read real upload documentation')
        hits=self.api.check_baseline(['ArDrive'])['matches']
        plan={'provider':'ArDrive','upload_url':'https://upload.ardrive.io/file','method':'POST',
            'authentication':'UNKNOWN','credential_id':'','export_path':'build.epub',
            'required_external_actions':1,'documentation_urls':[self.origin+'/docs',self.origin+'/terms'],
            'novelty_class':'KNOWN_CARRIER','baseline_evidence_ids':[h['id'] for h in hits],
            'baseline_behavior':'','proposed_change':'','validation_plan':''}
        q=self.api.check_deposit_target(plan)
        self.assertIn('ALREADY_KNOWN_BASELINE',q['reasons'])
        self.assertIn('DIFFERENT',q['next_action'])
        self.assertEqual((await self.api.read_document(self.origin+'/docs','Read already rejected carrier docs'))['reason'],'SWITCH_CARRIER_REQUIRED')
        r=self.api.screen_carrier('ArDrive','https://upload.ardrive.io/')
        self.assertFalse(r['research_allowed'])
        self.assertEqual(len(self.server.calls),2);self.assertEqual(self.engine.state['ideas'],[])

    async def test_other_roles_and_optout_can_read_without_screen(self):
        auditor=self.for_agent(self.engine.state['agents'][1])
        self.assertEqual((await auditor.read_document(self.origin+'/docs','Independent audit docs'))['status'],'COMPLETED')
        self.api.screen_carrier('ArDrive','https://upload.ardrive.io/')
        self.engine.state['config']['carrier_screening']=False
        self.assertEqual((await self.api.read_document(self.origin+'/terms','Explicit operator optout'))['status'],'COMPLETED')
        with self.assertRaises(ValueError):validate_config(dict(self.config,carrier_screening='yes'))

    async def test_redirect_returns_relative_target_without_follow_and_explicit_get_reads(self):
        self.api.screen_carrier('Unrelated fixture',self.origin+'/redirect')
        r=await self.api.read_document(self.origin+'/redirect','Read redirected API docs')
        self.assertEqual(r['status'],'DEFERRED');self.assertEqual(r['redirect_url'],self.origin+'/docs')
        self.assertEqual(self.server.calls,['/redirect'])
        self.assertFalse(self.agent.get('http_document_reads'))
        self.assertEqual((await self.api.read_document(r['redirect_url'],'Explicitly follow validated document target'))['status'],'COMPLETED')
        self.assertEqual(self.server.calls,['/redirect','/docs'])
        self.assertEqual(len(self.engine.state['http_requests']),2)

    async def test_unsafe_redirects_never_emit_target_or_follow(self):
        self.api.screen_carrier('Unrelated fixture',self.origin+'/redirect')
        for location in ('https://127.0.0.1/x', 'http://example.org/docs', 'file:///private',
                         'https://user:pass@example.org/docs','https://example.org/?%74oken=secret',
                         'https://example.org/?api-key=secret','/redirect','','https://example.org/?signature=private'):
            with self.subTest(location=location):
                record={'id':'HTTP-fixture','status':'COMPLETED','action':{'payload':{'url':self.origin+'/redirect'}},
                    'response':{'status':301,'headers':{'Location':location}}}
                with patch.object(self.api,'http_request',new=AsyncMock(return_value=record)) as transport:
                    r=await self.api.read_document(self.origin+'/redirect','Read redirect security fixture')
                self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['redirect_url'])
                self.assertEqual(transport.await_count,1)
        self.assertEqual(self.server.calls,[]);self.assertFalse(self.agent.get('http_document_reads'))

    def test_report_manifest_include_original_screen_and_current_assignment(self):
        self.api.screen_carrier('ArDrive','https://upload.ardrive.io/')
        refresh_reports(self.engine.store,self.engine.state)
        manifest=json.loads((self.run/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['carrier_screens'][0]['registered_entries'][0]['label'],'ArDrive / Arweave')
        self.assertEqual(manifest['agents'][0]['carrier_switch_required']['reason'],'EXISTING_LAYER')
        report=(self.run/'SWARM_REPORT.md').read_text(encoding='utf-8')
        self.assertIn('EXISTING_LAYER',report);self.assertIn('label_line',report)
        self.engine.store.verify()

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_real_sdk_screen_then_document_no_paid_inference(self):
        from metaweb_swarm.backend import OpenAIBackend
        from tests.test_backend import FakeProvider,tool_response,final_response
        self.config['carrier_screening']=True
        provider=FakeProvider([
            tool_response('screen_carrier',{'provider':'Unrelated fixture','service_url':self.origin+'/docs',
                'baseline_behavior':'','proposed_change':'','validation_plan':''}),
            tool_response('read_document',{'url':self.origin+'/docs','purpose':'Read the actual API docs','offset':0,'limit':12000},ident='call-docs'),
            final_response()])
        result=await OpenAIBackend(provider).step(self.agent,self.engine.prompt(self.agent),[],self.api,self.config)
        outputs=[json.loads(i['output']) for i in result['history'] if i.get('type')=='function_call_output']
        self.assertEqual(outputs[0]['status'],'NO_MATCH_FOUND');self.assertEqual(outputs[1]['status'],'COMPLETED')
        self.assertIn('POST /file',outputs[1]['text']);self.assertEqual(self.server.calls,['/docs'])
        self.assertEqual(len(self.engine.state['carrier_screens']),1)

