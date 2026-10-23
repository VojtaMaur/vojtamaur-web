"""SDK coding integration, continuous repair and host-owned boundaries. No paid API."""
import asyncio
import base64
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.backend import OpenAIBackend,BackendLimit,BackendYield
from metaweb_swarm.coding_worker import enabled,task,scope
from metaweb_swarm.research_tasks import revision,local_candidates
from metaweb_swarm.config import load_config,validate_config
from tests import test_prototype_review as fixture
from tests.test_backend import SDK_AVAILABLE,FakeProvider,tool_response


class CodingWorkerTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.PrototypeScopeTests.setUp
    tearDown=fixture.PrototypeScopeTests.tearDown
    for_agent=fixture.PrototypeScopeTests.for_agent
    prepare=fixture.PrototypeScopeTests.prepare

    def setup_worker(self):
        self.prepare()
        self.engine.state['config'].update(coding_backend='sdk_shell',coding_max_turns=12,
            max_coding_commands_per_agent=8,require_prototype_focus=True,max_total_tokens=800000,
            max_web_search_calls_per_request=3)
        self.idea['prototype_focus']={'scope':'SUBCOMPONENT','goal':'Encode and decode a real source-derived recovery component, testing semantic corruption',
            'research_revision':revision(self.idea),'agent_id':self.auditor['id']}
        self.result={'status':'READY','summary':'Implemented and exercised the actual local recovery component and invalid input checks',
            'script_path':'prototype/test.py','argv':['python','prototype/test.py'],
            'output_paths':['prototype/seed.bin','prototype/decoded.json'],
            'positive_assertion':'Read the generated specimen and assert the decoded source hash matches the export',
            'negative_assertion':'Reject a syntactically valid payload with an incorrect source hash',
            'limitations':'Local component only; external custody and complete export recovery remain untested.'}

    def mock_command(self,root,argv):
        if argv[0]=='sh':
            if 'BROKEN' in argv[-1]:
                self.local.workspace.write_file('prototype/test.py','raise ValueError("initial code bug")\n')
                return {'status':'BLOCKED','returncode':1,'output':'ValueError: initial code bug','cleanup_ok':True}
            self.local.workspace.write_file('prototype/test.py',
                'from pathlib import Path\n# fixture: actual semantic correctness is not claimed by a mock executor\nassert True\n')
            self.local.workspace.write_file('prototype/codec.py','# Mock implementation dependency retained for independent source review\n')
        else:
            self.local.workspace.write_file('prototype/seed.bin',b'newly emitted mock specimen')
            self.local.workspace.write_file('prototype/decoded.json','{"source":"mock decoder output"}')
        return {'status':'COMPLETED','returncode':0,'output':'Mock executor result for orchestration regression','cleanup_ok':True}

    def test_existing_run_keeps_legacy_unless_explicitly_configured(self):
        self.prepare()
        self.assertFalse(enabled(self.engine.state,self.proto))
        config=load_config();self.assertEqual(config['coding_backend'],'legacy')
        config['coding_backend']='unknown'
        with self.assertRaises(ValueError):validate_config(config)

    def test_fixed_operator_acceptance_has_no_discovery_or_false_novelty(self):
        self.prepare();self.engine.state['ideas']=[]
        from metaweb_swarm.coding_acceptance import seed
        seed(self.engine.state)
        self.assertEqual(len(self.engine.state['ideas']),1)
        self.assertEqual(self.engine.state['ideas'][0]['agent_id'],'OPERATOR')
        self.assertIn('KNOWN',self.engine.state['ideas'][0]['novelty'])
        self.assertEqual(self.engine.state['ideas'][0]['prototype_focus']['scope'],'SUBCOMPONENT')
        self.assertEqual(self.auditor['status'],'COMPLETED')

    def test_exact_contract_and_preserved_input_name_share_host_expectations(self):
        self.setup_worker();self.engine.state['config']['coding_acceptance']='cbor_seed'
        current=task(self.local)
        from metaweb_swarm.coding_acceptance import expected_fields
        self.assertEqual(Path(current['input']['path']).name,Path(current['input']['export']).name)
        self.assertEqual(current['acceptance_contract']['expected_fields'],expected_fields(current['input']))
        self.assertEqual(self.engine.state['coding_acceptance_contract'],current['acceptance_contract'])

    def test_old_materialized_name_is_retained_on_resume(self):
        self.setup_worker();chosen=self.engine.state['exports']['files'][0]
        old='inputs/'+chosen['sha256'][:12]+'-'+Path(chosen['path']).name
        self.local.materialize_export(chosen['path'],old)
        self.assertEqual(task(self.local)['input']['path'],old)

    async def test_name_mismatch_is_a_precise_diagnostic_not_a_hidden_expectation(self):
        import cbor2
        from metaweb_swarm.coding_acceptance import expected_fields,validate
        self.setup_worker();current=task(self.local)
        fields=expected_fields(current['input']);fields['export']='transport-prefix-'+fields['export']
        self.local.workspace.write_file('prototype/seed.cbor',cbor2.dumps(cbor2.CBORTag(55799,fields)))
        check=await validate(self.local,current,{'experiment_id':'EXPERIMENT-name-mismatch'})
        self.assertFalse(check['passed']);self.assertEqual(check['mismatched_fields'],['export'])
        self.assertEqual(check['expected']['sha256'],fields['sha256'])

    def test_discovery_defer_is_advice_not_a_local_execution_permission(self):
        self.setup_worker();self.idea['prototype_focus']['scope']='DEFER'
        self.assertIn(self.idea,local_candidates(self.engine.state,self.proto))
        self.assertEqual(scope(self.idea),'SUBCOMPONENT')
        self.idea['prototype_focus']['scope']='FULL_MECHANISM'
        self.assertEqual(scope(self.idea),'FULL_MECHANISM')
        self.idea['mechanism']='Changed claim after focus assessment'
        self.assertEqual(scope(self.idea),'SUBCOMPONENT')

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_host_failure_is_repaired_in_same_sdk_quantum(self):
        from tests.test_backend import response
        self.setup_worker();self.engine.state['config']['coding_acceptance']='cbor_seed'
        self.mock_command(self.local.workspace.root,['sh','INITIAL'])
        self.local.workspace.write_file('prototype/codec.py','# Incorrect fixture code before host feedback\n')
        def ready(ident):return response([{'type':'message','id':ident,'role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':json.dumps(self.result),'annotations':[]}]}])
        provider=FakeProvider([ready('initial-ready'),
            tool_response('exec_command',{'cmd':'REPAIR_AND_RUN','yield_time_ms':10000},ident='feedback-repair'),ready('repaired-ready')])
        failed={'passed':False,'reason':'CBOR metadata mismatch in export',
            'expected':{'export':'build.epub'},'actual':{'export':'prefix-build.epub'},'mismatched_fields':['export']}
        with patch('metaweb_swarm.workspace.DockerExecutor') as development,patch('metaweb_swarm.engine.DockerExecutor') as final,patch('metaweb_swarm.coding_acceptance.validate') as validate:
            development.return_value.run.side_effect=self.mock_command
            final.return_value.run.side_effect=self.mock_command
            validate.side_effect=[failed,{'passed':True,'reason':'Mock acceptance passed after code repair'}]
            result=await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
        self.assertEqual(result['output']['status'],'COMPLETED')
        self.assertEqual(len(provider.model.calls),3)
        self.assertEqual(validate.await_count,2)
        second=provider.model.calls[1]
        encoded=str(second)
        self.assertIn('HOST_VALIDATION_FEEDBACK',encoded)
        self.assertIn('prefix-build.epub',encoded)
        self.assertEqual(len(self.engine.state['tests']),1)
        self.assertEqual(self.proto['rounds'],0)  # No scheduler round requested by the repair loop.
        self.assertFalse(self.engine.state.get('budget_reservations'))

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_host_retry_uses_shared_turn_limit_and_retains_feedback(self):
        from tests.test_backend import response
        self.setup_worker();self.engine.state['config']['coding_max_turns']=1
        provider=FakeProvider([response([{'type':'message','id':'ready','role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':json.dumps(self.result),'annotations':[]}]}])])
        async def reject(api,result,current):
            api.agent['coding_last_result']={'passed':False,'reason':'A required negative test failed'}
            return {'status':'CONTINUE','summary':'Host check failed','reason_for_stopping':'Repair the implementation'}
        with patch('metaweb_swarm.coding_worker.finalize',side_effect=reject):
            with self.assertRaises(BackendYield) as caught:
                await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
        self.assertEqual(len(provider.model.calls),1)
        self.assertIn('HOST_VALIDATION_FEEDBACK',json.dumps(caught.exception.history))
        self.assertFalse(self.engine.state.get('budget_reservations'))

    def test_stale_ready_claims_are_removed_but_tool_pairs_are_retained(self):
        from metaweb_swarm.coding_worker import without_final_claims
        pair=[{'type':'function_call','call_id':'a','name':'exec_command','arguments':'{}'},
              {'type':'function_call_output','call_id':'a','output':'actual output'}]
        history=pair+[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps({'status':'READY','script_path':'test.py'})}]}]
        self.assertEqual(without_final_claims(history),pair)

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_real_sdk_keeps_failed_command_and_repair_in_one_coding_turn(self):
        from tests.test_backend import response
        self.setup_worker()
        provider=FakeProvider([tool_response('exec_command',{'cmd':'WRITE_BROKEN_AND_RUN','yield_time_ms':10000}),
            tool_response('exec_command',{'cmd':'REPAIR_AND_RUN','yield_time_ms':10000},ident='repair'),
            response([{'type':'message','id':'final','role':'assistant','status':'completed',
                'content':[{'type':'output_text','text':json.dumps(self.result),'annotations':[]}]}])])
        with patch('metaweb_swarm.workspace.DockerExecutor') as docker:
            docker.return_value.run.side_effect=self.mock_command
            # Final controlled capture imports the same executor at engine-module scope.
            with patch('metaweb_swarm.engine.DockerExecutor') as final:
                final.return_value.run.side_effect=self.mock_command
                result=await OpenAIBackend(provider).step(self.proto,'ignored legacy prompt',[],self.local,self.engine.state['config'])
        self.assertEqual(len(provider.model.calls),3)
        self.assertEqual(result['output']['status'],'COMPLETED')
        self.assertEqual([r['returncode'] for r in self.engine.state['coding_commands']],[1,0])
        self.assertEqual(len(self.engine.state['tests']),1)
        self.assertIn('prototype/codec.py',[a['path'] for a in self.engine.state['tests'][0]['artifacts']])
        self.assertFalse(self.idea['prototype_tested'])
        self.assertFalse(self.engine.state.get('prototype_plan_submissions'))
        self.assertFalse(self.engine.state.get('budget_reservations'))
        self.assertTrue(all(r['max_search_calls']==0 for r in self.engine.state['budget_settlements'].values()))
        first=provider.model.calls[0]
        tools=first[1].get('tools',first[0][3] if len(first[0])>3 else [])
        self.assertTrue({'exec_command'} <= {t.name for t in tools})
        self.assertFalse({'record_prototype_plan','record_test','execute_prototype'} & {t.name for t in tools})

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_sdk_turn_exhaustion_retains_tool_history_for_resume(self):
        self.setup_worker();self.engine.state['config']['coding_max_turns']=1
        provider=FakeProvider([tool_response('exec_command',{'cmd':'REPAIR_AND_RUN','yield_time_ms':10000})])
        with patch('metaweb_swarm.workspace.DockerExecutor') as docker:
            docker.return_value.run.side_effect=self.mock_command
            with self.assertRaises(BackendYield) as caught:
                await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
        history=json.dumps(caught.exception.history)
        self.assertIn('exec_command',history)
        self.assertTrue((self.local.workspace.root/'prototype/test.py').is_file())
        self.assertEqual(len(self.engine.state['coding_commands']),1)
        self.assertFalse(self.engine.state.get('budget_reservations'))

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_unresolved_cleanup_blocks_another_command_and_final_capture(self):
        from metaweb_swarm.backend import BackendBlocked
        from metaweb_swarm.coding_session import create_session
        from metaweb_swarm.coding_worker import finalize
        self.setup_worker()
        with patch('metaweb_swarm.workspace.DockerExecutor') as docker:
            docker.return_value.run.return_value={'status':'BLOCKED','returncode':1,'cleanup_ok':False,'cleanup_error':'fixture: cannot remove container'}
            session=create_session(self.local)
            with self.assertRaises(BackendBlocked):await session.exec('echo fixture')
            with self.assertRaises(BackendBlocked):await session.exec('echo must-not-run')
            self.assertEqual(docker.return_value.run.call_count,1)
        with self.assertRaises(BackendBlocked):await finalize(self.local,self.result,task(self.local))

    async def test_revision_can_repair_helper_without_fake_driver_edits(self):
        from metaweb_swarm.coding_worker import finalize
        from metaweb_swarm.review_tasks import assign
        self.setup_worker()
        self.mock_command(self.local.workspace.root,['sh','REPAIR_AND_RUN'])
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=self.mock_command
            first=await finalize(self.local,self.result,task(self.local))
            self.assertEqual(first['status'],'COMPLETED')
            test=self.engine.state['tests'][0]
            assign(self.engine,self.auditor)
            self.review.review_prototype_test(test['id'],'REVISE','The helper needs a semantic corruption check inside the decoder',
                required_local_change='Add a semantic corruption check in the actual decoder helper',
                defect_code='# Mock implementation dependency retained for independent source review')
            self.local.workspace.write_file('prototype/codec.py','# Actual helper revision; driver unchanged\nassert "changed" != "original"\n')
            second=await finalize(self.local,self.result,task(self.local))
        self.assertEqual(second['status'],'COMPLETED')
        self.assertEqual(len(self.engine.state['tests']),2)
        old,new=self.engine.state['tests']
        self.assertEqual(old['prototype_plan']['script']['sha256'],new['prototype_plan']['script']['sha256'])
        self.assertNotEqual(next(a['sha256'] for a in old['artifacts'] if a['path'].endswith('codec.py')),
                            next(a['sha256'] for a in new['artifacts'] if a['path'].endswith('codec.py')))

    def test_acceptance_profile_and_report_separate_commands_from_certified_tests(self):
        config=load_config(Path(__file__).resolve().parents[1]/'config.prototype.json')
        self.assertEqual(config['coding_backend'],'sdk_shell')
        self.assertEqual(config['max_external_actions'],0)
        config['coding_acceptance']={}
        with self.assertRaises(ValueError):validate_config(config)
        self.setup_worker()
        self.engine.state['coding_commands']=[{'id':'CODE-fixture','status':'BLOCKED'}]
        self.engine.state['coding_validations']=[{'id':'VALID-fixture','passed':True}]
        from metaweb_swarm.report_packet import build,SECTIONS
        packet=build(self.engine.state)
        self.assertEqual(packet['counts']['coding_commands'],1)
        self.assertEqual(packet['counts']['coding_acceptance_passes'],1)
        self.assertEqual(packet['counts']['recorded_tests'],0)
        self.assertIn('coding_commands',SECTIONS)

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_token_limit_and_pause_stop_before_another_paid_request(self):
        self.setup_worker();self.engine.state['config']['max_total_tokens']=1
        provider=FakeProvider([])
        with self.assertRaises(BackendLimit):
            await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
        self.assertEqual(provider.model.calls,[])
        self.engine.state['config']['max_total_tokens']=800000
        (self.run/'PAUSE.flag').write_text('pause')
        with self.assertRaises(BackendYield):
            await OpenAIBackend(provider).step(self.proto,'unused',[],self.local,self.engine.state['config'])
        self.assertEqual(provider.model.calls,[])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_supervision_and_command_limits_never_fall_back_to_host(self):
        self.setup_worker()
        from metaweb_swarm.coding_session import create_session
        session=create_session(self.local)
        with patch('metaweb_swarm.workspace.DockerExecutor') as docker:
            # Create after patch: the adapter captures this executor dependency.
            session=create_session(self.local)
            self.engine.state['config']['run_mode']='supervised'
            self.assertEqual((await session.exec('echo unsafe')).exit_code,126)
            self.engine.state['config']['run_mode']='autonomous'
            self.engine.state['config']['max_coding_commands_per_agent']=0
            with self.assertRaises(BackendLimit):await session.exec('echo unsafe')
            docker.assert_not_called()
        with self.assertRaises(ValueError):await session.read(Path('/etc/passwd'))

    async def test_acceptance_rejects_false_positive_artifacts_before_decoder_execution(self):
        self.setup_worker();current=task(self.local)
        self.local.workspace.write_file('prototype/seed.cbor',b'not actual CBOR')
        from metaweb_swarm.coding_acceptance import validate
        with patch('metaweb_swarm.workspace.DockerExecutor') as docker:
            check=await validate(self.local,current,{'experiment_id':'EXPERIMENT-test'})
            docker.assert_not_called()
        self.assertFalse(check['passed'])
        self.assertIn('55799',check['reason'])
        self.assertFalse(self.engine.state['tests'])

    async def test_acceptance_checks_transcription_and_semantic_decoder_failures(self):
        import cbor2
        self.setup_worker();current=task(self.local);source=current['input']
        fields={'export':Path(source['export']).name,'sha256':source['sha256'],'bytes':source['bytes'],'decoder':'metaweb-cbor-seed-v1'}
        body=cbor2.dumps(cbor2.CBORTag(55799,fields),canonical=True)
        self.local.workspace.write_file('prototype/seed.cbor',body)
        self.local.workspace.write_file('prototype/mirror.txt','METAWEB-CBOR-1\n'+base64.b64encode(body).decode()+'\n')
        self.local.workspace.write_file('prototype/decoded.json',json.dumps(fields))
        from metaweb_swarm.coding_acceptance import validate
        with patch('metaweb_swarm.workspace.DockerExecutor') as docker:
            docker.return_value.run.return_value={'status':'BLOCKED','returncode':1,'cleanup_ok':True,
                'output':'AssertionError: Decoder accepted invalid or semantically corrupted input'}
            check=await validate(self.local,current,{'experiment_id':'EXPERIMENT-test'})
        self.assertFalse(check['passed'])
        self.assertIn('semantically corrupted',check['reason'])
        self.assertFalse(self.idea['prototype_tested'])
