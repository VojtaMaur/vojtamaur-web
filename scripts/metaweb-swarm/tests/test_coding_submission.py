"""Direct saved shell drivers, actionable feedback and bounded invalid submissions."""
import copy,json,unittest
from unittest.mock import patch
from metaweb_swarm.backend import OpenAIBackend,BackendBlocked,BackendLimit
from metaweb_swarm.coding_worker import task,normalize_submission,finalize,last_result
from metaweb_swarm.prototype_queue import synchronize
from tests import test_coding_worker as fixture
from tests.test_backend import SDK_AVAILABLE,FakeProvider,response,tool_response


class CodingSubmissionTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.CodingWorkerTests.setUp
    tearDown=fixture.CodingWorkerTests.tearDown
    for_agent=fixture.CodingWorkerTests.for_agent
    prepare=fixture.CodingWorkerTests.prepare
    setup_worker=fixture.CodingWorkerTests.setup_worker
    mock_command=fixture.CodingWorkerTests.mock_command

    def shell_result(self):
        self.setup_worker();self.mock_command(self.local.workspace.root,['sh','INITIAL'])
        self.local.workspace.write_file('prototype/test.sh','#!/bin/sh\nset -eu\npython prototype/test.py\n')
        value=copy.deepcopy(self.result);value.update(script_path='prototype/test.sh',argv=[])
        return value

    def ready(self,value,ident='ready'):
        return response([{'type':'message','id':ident,'role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':json.dumps(value),'annotations':[]}]}])

    async def test_saved_shell_driver_is_captured_without_shell_inline_substitution(self):
        value=self.shell_result();self.assertEqual(normalize_submission(value,task(self.local))['argv'],['sh','prototype/test.sh'])
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=lambda root,argv:self.mock_command(root,['python','prototype/test.py'])
            result=await finalize(self.local,value,task(self.local))
            self.assertEqual(docker.return_value.run.call_args.args[1],['sh','prototype/test.sh'])
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(len(self.engine.state['tests']),1)
        receipt=self.engine.state['tests'][0]
        self.assertTrue(any(a['path']=='prototype/test.py' for a in receipt['artifacts']))
        self.assertTrue(receipt['prototype_review_required'])

    async def test_shell_inline_error_keeps_specific_correction_and_exact_argv(self):
        value=self.shell_result();value['argv']=['sh','-c','true','prototype/test.sh']
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            result=await finalize(self.local,value,task(self.local));docker.assert_not_called()
        self.assertEqual(result['status'],'CONTINUE')
        diagnostic=last_result(self.proto)
        self.assertEqual(diagnostic['reason'],'DIRECT_TEST_EXECUTION_REQUIRED')
        self.assertEqual(diagnostic['expected_argv'],['sh','prototype/test.sh'])
        self.assertIn('directly',diagnostic['next_action'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_repairs_invocation_only_in_same_quantum(self):
        value=self.shell_result();bad=copy.deepcopy(value);bad['argv']=['sh','-c','true','prototype/test.sh']
        provider=FakeProvider([self.ready(bad,'bad'),self.ready(value,'fixed')])
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=lambda root,argv:self.mock_command(root,['python','prototype/test.py'])
            result=await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
            self.assertEqual(docker.return_value.run.call_count,1)
        self.assertEqual(result['output']['status'],'COMPLETED')
        self.assertIn('expected_argv',str(provider.model.calls[1]));self.assertIn('prototype/test.sh',str(provider.model.calls[1]))

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_third_identical_host_rejection_stops_worker_not_24_more_requests(self):
        value=self.shell_result();value['argv']=['sh','-c','true','prototype/test.sh']
        provider=FakeProvider([self.ready(value,'bad-'+str(n)) for n in range(4)])
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            with self.assertRaisesRegex(BackendBlocked,'CODING_SUBMISSION_STALLED'):
                await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
            docker.assert_not_called()
        self.assertEqual(len(provider.model.calls),3)
        self.assertEqual(self.engine.state['tests'],[])

    async def test_repeated_contract_errors_persist_between_rounds_and_ignore_cosmetic_edits(self):
        value=self.shell_result();value['argv']=['sh','-c','true','prototype/test.sh'];current=task(self.local)
        await finalize(self.local,value,current)
        self.proto['rounds']+=1
        self.local.workspace.write_file('prototype/test.sh','#!/bin/sh\n# cosmetic rewrite\npython prototype/test.py\n')
        await finalize(self.local,value,current)
        with self.assertRaisesRegex(BackendBlocked,'CODING_SUBMISSION_STALLED'):await finalize(self.local,value,current)
        # Explicit human resolution changes operator_notes and grants a fresh diagnostic attempt.
        self.proto.setdefault('operator_notes',[]).append('Correct invocation now; no budget change')
        self.assertEqual((await finalize(self.local,value,current))['status'],'CONTINUE')

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_exhausted_command_budget_makes_zero_provider_calls(self):
        self.setup_worker();self.engine.state['config']['max_coding_commands_per_agent']=0
        provider=FakeProvider([])
        with self.assertRaisesRegex(BackendLimit,'MAX_CODING_COMMANDS'):
            await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
        self.assertEqual(provider.model.calls,[])
        self.proto['status']='PENDING';before=self.proto['rounds'];synchronize(self.engine)
        self.assertEqual(self.proto['status'],'LIMIT_REACHED');self.assertEqual(self.proto['rounds'],before)

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_last_allowed_command_stops_followup_model_requests(self):
        self.setup_worker();self.engine.state['config']['max_coding_commands_per_agent']=1
        provider=FakeProvider([tool_response('exec_command',{'cmd':'WRITE_AND_RUN','yield_time_ms':10000}),self.ready(self.result)])
        with patch('metaweb_swarm.workspace.DockerExecutor') as docker:
            docker.return_value.run.side_effect=self.mock_command
            with self.assertRaisesRegex(BackendLimit,'MAX_CODING_COMMANDS'):
                await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
            self.assertEqual(docker.return_value.run.call_count,1)
        self.assertEqual(len(provider.model.calls),1)

    async def test_python_cannot_be_used_to_execute_shell_driver(self):
        value=self.shell_result();value['argv']=['python3','prototype/test.sh']
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            await finalize(self.local,value,task(self.local));docker.assert_not_called()
        self.assertEqual(last_result(self.proto)['reason'],'SCRIPT_RUNTIME_MISMATCH')
        self.assertEqual(last_result(self.proto)['expected_argv'],['sh','prototype/test.sh'])
