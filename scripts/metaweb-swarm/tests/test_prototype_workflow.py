"""Regression of the real run's ID mix-up, irrelevant code and lost repair execution."""
import asyncio
import copy
import json
import unittest
from unittest.mock import patch
from tests import test_prototype_review as fixture
from tests.test_backend import SDK_AVAILABLE
from metaweb_swarm.research_tasks import revision, local_candidates, recover
from metaweb_swarm.review_tasks import assign
from metaweb_swarm.review_dispatch import action, schedule
from metaweb_swarm.prototype_preflight import hold
from metaweb_swarm.prototype_workflow import begin, finish


class PrototypeWorkflowTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.PrototypeScopeTests.setUp
    tearDown = fixture.PrototypeScopeTests.tearDown
    for_agent = fixture.PrototypeScopeTests.for_agent
    prepare = fixture.PrototypeScopeTests.prepare
    artifacts = fixture.PrototypeScopeTests.artifacts
    plan = fixture.PrototypeScopeTests.plan

    def setup_workflow(self):
        self.artifacts()
        self.review.record_critique(self.idea['id'], 'REVISE', 'The representation still needs an actual local roundtrip test')
        self.engine.state['config']['require_prototype_focus'] = True
        self.idea['prototype_focus'] = {'scope': 'FULL_MECHANISM', 'goal':
            'Base64 encode the retained bytes, decode the generated specimen and reject corrupt payload',
            'research_revision': revision(self.idea), 'agent_id': self.auditor['id']}
        return self.submit()

    def submit(self, **repair):
        return self.local.record_current_prototype_plan(self.idea['id'],
            'Encode and decode the actual retained payload through the proposed representation',
            'exports/input.epub', 'prototype/test.py', ['prototype/specimen.bin', 'prototype/recovered.bin'],
            'Decode the generated specimen and compare original bytes',
            'Altered encoded payload must fail integrity verification', 'FULL_MECHANISM', '', **repair)

    def check_plan(self, plan, verdict='READY'):
        assign(self.engine, self.auditor)
        self.assertEqual(self.auditor['review_assignment']['kind'], 'PROTOTYPE_PLAN')
        result = self.review.read_prototype_plan(plan['id'])
        while result.get('next_offset') is not None:
            result = self.review.read_prototype_plan(plan['id'], result['next_offset'])
        return self.review.review_prototype_plan(plan['id'], verdict,
            'The script implements the representation operation' if verdict == 'READY' else
            'This generic container check does not exercise the public profile mechanism; implement its serialization and field extraction',
            'Encode payload into a specimen and decode that representation',
            'encoded=base64.b64encode(data)' if verdict == 'READY' else '')

    def mock_success(self, *args):
        self.local.workspace.write_file('prototype/specimen.bin', b'generated mock specimen')
        self.local.workspace.write_file('prototype/recovered.bin', (self.local.workspace.root/'exports/input.epub').read_bytes())
        return {'status': 'COMPLETED', 'returncode': 0, 'output': 'Mock executor for workflow only; no semantic proof'}

    async def test_plan_waits_without_docker_or_paid_local_retry_then_reopens(self):
        p = self.setup_workflow()
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            result = await self.local.execute_prototype(['python', 'prototype/test.py'])
            self.assertEqual(result['reason'], 'PROTOTYPE_PLAN_REVIEW_PENDING')
            docker.assert_not_called()
        self.proto['status'] = 'PENDING'
        hold(self.engine)
        self.assertEqual(self.proto['status'], 'BLOCKED')
        self.assertFalse(local_candidates(self.engine.state, self.proto))
        self.auditor.update(status='PENDING')
        self.assertEqual(schedule(self.engine.state, [self.auditor, self.reporter], 6, 1), [self.auditor])
        self.check_plan(p)
        recover(self.engine)
        self.assertEqual(self.proto['status'], 'PENDING')
        self.assertEqual(action(self.local)['tool'], 'execute_prototype')

    async def test_capture_receipt_is_automatic_idempotent_and_not_a_prototype_award(self):
        p = self.setup_workflow(); self.check_plan(p)
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect = self.mock_success
            result = await self.local.execute_prototype(['python', 'prototype/test.py'])
            repeated = await self.local.execute_prototype(['python', 'prototype/test.py'])
            self.assertEqual(docker.return_value.run.call_count, 1)
        self.assertEqual(result['test_receipt']['id'], repeated['test_receipt']['id'])
        self.assertEqual(len(self.engine.state['tests']), 1)
        self.assertFalse(self.idea['prototype_tested'])
        assign(self.engine, self.auditor)
        self.assertEqual(self.auditor['review_assignment']['kind'], 'PROTOTYPE_TEST')

    async def test_failed_repair_uses_host_id_never_a_test_id_and_preserves_notes(self):
        p = self.setup_workflow(); self.check_plan(p)
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.return_value = {'status': 'BLOCKED', 'returncode': 1,
                'output': 'AssertionError: damaged EPUB unexpectedly survived'}
            failed = await self.local.execute_prototype(['python', 'prototype/test.py'])
        assign(self.engine, self.auditor)
        self.review.read_failed_experiment(failed['experiment_id'])
        self.review.record_failure_diagnosis(failed['experiment_id'], 'CODE_BUG',
            'The negative control flips an arbitrary byte instead of testing rejection of an actual damaged specimen',
            ['Implement deterministic corruption of the produced specimen without weakening positive checks'],
            'A damaged produced specimen must fail the expected digest check', 'REPAIR')
        self.local.read_failed_experiment(failed['experiment_id'])
        self.local.workspace.write_file('prototype/test.py',
            self.local.workspace.read_file('prototype/test.py') + '\n# repaired deterministic control fixture\n')
        self.assertEqual(action(self.local)['tool'], 'record_prototype_plan')
        notes = 'Implement deterministic corruption of the produced specimen, preserving positive assertions'
        repaired = self.submit(repair_notes=notes,
            repair_check='The damaged specimen must now fail digest validation while intact bytes recover exactly')
        self.assertEqual(repaired['repair']['experiment_id'], failed['experiment_id'])
        self.assertEqual(repaired['repair']['notes'], notes)
        self.assertNotIn('revision_repair', repaired)
        self.check_plan(repaired)
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect = self.mock_success
            result = await self.local.execute_prototype(['python', 'prototype/test.py'])
        self.assertIn('test_receipt', result)
        self.assertEqual(len(self.engine.state['experiments']), 2)

    async def test_successful_but_revised_test_binds_its_real_test_id(self):
        p = self.setup_workflow(); self.check_plan(p)
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect = self.mock_success
            result = await self.local.execute_prototype(['python', 'prototype/test.py'])
        test = self.engine.state['tests'][0]
        assign(self.engine, self.auditor)
        for artifact in test['artifacts']:
            self.review.read_test_artifact(test['id'], artifact['path'])
        self.review.review_prototype_test(test['id'], 'REVISE',
            'The decoder must read the saved produced specimen rather than directly using the encoder variable')
        self.local.read_revised_test(test['id'])
        self.local.workspace.write_file('prototype/test.py',
            self.local.workspace.read_file('prototype/test.py').replace('base64.b64decode(encoded)',
            "base64.b64decode(Path('prototype/specimen.bin').read_bytes())"))
        fixed = self.submit(repair_notes='Read back the generated specimen before actual decoding instead of using the in-memory encoder value',
            repair_check='Assert decoded saved specimen bytes equal the original and reject the altered specimen')
        self.assertEqual(fixed['revision_repair']['test_id'], result['test_receipt']['id'])
        self.assertNotIn('repair', fixed)

    async def test_irrelevant_plan_cannot_execute_and_relabeling_does_not_fix_code(self):
        p = self.setup_workflow()
        self.check_plan(p, 'REVISE')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            result = await self.local.execute_prototype(['python', 'prototype/test.py'])
            self.assertEqual(result['reason'], 'PROTOTYPE_PLAN_REVISE')
            docker.assert_not_called()
        self.assertEqual(self.submit()['reason'], 'PLANNED_OPERATION_NEEDS_CODE_CHANGE')
        self.assertNotEqual(self.idea['status'], 'REJECTED')
        self.assertFalse(self.engine.state['tests'])

    async def test_changed_code_invalidates_preflight_and_immutable_read_keeps_original(self):
        p = self.setup_workflow(); self.check_plan(p)
        original = self.local.workspace.read_file('prototype/test.py')
        self.local.workspace.write_file('prototype/test.py', 'print("different unreviewed code")\n')
        reread = self.review.read_prototype_plan(p['id'])
        self.assertEqual(reread['text'], original)
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            result = await self.local.execute_prototype(['python', 'prototype/test.py'])
            self.assertEqual(result['reason'], 'PROTOTYPE_SCRIPT_CHANGED')
            docker.assert_not_called()

    def test_no_self_review_or_unread_code_approval_and_no_new_permission(self):
        p = self.setup_workflow(); assign(self.engine, self.auditor)
        with self.assertRaises(ValueError):
            self.local.review_prototype_plan(p['id'], 'READY', 'A self-approved prototype would be invalid',
                'Exercise the concrete carrier operation', 'encoded=base64.b64encode(data)')
        result = self.review.review_prototype_plan(p['id'], 'READY', 'A source read must precede the actual judgment',
            'Exercise the concrete carrier operation', 'encoded=base64.b64encode(data)')
        self.assertEqual(result['reason'], 'OWN_PLANNED_SCRIPT_READ_REQUIRED')
        self.check_plan(p)
        self.assertFalse(self.engine.state['external_actions'])
        self.assertFalse(self.idea['prototype_tested'])

    def test_two_rounds_without_code_or_execution_stop_technical_loop(self):
        p = self.setup_workflow(); self.check_plan(p, 'REVISE')
        for number in (2, 3):
            self.proto['rounds'] = number
            begin(self.local); finish(self.local)
        self.assertEqual(self.proto['research_task_blocks'][-1]['reason'], 'PROTOTYPE_WORKFLOW_STALLED')
        self.assertFalse(local_candidates(self.engine.state, self.proto))
        self.assertNotEqual(self.idea['status'], 'REJECTED')

    async def test_interrupted_receipt_registration_reuses_execution_without_rerun(self):
        p=self.setup_workflow();self.check_plan(p)
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=self.mock_success
            with patch.object(self.local,'record_test',side_effect=OSError('simulated receipt interruption')):
                with self.assertRaises(OSError):await self.local.execute_prototype(['python','prototype/test.py'])
            result=await self.local.execute_prototype(['python','prototype/test.py'])
            self.assertEqual(docker.return_value.run.call_count,1)
        self.assertIn('test_receipt',result)
        self.assertEqual(len(self.engine.state['tests']),1)

    async def test_incomplete_receipt_is_not_reported_as_completed_work(self):
        p=self.setup_workflow();self.check_plan(p)
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=self.mock_success
            with patch.object(self.local,'record_test',return_value={'status':'DEFERRED','reason':'EXECUTED_ARTIFACT_CHANGED'}):
                result=await self.local.execute_prototype(['python','prototype/test.py'])
        self.assertEqual(result['status'],'DEFERRED')
        self.assertEqual(result['reason'],'TEST_RECEIPT_INCOMPLETE')
        self.assertFalse(self.engine.state['tests'])

    async def test_unresolved_execution_is_not_retried_and_plan_snapshot_survives_resume(self):
        from metaweb_swarm.research_tasks import prepare_task_context
        p=self.setup_workflow();self.check_plan(p)
        self.proto['prototype_execution']={'status':'RUNNING','plan_id':p['id'],'argv':['python','prototype/test.py']}
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            result=await self.local.execute_prototype(['python','prototype/test.py'])
            self.assertEqual(result['reason'],'LOCAL_EXECUTION_OUTCOME_UNRESOLVED')
            docker.assert_not_called()
        self.proto['history']=[{'role':'user','content':'Old repair schema with misleading TEST/EXPERIMENT IDs'}]
        self.proto['active_task_key']='legacy workflow';self.proto['rounds']=2
        saved=copy.deepcopy(self.engine.state['prototype_plan_submissions'])
        prepare_task_context(self.engine,self.proto,self.local.workspace)
        self.assertEqual(self.proto['history'],[])
        self.assertEqual(self.engine.state['prototype_plan_submissions'],saved)
        self.assertIn('0.6.18',self.proto['active_task_key'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_forces_actual_code_read_then_plan_judgment(self):
        from metaweb_swarm.backend import OpenAIBackend
        from tests.test_backend import FakeProvider,tool_response,final_response
        p=self.setup_workflow();assign(self.engine,self.auditor)
        provider=FakeProvider([
            tool_response('read_prototype_plan',{'plan_id':p['id'],'offset':0,'limit':16000}),
            tool_response('review_prototype_plan',{'plan_id':p['id'],'verdict':'REVISE',
                'reason':'A generic archive check would not test federation; implement profile field serialization and extraction',
                'mechanism_operation':'Serialize and retrieve a profile recovery field rather than test ZIP integrity',
                'evidence_code':''},ident='plan-review'),final_response()])
        await OpenAIBackend(provider).step(self.auditor,'Review this exact plan',[],self.review,self.engine.state['config'])
        choices=[kw.get('model_settings',args[2] if len(args)>2 else None).tool_choice for args,kw in provider.model.calls]
        self.assertEqual(choices,['read_prototype_plan','review_prototype_plan',None])
        self.assertEqual(self.engine.state['prototype_plan_submissions'][-1]['preflight_review']['verdict'],'REVISE')
        self.assertFalse(self.engine.state['experiments'])

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK optional')
    async def test_sdk_schema_has_no_repair_ids_and_plan_queue_yields_after_one_request(self):
        import agents
        from metaweb_swarm.backend import _make_sdk_tools, OpenAIBackend, BackendYield
        from tests.test_backend import FakeProvider, tool_response
        self.setup_workflow()
        # The initial fixture plan is reviewed so the next changed plan can be submitted normally.
        self.check_plan(self.proto['prototype_plans'][self.idea['id']])
        self.local.workspace.write_file('prototype/test.py', self.local.workspace.read_file('prototype/test.py')+'\n# changed\n')
        tools = {t.name:t for t in _make_sdk_tools(agents, self.local)[0]}
        self.assertIn('execute_prototype', tools)
        self.assertNotIn('run_experiment', tools)
        self.assertNotIn('record_test', tools)
        schema = tools['record_prototype_plan'].params_json_schema['properties']
        self.assertFalse({'revision_test_id', 'repair_experiment_id'} & set(schema))
        self.assertTrue({'repair_notes', 'repair_check'} <= set(schema))
        provider = FakeProvider([tool_response('record_prototype_plan', {
            'idea_id':self.idea['id'], 'property_tested':'Recover original bytes from the representation',
            'input_path':'exports/input.epub', 'script_path':'prototype/test.py',
            'output_paths':['prototype/specimen.bin', 'prototype/recovered.bin'],
            'positive_assertion':'Decode the specimen to original bytes',
            'negative_assertion':'Corrupted specimen must fail validation', 'scope':'FULL_MECHANISM',
            'limitations':'', 'repair_notes':'', 'repair_check':''})])
        with self.assertRaises(BackendYield):
            await OpenAIBackend(provider).step(self.proto, 'Update the current test plan', [], self.local, self.engine.state['config'])
        self.assertEqual(len(provider.model.calls), 1)
