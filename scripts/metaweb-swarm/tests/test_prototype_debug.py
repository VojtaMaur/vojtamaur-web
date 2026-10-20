"""Failure handoff/recovery: fake executor or model, no paid inference."""
import json,unittest
from unittest.mock import patch
from tests import test_prototype_review as fixture
from tests.test_backend import SDK_AVAILABLE
from metaweb_swarm.backend import OpenAIBackend,BackendYield
from metaweb_swarm.review_tasks import assign
from metaweb_swarm.research_tasks import recover,local_candidates,prepare_task_context
from metaweb_swarm.prototype_debug import hold
from metaweb_swarm.review_dispatch import action,schedule

class PrototypeDebugTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.PrototypeScopeTests.setUp
    tearDown=fixture.PrototypeScopeTests.tearDown
    for_agent=fixture.PrototypeScopeTests.for_agent
    prepare=fixture.PrototypeScopeTests.prepare
    artifacts=fixture.PrototypeScopeTests.artifacts
    plan=fixture.PrototypeScopeTests.plan

    async def failed(self):
        self.artifacts()
        self.review.record_critique(self.idea['id'],'REVISE','The selected local operation still needs a real test')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.return_value={'status':'BLOCKED','returncode':1,'output':'Traceback: AssertionError: decoder does not repair damaged input'}
            e=await self.local.run_experiment(['python','prototype/test.py'],self.idea['id'])
        assign(self.engine,self.auditor)
        return e

    def diagnosis(self,e,disposition='REPAIR'):
        self.review.read_failed_experiment(e['experiment_id'])
        return self.review.record_failure_diagnosis(e['experiment_id'],'ALGORITHM_MISSING',
            'The decoder lacks the actual correction operation; parser edits cannot restore missing data',
            ['Implement the documented inverse of the encoded specimen','Keep decisive corruption assertions and original-byte comparison'],
            'Decode the damaged saved specimen and compare its complete recovered bytes to the original',disposition)

    async def test_failed_execution_has_immutable_source_and_no_test_award(self):
        e=await self.failed();f=e['failure_evidence']
        self.local.workspace.write_file('prototype/test.py','print("unrelated later edit")\n')
        read=self.review.read_failed_experiment(e['experiment_id'])
        self.assertIn('base64',read['text'])
        self.assertNotIn('unrelated later edit',read['text'])
        self.assertEqual(read['script_sha256'],f['script']['sha256'])
        self.assertEqual(self.engine.state['tests'],[])
        self.assertEqual(self.auditor['review_assignment']['kind'],'PROTOTYPE_FAILURE')

    async def test_peer_must_read_source_and_cannot_self_diagnose(self):
        e=await self.failed()
        result=self.review.record_failure_diagnosis(e['experiment_id'],'CODE_BUG','Actual inverse has not been implemented',
            ['Implement a real decoder before retrying'],'A damaged specimen must recover the original bytes','REPAIR')
        self.assertEqual(result['reason'],'OWN_FAILED_SCRIPT_READ_REQUIRED')
        own=self.local.record_failure_diagnosis(e['experiment_id'],'CODE_BUG','Self judgment is not independent',
            ['Change the parser and decoder implementation'],'Recover original bytes from the damaged specimen','REPAIR')
        self.assertEqual(own['reason'],'INDEPENDENT_FAILURE_REVIEW_REQUIRED')

    async def test_pending_peer_review_holds_local_role_without_paid_retry(self):
        e=await self.failed();self.proto['status']='PENDING'
        hold(self.engine)
        self.assertEqual(self.proto['reason_for_stopping'],'FAILED_CODE_REVIEW_PENDING')
        self.assertEqual(local_candidates(self.engine.state,self.proto),[])
        self.auditor.update(status='PENDING')
        self.assertEqual(schedule(self.engine.state,[self.auditor,self.reporter],8,1),[self.auditor])
        self.diagnosis(e);recover(self.engine)
        self.assertEqual(self.proto['status'],'PENDING')

    async def test_repair_requires_changed_code_and_linked_diagnostic_notes(self):
        e=await self.failed();self.diagnosis(e)
        unchanged=self.plan()
        self.assertEqual(unchanged['reason'],'FAILED_SCRIPT_UNCHANGED')
        self.local.workspace.write_file('prototype/test.py','assert True # fixture edit, no semantic proof\n')
        missing=self.plan()
        self.assertEqual(missing['reason'],'ROOT_CAUSE_REPAIR_REQUIRED')
        result=self.local.record_prototype_plan(self.idea['id'],'Repair actual inverse operation and verify corruption detection',
            'exports/input.epub','prototype/test.py',['prototype/specimen.bin','prototype/recovered.bin'],
            'Compare recovered bytes from the produced specimen','Altered specimen must be rejected or recovered','FULL_MECHANISM','',
            e['experiment_id'],'Changed the inverse to consume its generated specimen according to the diagnosis',
            'Compare complete recovered bytes to the original and exercise damaged input')
        self.assertEqual(result['repair']['experiment_id'],e['experiment_id'])

    async def test_dependency_receipt_can_repair_same_code_without_fake_edits(self):
        e=await self.failed();self.diagnosis(e)
        e['failure_review']['problem_kind']='DEPENDENCY'
        self.engine.state.setdefault('package_installations',[]).append(
            {'id':'NEW-ACTUAL-HOST-RECEIPT','agent_id':self.proto['id'],'status':'COMPLETED'})
        result=self.local.record_prototype_plan(self.idea['id'],'Retest after actual sandbox dependency installation',
            'exports/input.epub','prototype/test.py',['prototype/specimen.bin','prototype/recovered.bin'],
            'Decode original bytes and verify equality','Altered bytes must fail digest verification','FULL_MECHANISM','',
            e['experiment_id'],'Installed the missing package; code already implements the required decoder',
            'Re-run unchanged decoder with actual dependency and verify roundtrip and corruption rejection')
        self.assertEqual(result['repair']['experiment_id'],e['experiment_id'])

    async def test_deferred_repair_retains_hypothesis_and_allows_another_candidate(self):
        e=await self.failed();self.diagnosis(e,'DEFER')
        self.assertEqual(local_candidates(self.engine.state,self.proto),[])
        self.assertNotEqual(self.idea['status'],'REJECTED')
        self.assertEqual(self.engine.state['tests'],[])

    async def test_review_and_repair_contexts_are_current_and_history_is_archived(self):
        e=await self.failed();self.diagnosis(e)
        self.proto['history']=[{'role':'user','content':'Old parser guesses'}];self.proto['rounds']=2
        prepare_task_context(self.engine,self.proto,self.local.workspace)
        self.assertEqual(self.proto['history'],[])
        self.assertIn('LOCAL_REPAIR',self.proto['active_task_key'])
        self.assertEqual(action(self.local)['tool'],'read_failed_experiment')
        self.local.read_failed_experiment(e['experiment_id'])
        self.assertEqual(action(self.local)['tool'],'required')

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_yields_after_failed_execution_without_second_model_request(self):
        from tests.test_backend import FakeProvider,tool_response
        self.artifacts()
        provider=FakeProvider([tool_response('run_experiment',{'argv':['python','prototype/test.py'],'idea_id':self.idea['id']})])
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.return_value={'status':'BLOCKED','returncode':1,'output':'AssertionError: incomplete decoder'}
            with self.assertRaises(BackendYield) as caught:
                await OpenAIBackend(provider).step(self.proto,'Implement current prototype',[],self.local,self.engine.state['config'])
        self.assertEqual(len(provider.model.calls),1)
        self.assertTrue(caught.exception.raw['usage_complete'])
        self.assertIn('failure_evidence',json.dumps(caught.exception.history))

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_forces_failed_read_then_independent_diagnosis(self):
        from tests.test_backend import FakeProvider,tool_response,final_response
        e=await self.failed()
        provider=FakeProvider([tool_response('read_failed_experiment',{'experiment_id':e['experiment_id'],'offset':0,'limit':16000}),
            tool_response('record_failure_diagnosis',{'experiment_id':e['experiment_id'],'problem_kind':'ALGORITHM_MISSING',
                'diagnosis':'This decoder lacks the requested correction algorithm',
                'repair_steps':['Implement a real documented correction algorithm'],
                'success_check':'Recover complete original bytes from a corrupted saved specimen','disposition':'REPAIR'},ident='diagnose'),final_response()])
        self.engine.backend=OpenAIBackend(provider);await self.engine.step(self.auditor)
        choices=[kwargs.get('model_settings',args[2] if len(args)>2 else None).tool_choice for args,kwargs in provider.model.calls]
        self.assertEqual(choices,['read_failed_experiment','record_failure_diagnosis',None])
        self.assertEqual(e['failure_review']['disposition'],'REPAIR')
        self.assertEqual(self.auditor['status'],'COMPLETED')
