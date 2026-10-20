"""Task switching and test scope regressions: fake provider/executor, no paid calls."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.research_tasks import prepare_task_context, local_candidates, recover
from metaweb_swarm.review_tasks import assign, pending
from metaweb_swarm.review_contract import complete_review
from metaweb_swarm.demo import DemoBackend
from tests import test_research_handoffs as fixture
from tests.test_backend import SDK_AVAILABLE, FINAL


class PrototypeScopeTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.ResearchHandoffTests.setUp
    tearDown=fixture.ResearchHandoffTests.tearDown
    for_agent=fixture.ResearchHandoffTests.for_agent
    prepare=fixture.ResearchHandoffTests.prepare

    def plan(self,scope='FULL_MECHANISM',script='prototype/test.py',input_path='exports/input.epub'):
        return self.local.record_prototype_plan(self.idea['id'],'Recover exact retained export bytes and detect corruption',
            input_path,script,['prototype/specimen.bin','prototype/recovered.bin'],'Decode and assert equality of bytes and real SHA256',
            'Modified payload must fail digest verification',scope,
            'Only local representation; remote upload and retention are untested' if scope=='SUBCOMPONENT' else '')

    def artifacts(self,scope='FULL_MECHANISM'):
        self.prepare()
        self.local.materialize_export('build.epub','exports/input.epub')
        self.local.workspace.write_file('prototype/test.py',
            "from pathlib import Path\nimport base64,hashlib\ndata=Path('exports/input.epub').read_bytes()\n"
            "encoded=base64.b64encode(data)\nPath('prototype/specimen.bin').write_bytes(encoded)\n"
            "decoded=base64.b64decode(encoded)\nassert data==decoded\n"
            "Path('prototype/recovered.bin').write_bytes(decoded)\n"
            "assert hashlib.sha256(decoded).digest()==hashlib.sha256(data).digest()\n"
            "assert hashlib.sha256(decoded+b'!').digest()!=hashlib.sha256(data).digest()\n")
        self.local.workspace.write_file('prototype/specimen.bin',b'fixed mock transport specimen')
        self.local.register_idea_artifacts(self.idea['id'],['prototype/test.py','prototype/specimen.bin'])
        return self.plan(scope)

    async def executed(self,scope='FULL_MECHANISM'):
        self.artifacts(scope)
        self.review.record_critique(self.idea['id'],'REVISE','Initial sources require independent validation of the planned local test')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            def mock_run(*args):
                self.local.workspace.write_file('prototype/specimen.bin',b'generated mock transport specimen')
                self.local.workspace.write_file('prototype/recovered.bin',(self.local.workspace.root/'exports/input.epub').read_bytes())
                return {'status':'COMPLETED','returncode':0,'output':'mock executor, assertions not actually run in this unit test'}
            docker.return_value.run.side_effect=mock_run
            e=await self.local.run_experiment(['python','prototype/test.py'],self.idea['id'])
        t=self.local.record_test(self.idea['id'],e['experiment_id'],'Simulated execution-bound test for independent scope review')
        assign(self.engine,self.auditor)
        return t

    def evidence(self, test, recovered=True):
        for artifact in test['artifacts']:
            result=self.review.read_test_artifact(test['id'],artifact['path'])
            while result.get('next_offset') is not None:
                result=self.review.read_test_artifact(test['id'],artifact['path'],result['next_offset'])
        return {'positive_code':'assert data==decoded',
                'negative_code':"assert hashlib.sha256(decoded+b'!').digest()!=hashlib.sha256(data).digest()",
                'recovered_path':'prototype/recovered.bin' if recovered else ''}

    def test_new_assignment_clears_old_model_context_but_keeps_audit_and_side_effects(self):
        self.prepare(two=True)
        self.auditor['rounds']=1
        prepare_task_context(self.engine,self.auditor,self.review.workspace)
        old=[{'type':'function_call','name':'get_review_task','call_id':'old','arguments':'{}'},
             {'type':'function_call_output','call_id':'old','output':'OLD_ASSIGNED_IDEA_0001'},
             {'role':'user','content':'Historical task must not overrule next assignment'}]
        self.auditor['history']=copy.deepcopy(old)
        self.engine.state.setdefault('http_requests',[]).append({'id':'UNKNOWN-EXTERNAL','status':'UNKNOWN','agent_id':self.auditor['id']})
        self.review.record_critique(self.idea['id'],'REVISE','Missing primary evidence; local test still needed')
        assign(self.engine,self.auditor)
        self.assertEqual(self.auditor['review_assignment']['target_id'],self.other['id'])
        self.auditor['rounds']=2
        prepare_task_context(self.engine,self.auditor,self.review.workspace)
        self.assertEqual(self.auditor['history'],[])
        archive=self.run/'raw'/f"{self.auditor['id']}-task-history-before-round-2.json"
        self.assertEqual(json.loads(archive.read_text()),old)
        self.assertEqual(self.engine.state['http_requests'][-1]['status'],'UNKNOWN')
        self.assertIn(self.other['id'],self.engine.prompt(self.auditor))

    async def test_execution_alone_never_awards_prototyped_and_independent_read_is_required(self):
        t=await self.executed()
        replay=self.local.record_test(self.idea['id'],t['experiment_id'],'Repeat the same execution receipt without inflating tests')
        self.assertTrue(replay['replayed'])
        self.assertEqual(len(self.engine.state['tests']),1)
        self.assertFalse(self.idea['prototype_tested'])
        self.assertNotEqual(self.idea['status'],'PROTOTYPED')
        self.assertEqual(self.review.get_review_task()['kind'],'PROTOTYPE_TEST')
        self.assertEqual(self.review.get_research_task()['candidate']['id'],self.idea['id'])
        if SDK_AVAILABLE:
            import agents
            from metaweb_swarm.backend import _make_sdk_tools
            names={t.name for t in _make_sdk_tools(agents,self.review)[0]}
            self.assertNotIn('record_critique',names)
            self.assertNotIn('read_document',names)
            self.assertIn('review_prototype_test',names)
        wrong=self.local.review_prototype_test(t['id'],'FULL_MECHANISM','Self certification must be refused regardless of claimed assertions')
        self.assertEqual(wrong['reason'],'ASSIGNED_PROTOTYPE_REVIEW_REQUIRED')
        result=self.review.review_prototype_test(t['id'],'FULL_MECHANISM','All assertions claimed to cover the current mechanism')
        self.assertEqual(result['reason'],'OWN_EXECUTED_SCRIPT_READ_REQUIRED')
        self.review.read_test_artifact(t['id'],'prototype/test.py')
        result=self.review.review_prototype_test(t['id'],'FULL_MECHANISM','Independent fixture judgment: actual script tests the planned round-trip and a corruption case',**self.evidence(t))
        self.assertEqual(result['verdict'],'FULL_MECHANISM')
        self.assertEqual(self.idea['status'],'PROTOTYPED')
        self.assertFalse(self.engine.state['external_actions'])

    async def test_qr_subcomponent_cannot_award_entire_storage_mechanism(self):
        t=await self.executed('SUBCOMPONENT')
        self.review.read_test_artifact(t['id'],'prototype/test.py')
        result=self.review.review_prototype_test(t['id'],'FULL_MECHANISM','A limited metadata check is falsely claimed to prove remote storage')
        self.assertEqual(result['reason'],'SUBCOMPONENT_CANNOT_CERTIFY_MECHANISM')
        self.review.review_prototype_test(t['id'],'SUBCOMPONENT','Only local representation is tested; remote custody and retrieval remain untested',**self.evidence(t))
        self.assertTrue(self.idea['prototype_component_tested'])
        self.assertFalse(self.idea['prototype_tested'])
        self.assertNotEqual(self.idea['status'],'PROTOTYPED')

    async def test_bad_test_is_revised_without_rejecting_candidate_and_reopens_local_work(self):
        t=await self.executed()
        self.proto.update(status='COMPLETED',rounds=1)
        self.review.review_prototype_test(t['id'],'REVISE','The script checks another representation and does not implement the promised mechanism')
        recover(self.engine)
        self.assertEqual(self.proto['status'],'PENDING')
        self.assertIn(self.idea,local_candidates(self.engine.state,self.proto))
        self.assertNotEqual(self.idea['status'],'REJECTED')

    async def test_modified_executed_script_cannot_receive_full_scope_approval(self):
        t=await self.executed()
        self.review.read_test_artifact(t['id'],'prototype/test.py')
        self.local.workspace.write_file('prototype/test.py',"print('changed after execution')\n")
        # Mutable workspace changes do not destroy the captured executed evidence.
        frozen=next(a for a in t['audit_artifacts'] if a['source_path']=='prototype/test.py')
        (self.run/frozen['path']).write_text("print('corrupted immutable audit')\n",encoding='utf-8')
        r=self.review.review_prototype_test(t['id'],'FULL_MECHANISM','Old read receipt must not approve a changed current artifact')
        self.assertEqual(r['reason'],'OWN_EXECUTED_SCRIPT_READ_REQUIRED')
        self.assertFalse(self.idea['prototype_tested'])

    async def test_executed_snapshot_survives_workspace_reuse_and_legacy_status_is_not_trusted(self):
        t=await self.executed()
        self.local.workspace.write_file('prototype/test.py',"print('next unrelated task')\n")
        read=self.review.read_test_artifact(t['id'],'prototype/test.py')
        self.assertIn('base64.b64decode',read['text'])
        self.review.review_prototype_test(t['id'],'FULL_MECHANISM','The immutable execution script matches the scoped local recovery goal',**self.evidence(t))
        from metaweb_swarm.prototype_review import enforce_scope
        self.assertEqual(enforce_scope(self.engine.state),[])
        self.engine.state['tests'][0].pop('prototype_review')
        self.assertTrue(enforce_scope(self.engine.state))
        self.assertNotEqual(self.idea['status'],'PROTOTYPED')
        self.assertEqual(len(self.engine.state['tests']),1)

    async def test_pause_resume_review_updates_authoritative_and_embedded_receipts(self):
        await self.executed()
        self.engine.close()
        from metaweb_swarm.engine import Engine
        self.engine=Engine(self.run,DemoBackend(),'demo')
        self.idea=self.engine.state['ideas'][0]
        self.auditor=self.engine.state['agents'][1]
        self.review=self.for_agent(self.auditor)
        assign(self.engine,self.auditor)
        test=self.engine.state['tests'][0]
        self.assertIsNot(test,self.idea['test_receipts'][0])
        self.review.read_test_artifact(test['id'],'prototype/test.py')
        self.review.review_prototype_test(test['id'],'FULL_MECHANISM','Executed snapshot covers the declared local byte recovery and corruption checks',**self.evidence(test))
        self.engine.close()
        self.engine=Engine(self.run,DemoBackend(),'demo')
        idea=self.engine.state['ideas'][0]
        self.assertTrue(idea['prototype_tested'])
        self.assertEqual(idea['status'],'PROTOTYPED')
        self.assertEqual(idea['test_receipts'][0]['prototype_review']['verdict'],'FULL_MECHANISM')

    def test_invented_fixture_not_accepted_as_retained_export_input(self):
        self.artifacts()
        self.local.workspace.write_file('fixture.txt','Invented payload instead of real preserved website')
        r=self.plan(input_path='fixture.txt')
        self.assertEqual(r['reason'],'RETAINED_EXPORT_INPUT_REQUIRED')

    async def test_runtime_mismatch_refused_before_docker_and_probe_is_fixed_networkless_execution(self):
        self.artifacts()
        self.local.workspace.write_file('prototype/test.mjs',"console.log('JS');\n")
        self.plan(script='prototype/test.mjs')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.return_value={'status':'COMPLETED','returncode':0,
                'output':json.dumps({'runtimes':{'python':'/usr/local/bin/python','python3':'/usr/local/bin/python3','node':None,'npm':None},'python_version':'3.11'})}
            cap=await self.local.get_sandbox_capabilities()
            self.assertIsNone(cap['runtimes']['node'])
            self.assertEqual(docker.return_value.run.call_args.args[1][:3],['python','-I','-c'])
            await self.local.get_sandbox_capabilities()
            self.assertEqual(docker.return_value.run.call_count,1)
            for command,reason in [('node','RUNTIME_UNAVAILABLE'),('python','SCRIPT_RUNTIME_MISMATCH')]:
                r=await self.local.run_experiment([command,'prototype/test.mjs'],self.idea['id'])
                self.assertEqual(r['reason'],reason)
            self.assertEqual(docker.return_value.run.call_count,1)
        self.assertFalse(self.engine.state['experiments'])

    async def test_script_as_unused_argument_and_disabled_assertions_are_not_execution(self):
        self.artifacts()
        commands=[['python','-c',"print('placeholder')",'prototype/test.py'],
                  ['python','-O','prototype/test.py'],
                  ['sh','-c','python prototype/test.py','prototype/test.py']]
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            for argv in commands:
                result=await self.local.run_experiment(argv,self.idea['id'])
                self.assertEqual(result['reason'],'DIRECT_TEST_EXECUTION_REQUIRED')
            self.local.agent['work_kind']='DISCOVERY'
            result=await self.local.run_experiment(commands[0],self.idea['id'])
            self.assertEqual(result['reason'],'DIRECT_TEST_EXECUTION_REQUIRED')
            docker.assert_not_called()
        self.assertFalse(self.engine.state['experiments'])

    def test_named_archive_layer_cannot_be_submitted_as_a_new_discovery(self):
        self.prepare()
        from metaweb_swarm.baseline import BaselineCorpus
        (self.run/'context/local-ARCHIVE.txt').write_text('ALTERNATIVE DEPLOYMENTS:\n\tArDrive / Arweave\n\thttps://arweave.net/existing-copy\n',encoding='utf-8')
        self.engine.baseline=BaselineCorpus(self.run)
        data=DemoBackend.idea('Arweave permanent publication','remote-custody','ONE_TIME','DISCOVERED')
        data['provider']='Arweave'
        r=self.api.submit_idea(data)
        self.assertEqual(r['reason'],'EXISTING_ARCHIVE_LAYER')
        self.assertEqual(len(self.engine.state['ideas']),1)
        data.update(novelty_delta='Real change to existing payload recovery',baseline_behavior='Current copy has only one payload',
            proposed_change='Add independently recoverable redundancy',validation_plan='Delete fragments and verify exact recovered bytes',
            baseline_evidence_ids=[r['baseline']['matches'][0]['id']])
        self.assertIn('id',self.api.submit_idea(data))

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_next_round_really_receives_new_assignment_without_old_tool_outputs(self):
        from metaweb_swarm.backend import OpenAIBackend
        from tests.test_backend import FakeProvider,tool_response,final_response
        self.prepare(two=True)
        self.engine.state['config']['role_round_limits']['Evidence Auditor']=6
        first=FakeProvider([tool_response('get_review_task',{},ident='packet-one'),
            tool_response('record_critique',{'idea_id':self.idea['id'],'verdict':'REVISE','reason':'Primary evidence is not yet sufficient',
                'decision_basis':'EVIDENCE_GAP','failure_kind':'NONE','failure_fact':'','negative_evidence_urls':[]},ident='critique-one'),final_response(output=FINAL)])
        self.engine.backend=OpenAIBackend(first)
        await self.engine.step(self.auditor)
        second=FakeProvider([tool_response('get_review_task',{},ident='packet-two'),
            tool_response('record_critique',{'idea_id':self.other['id'],'verdict':'REVISE','reason':'Second independent claim lacks primary evidence',
                'decision_basis':'EVIDENCE_GAP','failure_kind':'NONE','failure_fact':'','negative_evidence_urls':[]},ident='critique-two'),final_response(output=FINAL)])
        self.engine.backend=OpenAIBackend(second)
        await self.engine.step(self.auditor)
        wire=json.dumps(second.model.calls[0],default=str)
        self.assertNotIn('packet-one',wire)
        self.assertNotIn('critique-one',wire)
        self.assertIn('IDEA-0002',wire)
        self.assertEqual(self.other['critique']['agent_id'],self.auditor['id'])
        self.assertEqual(self.auditor['status'],'COMPLETED')
