"""Typed feasibility and cross-role evidence without relaxing execution gates."""
import json
import unittest
from unittest.mock import patch
from metaweb_swarm.backend import OpenAIBackend, _make_sdk_tools
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine, refresh_reports
from tests.test_backend import SDK_AVAILABLE
from tests import test_focused_tasking as focused

class AuditQualificationTests(unittest.IsolatedAsyncioTestCase):
    setUp = focused.FocusedTests.setUp
    tearDown = focused.FocusedTests.tearDown
    for_agent = focused.FocusedTests.for_agent
    def plan(self, **changes):
        data={'provider':'Source-backed fixture carrier','export_path':'build.epub',
              'documentation_urls':[self.origin+'/docs',self.origin+'/terms'],
              'upload_url':self.origin+'/file','method':'PUT','authentication':'ANONYMOUS','credential_id':'',
              'required_external_actions':1,'novelty_class':'POTENTIALLY_NEW','baseline_evidence_ids':[],
              'baseline_behavior':'','proposed_change':'','validation_plan':''}
        data.update(changes);return data
    async def sources(self):
        for path in ('/docs','/terms'):await self.api.read_document(self.origin+path,'Read actual write API/terms')

    async def test_unresolved_endpoint_auth_and_known_claims_are_audited_not_invented(self):
        await self.sources()
        missing=self.api.check_deposit_target(self.plan(upload_url='',authentication='UNKNOWN'))
        self.assertEqual(missing['status'],'TARGET_DETAILS_REQUIRED');self.assertFalse(missing['admissible'])
        self.assertIn('AUTHENTICATION_UNVERIFIED',missing['reasons'])
        auth=self.api.check_deposit_target(self.plan(authentication='UNKNOWN'))
        self.assertEqual(auth['status'],'AUTHENTICATION_UNVERIFIED');self.assertFalse(auth['admissible'])
        known=self.api.check_deposit_target(self.plan(novelty_class='KNOWN_CARRIER'))
        self.assertEqual(known['status'],'BASELINE_COMPARISON_REQUIRED')
        account=self.api.check_deposit_target(self.plan(authentication='ACCOUNT_REQUIRED'))
        self.assertEqual(account['status'],'ACCOUNT_SETUP_REQUIRED');self.assertTrue(account['admissible'])
        forbidden=self.api.check_deposit_target(self.plan(upload_url='https://gitlab.com/api/files',authentication='UNKNOWN'))
        self.assertEqual(forbidden['status'],'POLICY_FORBIDDEN')
        self.assertFalse(self.engine.state['external_actions']);self.assertFalse(self.engine.state['approvals'])
        self.assertGreaterEqual(len(self.engine.state['deposit_qualifications']),5)

    async def test_reporter_reads_shared_response_without_own_receipt_and_after_private_change(self):
        r=await self.api.read_document(self.origin+'/docs','Read source-backed upload API')
        request=self.engine.state['http_requests'][-1]
        self.assertTrue(request['audit_artifact']['path'].startswith('audit/http/'))
        reporter=self.for_agent(self.engine.state['agents'][3])
        result=reporter.read_audit_artifact(r['request_id'])
        self.assertIn('POST /file',result['text']);self.assertFalse(result['legacy_workspace_source'])
        self.assertEqual(result['owner_agent_id'],self.agent['id']);self.assertEqual(result['sha256'],r['sha256'])
        self.api.workspace.write_file(r['response_path'],'changed private file')
        self.assertIn('POST /file',reporter.read_audit_artifact(r['request_id'])['text'])
        self.assertFalse(reporter.agent.get('http_document_reads'));self.assertFalse(reporter.agent.get('external_sources'))
        self.assertEqual(len(self.server.calls),1)
        refresh_reports(self.engine.store,self.engine.state)
        manifest=json.loads((self.run/'manifest.json').read_text(encoding='utf-8'))
        indexed=next(a for a in manifest['artifacts'] if a['path']==request['audit_artifact']['path'])
        self.assertEqual(indexed['sha256'],r['sha256'])
        self.assertIn('Posouzení cílových plánů:',(self.run/'SWARM_REPORT.md').read_text(encoding='utf-8'))
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        again=self.for_agent(self.engine.state['agents'][3]).read_audit_artifact(r['request_id'])
        self.assertEqual(again['sha256'],r['sha256']);self.engine.store.verify()

    async def test_shared_capture_failure_preserves_known_http_outcome(self):
        with patch('metaweb_swarm.audit_artifacts.capture', side_effect=RuntimeError('fixture disk error')):
            result=await self.api.read_document(self.origin+'/docs','Read successful HTTP despite shared copy failure')
        self.assertEqual(result['status'],'COMPLETED')
        record=self.engine.state['http_requests'][-1]
        self.assertEqual(record['status'],'COMPLETED');self.assertEqual(record['audit_artifact_error'],'RuntimeError')
        legacy=self.for_agent(self.engine.state['agents'][3]).read_audit_artifact(record['id'])
        self.assertEqual(legacy['status'],'COMPLETED');self.assertTrue(legacy['legacy_workspace_source'])

    async def test_legacy_source_supported_but_changed_bytes_blocked(self):
        r=await self.api.read_document(self.origin+'/docs','Read legacy document fixture')
        self.engine.state['http_requests'][-1].pop('audit_artifact')
        reporter=self.for_agent(self.engine.state['agents'][3])
        result=reporter.read_audit_artifact(r['request_id']);self.assertTrue(result['legacy_workspace_source'])
        self.api.workspace.write_file(r['response_path'],'tampered')
        self.assertEqual(reporter.read_audit_artifact(r['request_id'])['reason'],'AUDIT_ARTIFACT_CHANGED')

    async def test_unknown_private_changed_and_traversal_artifacts_are_denied(self):
        r=await self.api.read_document(self.origin+'/docs','Read recorded source fixture')
        reporter=self.for_agent(self.engine.state['agents'][3]);record=self.engine.state['http_requests'][-1]
        for value in ('../checkpoint.json',r'G:\secret.txt', 'HTTP-../secret'):
            with self.assertRaises(ValueError):reporter.read_audit_artifact(value)
        self.assertEqual(reporter.read_audit_artifact('HTTP-'+'f'*16)['reason'],'AUDIT_REQUEST_NOT_FOUND')
        record['privileged']=True
        self.assertEqual(reporter.read_audit_artifact(r['request_id'])['reason'],'AUDIT_PUBLIC_GET_REQUIRED')
        record['privileged']=False
        original=record['audit_artifact']['path'];record['audit_artifact']['path']='checkpoint.json'
        self.assertEqual(reporter.read_audit_artifact(r['request_id'])['reason'],'AUDIT_ARTIFACT_PATH_MISMATCH')
        record['audit_artifact']['path']=original
        (self.run/original).write_bytes(b'tampered shared bytes')
        self.assertEqual(reporter.read_audit_artifact(r['request_id'])['reason'],'AUDIT_ARTIFACT_CHANGED')
        self.assertEqual(len(self.server.calls),1)

    async def test_shared_reads_never_satisfy_independent_auditor(self):
        await self.sources();q=self.api.check_deposit_target(self.plan())
        proposal=DemoBackend.idea('Source-backed fixture carrier','Public exact-byte deposit','FREE','DISCOVERED')
        proposal.update(provider=q['plan']['provider'],qualification_id=q['id'])
        idea=self.api.submit_idea(proposal);review=self.for_agent(self.engine.state['agents'][1])
        for r in self.engine.state['http_requests']:review.read_audit_artifact(r['id'])
        self.assertFalse(review.agent.get('http_document_reads'))
        self.assertEqual(review.record_critique(idea['id'],'PASS','Read shared response excerpts')['reason'],'AUDIT_QUALIFIED_DOCS_REQUIRED')
        for path in ('/docs','/terms'):await review.read_document(self.origin+path,'Independent read of actual sources')
        self.assertEqual(review.record_critique(idea['id'],'PASS','Own independent docs support operation')['verdict'],'PASS')

    def test_forbidden_targets_and_shared_reading_in_role_prompt(self):
        prompt=self.engine.prompt(self.agent)
        for host in ('github.com','gitlab.com','codeberg.org','vojtamaur.cz'):
            self.assertIn(host,prompt)
        self.assertIn('read_audit_artifact(request_id)',prompt)
        self.assertIn('authentication UNKNOWN',self.agent['mission'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_named_defaults_and_cross_role_read_dispatch(self):
        import agents as sdk
        from tests.test_backend import FakeProvider,tool_response,final_response
        await self.sources()
        tools,_=_make_sdk_tools(sdk,self.api);qual=next(t for t in tools if t.name=='check_deposit_target')
        self.assertNotIn('plan_json',qual.params_json_schema['properties'])
        self.assertIn('upload_url',qual.params_json_schema['properties'])
        self.assertIn('UNKNOWN',json.dumps(qual.params_json_schema['properties']['authentication']))
        provider=FakeProvider([tool_response('check_deposit_target',{'provider':'Documented unresolved service','export_path':'build.epub',
            'documentation_urls':[self.origin+'/docs',self.origin+'/terms']}),final_response()])
        await OpenAIBackend(provider).step(self.agent,self.engine.prompt(self.agent),[],self.api,self.config)
        self.assertEqual(self.engine.state['deposit_qualifications'][-1]['status'],'TARGET_DETAILS_REQUIRED')
        reporter=self.engine.state['agents'][3];request_id=self.engine.state['http_requests'][0]['id']
        provider=FakeProvider([tool_response('read_audit_artifact',{'request_id':request_id,'offset':0,'limit':8000}),final_response()])
        result=await OpenAIBackend(provider).step(reporter,self.engine.prompt(reporter),[],self.for_agent(reporter),self.config)
        outputs=[json.loads(i['output']) for i in result['history'] if i.get('type')=='function_call_output']
        self.assertEqual(outputs[0]['status'],'COMPLETED');self.assertIn('POST /file',outputs[0]['text'])
