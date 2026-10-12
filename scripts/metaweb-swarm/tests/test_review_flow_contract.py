"""Review meaning and mandatory short flow task; actual SDK, no paid inference."""
import copy
import json
import unittest
from metaweb_swarm.backend import OpenAIBackend
from metaweb_swarm.deposit_handoff import recover
from metaweb_swarm.flow_capture import pending
from metaweb_swarm.review_contract import complete_review
from metaweb_swarm.policy import normalize_output
from tests import test_deposit_handoff as handoff
from tests.test_backend import SDK_AVAILABLE

class ContractTests(unittest.IsolatedAsyncioTestCase):
    setUp=handoff.HandoffTests.setUp
    tearDown=handoff.HandoffTests.tearDown
    for_agent=handoff.HandoffTests.for_agent
    plan=handoff.HandoffTests.plan
    sources=handoff.HandoffTests.sources
    qualified=handoff.HandoffTests.qualified

    async def setup_candidate(self,flow_required=False):
        self.engine.state['config']['require_explicit_upload_flow']=flow_required
        q=await self.qualified(authentication='ACCOUNT_REQUIRED')
        recover(self.engine)
        return q,self.engine.state['ideas'][0],self.for_agent(self.engine.state['agents'][1])

    async def test_setup_reject_is_revise_and_requested_verdict_is_preserved(self):
        q,idea,review=await self.setup_candidate()
        first=review.record_critique(idea['id'],'REVISE','Dedicated credential is missing')
        result=review.record_critique(idea['id'],'REJECT','No key or completed upload means cannot PASS')
        self.assertEqual(result['verdict'],'REVISE');self.assertEqual(result['requested_verdict'],'REJECT')
        self.assertEqual(idea['status'],'BLOCKED');self.assertIn('REJECT_REQUIRES',result['verdict_adjustment'])
        self.assertEqual(len(self.engine.state['critiques']),2)
        self.engine.store.verify()

    async def test_evidence_gap_never_rejects_even_with_source_and_missing_format_fact(self):
        q,idea,review=await self.setup_candidate()
        url=self.origin+'/docs';await review.read_document(url,'Read supported formats independently')
        result=review.record_critique(idea['id'],'REJECT','EPUB is not documented, needs a test',
                'EVIDENCE_GAP','FORMAT_PROHIBITED','No EPUB is mentioned',[url])
        self.assertEqual(result['verdict'],'REVISE');self.assertEqual(idea['status'],'BLOCKED')

    async def test_genuine_failure_requires_independent_read_and_explicit_failure_fact(self):
        q,idea,review=await self.setup_candidate()
        result=review.record_critique(idea['id'],'REJECT','Published policy prohibits automated upload',
               'MECHANISM_FAILURE','AUTOMATION_PROHIBITED','Automated uploads are explicitly prohibited',[self.origin+'/docs'])
        self.assertEqual(result['verdict'],'REVISE')
        class Prohibition(handoff.focused.Documents):
            def do_GET(inner):
                inner.server.calls.append(inner.path)
                data=b'Automated uploads are explicitly prohibited'
                inner.send_response(200);inner.send_header('Content-Type','text/plain');inner.end_headers();inner.wfile.write(data)
        self.server.RequestHandlerClass=Prohibition
        await review.read_document(self.origin+'/docs','Read policy evidence independently')
        result=review.record_critique(idea['id'],'REJECT','Published policy prohibits automated upload',
               'MECHANISM_FAILURE','AUTOMATION_PROHIBITED','Automated uploads are explicitly prohibited',[self.origin+'/docs'])
        self.assertEqual(result['verdict'],'REJECT');self.assertEqual(idea['status'],'REJECTED')
        self.assertIn('negative_source_quote',result)
        revise=review.record_critique(idea['id'],'REVISE','Credential is missing','SETUP_GAP')
        self.assertEqual(idea['critique']['id'],result['id']);self.assertIn('current_verdict_preserved',revise)
        # Source provenance proves only access; negative claim itself is not certified.
        self.assertIn('not host certification',result['meaning'])

    async def test_owner_cannot_certify_its_own_negative_claim(self):
        q,idea,review=await self.setup_candidate()
        result=self.api.record_critique(idea['id'],'REJECT','Automated uploads forbidden','MECHANISM_FAILURE',
              'AUTOMATION_PROHIBITED','Automated uploads explicitly forbidden',[self.origin+'/docs'])
        self.assertEqual(result['verdict'],'REVISE')

    async def test_audit_completed_with_setup_handoff_does_not_become_continue_or_rejected_role(self):
        q,idea,review=await self.setup_candidate()
        review.record_critique(idea['id'],'REVISE','Credential missing','SETUP_GAP')
        raw={'status':'COMPLETED','reason_for_stopping':'Audit done','summary':'Needs setup','unexplored_leads':['Obtain key and upload'],
             'handoff_leads':[],'blind_spots':[]}
        output,note=complete_review(self.engine.state,review.agent,raw,normalize_output(raw))
        self.assertEqual(output['status'],'COMPLETED');self.assertEqual(output['unexplored_leads'],[])
        self.assertIn('Obtain key and upload',output['handoff_leads'])
        raw['status']='REJECTED'
        output,note=complete_review(self.engine.state,review.agent,raw,normalize_output(raw))
        self.assertEqual(output['status'],'COMPLETED');self.assertEqual(idea['status'],'BLOCKED')

    async def test_audit_without_current_critique_cannot_claim_completed(self):
        q,idea,review=await self.setup_candidate()
        raw={'status':'COMPLETED','reason_for_stopping':'Audit done','summary':'Claims only','unexplored_leads':[],'handoff_leads':[],'blind_spots':[]}
        output,note=complete_review(self.engine.state,review.agent,raw,normalize_output(raw))
        self.assertEqual(output['status'],'BLOCKED');self.assertIn('AUDIT_RECEIPT_REQUIRED',output['reason_for_stopping'])

    async def test_flow_capture_requalifies_same_candidate_and_derives_three_actions(self):
        q,idea,review=await self.setup_candidate(True)
        self.assertEqual(pending(self.engine.state,self.agent),q['id'])
        result=self.api.record_deposit_flow(q['id'],handoff.multi())
        self.assertEqual(result['status'],'RECORDED');self.assertEqual(result['external_actions_required'],3)
        self.assertEqual(len(self.engine.state['ideas']),1)
        current=self.engine.state['ideas'][0]
        self.assertEqual(current['id'],idea['id']);self.assertEqual(current['blocker'],'RESOURCE_LIMIT')
        self.assertEqual(current['deposit_plan']['required_external_actions'],3)
        self.assertIsNone(pending(self.engine.state,self.agent))
        self.assertEqual(self.api.record_deposit_flow(q['id'],handoff.multi()),result)
        self.assertFalse(self.engine.state['external_actions'])

    async def test_unknown_flow_is_explicit_and_never_fabricates_steps(self):
        q,idea,review=await self.setup_candidate(True)
        with self.assertRaises(ValueError):self.api.record_deposit_flow(q['id'],[])
        result=self.api.record_deposit_flow(q['id'],[],'Documentation does not explain upload finalization')
        self.assertEqual(result['status'],'UNKNOWN');self.assertEqual(idea['deposit_plan']['operation_steps'],[])
        self.assertIsNone(pending(self.engine.state,self.agent))
        self.assertFalse(self.engine.state['approvals'])

    async def test_other_role_or_wrong_qualification_cannot_change_flow(self):
        q,idea,review=await self.setup_candidate(True)
        with self.assertRaises(ValueError):review.record_deposit_flow(q['id'],handoff.multi())
        with self.assertRaises(ValueError):self.api.record_deposit_flow('QUAL-invalid',handoff.multi())

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_forces_flow_tool_once_and_engine_completes_handoff(self):
        from tests.test_backend import FakeProvider,tool_response,final_response,FINAL
        q,idea,review=await self.setup_candidate(True)
        final=dict(FINAL,status='CONTINUE',unexplored_leads=['Obtain key, deploy and verify'])
        provider=FakeProvider([tool_response('record_deposit_flow',{'qualification_id':q['id'],
            'operation_steps':handoff.multi(),'unknown_reason':''}),final_response(output=final)])
        self.engine.backend=OpenAIBackend(provider)
        await self.engine.step(self.agent)
        self.assertEqual(self.agent['status'],'COMPLETED')
        self.assertEqual(self.engine.state['ideas'][0]['deposit_plan']['required_external_actions'],3)
        first=provider.model.calls[0][1]['model_settings'];second=provider.model.calls[1][1]['model_settings']
        self.assertEqual(first.tool_choice,'record_deposit_flow');self.assertIn(second.tool_choice,(None,'auto'))
        self.assertEqual(self.agent['unexplored_leads'],[])
        self.assertIn('Obtain key, deploy and verify',self.agent['handoff_leads'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_model_ignoring_required_flow_is_blocked_without_repeat_or_success_claim(self):
        from tests.test_backend import FakeProvider,final_response
        q,idea,review=await self.setup_candidate(True)
        self.engine.backend=OpenAIBackend(FakeProvider([final_response()]))
        await self.engine.step(self.agent)
        self.assertEqual(self.agent['status'],'BLOCKED')
        self.assertIn('FLOW_NOT_RECORDED',self.agent['reason_for_stopping'])
        self.assertEqual(idea['deposit_plan']['operation_steps'],[])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_typed_review_cannot_replace_setup_with_rejection(self):
        from tests.test_backend import FakeProvider,tool_response,final_response
        q,idea,review=await self.setup_candidate()
        provider=FakeProvider([tool_response('record_critique',{'idea_id':idea['id'],'verdict':'REJECT','reason':'No key supplied',
             'decision_basis':'SETUP_GAP','failure_kind':'NONE','failure_fact':'','negative_evidence_urls':[]}),final_response()])
        await OpenAIBackend(provider).step(review.agent,self.engine.prompt(review.agent),[],review,self.config)
        self.assertEqual(idea['critique']['verdict'],'REVISE')

    async def test_invented_failure_fact_or_changed_source_cannot_ground_rejection(self):
        q,idea,review=await self.setup_candidate()
        r=await review.read_document(self.origin+'/docs','Read actual provider source')
        result=review.record_critique(idea['id'],'REJECT','Unsupported negative claim',
           'MECHANISM_FAILURE','AUTOMATION_PROHIBITED','Automated uploads explicitly forbidden',[self.origin+'/docs'])
        self.assertEqual(result['verdict'],'REVISE')
        review.workspace.write_file(r['response_path'],'Automated uploads explicitly forbidden')
        result=review.record_critique(idea['id'],'REJECT','Forged negative source claim',
           'MECHANISM_FAILURE','AUTOMATION_PROHIBITED','Automated uploads explicitly forbidden',[self.origin+'/docs'])
        self.assertEqual(result['verdict'],'REVISE')
        self.assertNotEqual(idea['status'],'REJECTED')
