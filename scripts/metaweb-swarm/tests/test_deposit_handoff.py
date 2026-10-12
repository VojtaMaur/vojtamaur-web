"""Host retention/resume/declared flow; local SDK and HTTP, no paid inference."""
import json
import unittest
from metaweb_swarm.engine import Engine
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.deposit_handoff import recover,report_revision
from tests import test_focused_tasking as focused
from tests import test_audit_qualification as qualification

def single():
    return [{'method':'POST','purpose':'Upload exact export bytes','sends_export':True,'uses_credential':False}]
def multi():
    return [{'method':'POST','purpose':'Reserve an upload slot','sends_export':False,'uses_credential':True},
            {'method':'PUT','purpose':'Send export to returned URL','sends_export':True,'uses_credential':False},
            {'method':'POST','purpose':'Finalize and obtain public link','sends_export':False,'uses_credential':True}]

class HandoffTests(unittest.IsolatedAsyncioTestCase):
    setUp=focused.FocusedTests.setUp
    tearDown=focused.FocusedTests.tearDown
    for_agent=focused.FocusedTests.for_agent
    def plan(self,**changes):
        changes.setdefault('method','POST')
        return qualification.AuditQualificationTests.plan(self,**changes)
    sources=qualification.AuditQualificationTests.sources

    async def qualified(self,**changes):
        await self.sources()
        return self.api.check_deposit_target(self.plan(**changes))

    async def test_setup_candidate_retained_even_without_model_submission_and_no_false_claim(self):
        q=await self.qualified(authentication='ACCOUNT_REQUIRED')
        self.assertTrue(q['admissible']);self.assertEqual(q['admission_kind'],'BLOCKED_LEAD')
        recover(self.engine)
        idea=self.engine.state['ideas'][0]
        self.assertEqual(idea['qualification_id'],q['id']);self.assertEqual(idea['status'],'BLOCKED')
        self.assertEqual(idea['payment'],'UNKNOWN');self.assertFalse(idea['prototype_tested'])
        self.assertEqual(idea['blocker'],'ACCOUNT_SETUP_REQUIRED');self.assertTrue(idea['host_retained_deposit_draft'])
        recover(self.engine);self.assertEqual(len(self.engine.state['ideas']),1)
        self.assertFalse(self.engine.state['approvals']);self.assertFalse(self.engine.state['external_actions'])
        self.engine.store.verify()

    async def test_later_model_submission_reuses_same_id_and_provenance(self):
        q=await self.qualified(authentication='ACCOUNT_REQUIRED');recover(self.engine)
        old=self.engine.state['ideas'][0]['id']
        data=DemoBackend.idea('Detailed carrier explanation','Public exact-byte export custody','FREE','DISCOVERED')
        data.update(provider=q['plan']['provider'],qualification_id=q['id'])
        result=self.api.submit_idea(data)
        self.assertEqual(result['id'],old);self.assertEqual(len(self.engine.state['ideas']),1)
        self.assertGreaterEqual(len(result['submissions']),2)
        newer=self.api.check_deposit_target(self.plan())
        recover(self.engine)
        self.assertEqual(len(self.engine.state['ideas']),1)
        self.assertEqual(self.engine.state['ideas'][0]['qualification_id'],newer['id'])

    async def test_old_qualification_never_rolls_new_candidate_back(self):
        q=await self.qualified(authentication='ACCOUNT_REQUIRED');recover(self.engine)
        fresh=self.api.check_deposit_target(self.plan())
        recover(self.engine)
        self.assertEqual(len(self.engine.state['ideas']),1)
        self.assertEqual(self.engine.state['ideas'][0]['qualification_id'],fresh['id'])
        recover(self.engine)
        self.assertEqual(self.engine.state['ideas'][0]['qualification_id'],fresh['id'])

    async def test_resume_releases_only_satisfied_dependency_block_not_approval(self):
        q=await self.qualified(authentication='ACCOUNT_REQUIRED')
        auditor=self.engine.state['agents'][1];local=self.engine.state['agents'][2]
        auditor.update(status='BLOCKED',reason_for_stopping='NO_ADMITTED_DISCOVERY_CANDIDATE')
        local.update(status='BLOCKED',reason_for_stopping='HUMAN_APPROVAL_REQUIRED')
        recover(self.engine)
        self.assertEqual(auditor['status'],'PENDING');self.assertEqual(local['status'],'BLOCKED')
        local['reason_for_stopping']='NO_INDEPENDENTLY_APPROVED_DEPOSIT_PLAN'
        recover(self.engine);self.assertEqual(local['status'],'BLOCKED')

    async def test_local_dependency_reopens_after_exact_current_independent_pass(self):
        q=await self.qualified();recover(self.engine)
        idea=self.engine.state['ideas'][0];idea['payment']='FREE';auditor=self.engine.state['agents'][1]
        local=self.engine.state['agents'][2];local.update(status='BLOCKED',reason_for_stopping='NO_INDEPENDENTLY_APPROVED_DEPOSIT_PLAN')
        api=self.for_agent(auditor)
        for path in ('/docs','/terms'):await api.read_document(self.origin+path,'Independently review actual API and terms')
        api.record_critique(idea['id'],'PASS','The exact current qualified operation works')
        recover(self.engine);self.assertEqual(local['status'],'PENDING')
        self.assertFalse(self.engine.state['approvals'])

    async def test_report_reopens_once_when_new_draft_or_critique_arrives(self):
        reporter=self.engine.state['agents'][3];reporter.update(status='COMPLETED',rounds=1,report_revision=report_revision(self.engine.state))
        await self.qualified(authentication='ACCOUNT_REQUIRED');recover(self.engine)
        self.assertEqual(reporter['status'],'PENDING')
        reporter.update(status='COMPLETED',report_revision=report_revision(self.engine.state))
        recover(self.engine);self.assertEqual(reporter['status'],'COMPLETED')

    async def test_checkpoint_resume_retains_candidate_and_restores_dependency(self):
        await self.qualified(authentication='ACCOUNT_REQUIRED')
        self.engine.state['agents'][1].update(status='BLOCKED',reason_for_stopping='NO_ADMITTED_DISCOVERY_CANDIDATE')
        self.api.event('fixture_dependency_blocked',{})
        self.engine.close();self.engine=Engine(self.run,DemoBackend(),'demo')
        recover(self.engine)
        self.assertEqual(len(self.engine.state['ideas']),1)
        self.assertEqual(self.engine.state['agents'][1]['status'],'PENDING')
        self.engine.store.verify()

    async def test_multistep_count_cannot_be_understated_and_is_retained_not_rejected(self):
        self.engine.state['config']['require_explicit_upload_flow']=True
        q=await self.qualified(authentication='ACCOUNT_REQUIRED',operation_steps=multi(),required_external_actions=1)
        self.assertEqual(q['plan']['required_external_actions'],3)
        self.assertEqual(q['flow_assessment']['derived_external_actions'],3)
        self.assertIn('RESOURCE_LIMIT',q['reasons']);self.assertIn('EXECUTABLE_FLOW_REQUIRED',q['reasons'])
        self.assertTrue(q['admissible']);self.assertFalse(q['execution_ready'])
        recover(self.engine);self.assertEqual(self.engine.state['ideas'][0]['status'],'BLOCKED')
        self.assertFalse(self.engine.state['external_actions'])

    async def test_authenticated_read_also_counts_and_extra_limits_do_not_create_executor(self):
        self.engine.state['config'].update(require_explicit_upload_flow=True,max_external_actions=5)
        steps=multi()+[{'method':'GET','purpose':'Inspect authenticated object status','sends_export':False,'uses_credential':True}]
        q=await self.qualified(operation_steps=steps)
        self.assertEqual(q['flow_assessment']['derived_external_actions'],4)
        self.assertEqual(q['status'],'EXECUTABLE_FLOW_REQUIRED')
        self.assertFalse(q['execution_ready'])

    async def test_missing_or_invalid_flow_cannot_be_ready(self):
        self.engine.state['config']['require_explicit_upload_flow']=True
        q=await self.qualified();self.assertEqual(q['status'],'UPLOAD_FLOW_REQUIRED')
        self.assertTrue(q['admissible']);self.assertFalse(q['execution_ready'])
        bad=single();bad[0]['sends_export']=False
        with self.assertRaises(ValueError):self.api.check_deposit_target(self.plan(operation_steps=bad))
        q=self.api.check_deposit_target(self.plan(operation_steps=single()))
        self.assertEqual(q['status'],'READY_FOR_AUDIT')

    async def test_forbidden_or_incomplete_research_never_autoadmitted(self):
        await self.qualified(upload_url='https://gitlab.com/file',authentication='ACCOUNT_REQUIRED')
        self.api.check_deposit_target(self.plan(upload_url='',authentication='UNKNOWN'))
        recover(self.engine)
        self.assertEqual(self.engine.state['ideas'],[])

    async def test_new_qualification_reopens_completed_auditor(self):
        q=await self.qualified(authentication='ACCOUNT_REQUIRED');recover(self.engine)
        auditor=self.engine.state['agents'][1];auditor.update(status='COMPLETED',rounds=1)
        self.engine.state['ideas'][0]['critique']={'qualification_id':q['id'],'verdict':'REVISE'}
        recover(self.engine);self.assertEqual(auditor['status'],'COMPLETED')
        fresh=self.api.check_deposit_target(self.plan());recover(self.engine)
        self.assertEqual(auditor['status'],'PENDING')

    @unittest.skipUnless(__import__('tests.test_backend',fromlist=['SDK_AVAILABLE']).SDK_AVAILABLE,'SDK optional')
    async def test_actual_sdk_receives_typed_flow_and_reports_retention_permission(self):
        from metaweb_swarm.backend import OpenAIBackend
        from tests.test_backend import FakeProvider,tool_response,final_response
        self.engine.state['config']['require_explicit_upload_flow']=True
        self.config['require_explicit_upload_flow']=True
        await self.sources()
        provider=FakeProvider([tool_response('check_deposit_target',self.plan(authentication='ACCOUNT_REQUIRED',operation_steps=multi())),final_response()])
        result=await OpenAIBackend(provider).step(self.agent,self.engine.prompt(self.agent),[],self.api,self.config)
        output=json.loads(next(i['output'] for i in result['history'] if i.get('type')=='function_call_output'))
        self.assertTrue(output['admissible']);self.assertEqual(output['admission_kind'],'BLOCKED_LEAD')
        self.assertEqual(output['flow_assessment']['derived_external_actions'],3)
        recover(self.engine);self.assertEqual(len(self.engine.state['ideas']),1)

    async def test_real_resume_scheduler_runs_audit_then_refreshes_report_once(self):
        q=await self.qualified(authentication='ACCOUNT_REQUIRED')
        self.agent.update(status='LIMIT_REACHED',rounds=4)
        self.engine.state['agents'][1].update(status='BLOCKED',reason_for_stopping='NO_ADMITTED_DISCOVERY_CANDIDATE')
        self.engine.state['agents'][2].update(status='BLOCKED',reason_for_stopping='NO_INDEPENDENTLY_APPROVED_DEPOSIT_PLAN')
        self.engine.state['agents'][3].update(status='COMPLETED',rounds=1)
        calls=[]
        class ReviewThenReport:
            async def step(inner,agent,prompt,history,api,config):
                calls.append(agent['role'])
                if agent['role']=='Evidence Auditor':
                    api.record_critique(self.engine.state['ideas'][0]['id'],'REVISE','Dedicated service credential is missing; retain lead')
                elif agent['role']!='Synthesizer / Reporter':
                    raise AssertionError('No discovery retry or premature implementation')
                return {'output':{'status':'COMPLETED','reason_for_stopping':'Assignment done','summary':'Saved draft requires setup',
                    'unexplored_leads':[],'handoff_leads':[],'blind_spots':[]},'history':history,'usage':{},'raw':{'usage_complete':True}}
        self.engine.backend=ReviewThenReport()
        await self.engine.run()
        self.assertEqual(calls,['Evidence Auditor','Synthesizer / Reporter'])
        self.assertEqual(len(self.engine.state['ideas']),1)
        self.assertEqual(self.engine.state['agents'][2]['status'],'BLOCKED')
        calls.clear();await self.engine.run();self.assertEqual(calls,[])
        self.engine.store.verify()
