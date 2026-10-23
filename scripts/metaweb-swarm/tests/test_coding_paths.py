"""SDK virtual paths remain inside the private workspace; bad data is repairable."""
import copy,json,unittest
from unittest.mock import patch
from metaweb_swarm.coding_worker import normalize_submission,task
from metaweb_swarm.backend import OpenAIBackend
from tests import test_coding_worker as fixture
from tests.test_backend import SDK_AVAILABLE,FakeProvider,response,tool_response


class CodingPathTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.CodingWorkerTests.setUp
    tearDown=fixture.CodingWorkerTests.tearDown
    for_agent=fixture.CodingWorkerTests.for_agent
    prepare=fixture.CodingWorkerTests.prepare
    setup_worker=fixture.CodingWorkerTests.setup_worker
    mock_command=fixture.CodingWorkerTests.mock_command

    def absolute_result(self):
        value=copy.deepcopy(self.result)
        value['script_path']='/workspace/'+value['script_path']
        value['output_paths']=['/workspace/'+p for p in value['output_paths']]
        value['source_paths']=['/workspace/'+task(self.local)['input']['path']]
        value['argv']=[]
        return value

    def test_virtual_absolute_names_map_to_confined_relative_names(self):
        self.setup_worker();current=task(self.local)
        value=normalize_submission(self.absolute_result(),current)
        self.assertEqual(value['script_path'],'prototype/test.py')
        self.assertEqual(value['argv'],['python','prototype/test.py'])
        self.assertEqual(value['output_paths'],self.result['output_paths'])
        self.assertEqual(value['source_paths'],[])

    def test_argument_paths_are_normalized_without_interpreting_shell_text(self):
        self.setup_worker();value=self.absolute_result()
        value['argv']=['python3','/workspace/prototype/test.py','literal;not-a-command']
        result=normalize_submission(value,task(self.local))
        self.assertEqual(result['argv'],['python3','prototype/test.py','literal;not-a-command'])

    def test_host_absolute_paths_and_traversal_are_still_forbidden(self):
        self.setup_worker()
        for path in ['/tmp/test.py','/workspace/../test.py','G:\\vojtamaur-web\\test.py','//server/share/test.py','/workspace/prototype/../../test.py']:
            with self.subTest(path=path):
                value=self.absolute_result();value['script_path']=path
                with self.assertRaises(ValueError):normalize_submission(value,task(self.local))

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_ready_absolute_paths_capture_without_new_model_round(self):
        self.setup_worker();self.mock_command(self.local.workspace.root,['sh','INITIAL'])
        value=self.absolute_result()
        provider=FakeProvider([response([{'type':'message','id':'ready','role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':json.dumps(value),'annotations':[]}]}])])
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=self.mock_command
            result=await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
            self.assertEqual(docker.return_value.run.call_args.args[1],['python','prototype/test.py'])
        self.assertEqual(result['output']['status'],'COMPLETED')
        self.assertEqual(len(self.engine.state['tests']),1)
        self.assertEqual(len(provider.model.calls),1)

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_bad_submission_gets_feedback_and_repairs_in_same_quantum(self):
        self.setup_worker();value=self.absolute_result();value['script_path']='/tmp/forbidden.py'
        def ready(data,ident):return response([{'type':'message','id':ident,'role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':json.dumps(data),'annotations':[]}]}])
        provider=FakeProvider([ready(value,'bad-ready'),
            tool_response('exec_command',{'cmd':'REPAIR_AND_RUN','yield_time_ms':10000},ident='repair-paths'),
            ready(self.absolute_result(),'fixed-ready')])
        with patch('metaweb_swarm.workspace.DockerExecutor') as development,patch('metaweb_swarm.engine.DockerExecutor') as final:
            development.return_value.run.side_effect=self.mock_command
            final.return_value.run.side_effect=self.mock_command
            result=await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
            self.assertEqual(final.return_value.run.call_count,1)
        self.assertEqual(result['output']['status'],'COMPLETED')
        self.assertIn('SUBMISSION_DATA_INVALID',str(provider.model.calls[1]))
        self.assertEqual(len(self.engine.state['tests']),1)
