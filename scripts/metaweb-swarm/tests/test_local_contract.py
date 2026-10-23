"""One local scope for coding/review and no repair credit for extra documents."""
import copy,unittest
from unittest.mock import patch
from metaweb_swarm.local_contract import bind,attach,current
from metaweb_swarm.coding_worker import finalize,task
from metaweb_swarm.review_tasks import assign
from tests import test_prototype_review as scope_fixture
from tests import test_coding_worker as coding_fixture
from tests.test_backend import SDK_AVAILABLE,FakeProvider,tool_response,final_response
from metaweb_swarm.backend import OpenAIBackend,BackendBlocked


class LocalContractReviewTests(unittest.IsolatedAsyncioTestCase):
    setUp=scope_fixture.PrototypeScopeTests.setUp
    tearDown=scope_fixture.PrototypeScopeTests.tearDown
    for_agent=scope_fixture.PrototypeScopeTests.for_agent
    prepare=scope_fixture.PrototypeScopeTests.prepare
    plan=scope_fixture.PrototypeScopeTests.plan
    artifacts=scope_fixture.PrototypeScopeTests.artifacts
    executed=scope_fixture.PrototypeScopeTests.executed
    evidence=scope_fixture.PrototypeScopeTests.evidence

    async def captured(self):
        t=await self.executed('SUBCOMPONENT');p=t['prototype_plan']
        result={'local_operation':'Base64 encode and decode source bytes and detect an altered saved payload',
                'positive_assertion':p['positive_assertion'],'negative_assertion':p['negative_assertion'],
                'limitations':'Local serialization only; public publication and remote custody are not tested.'}
        contract=bind(self.local,{'idea_id':self.idea['id'],'scope_ceiling':'SUBCOMPONENT'},result)
        attach(self.local,p,contract);assign(self.engine,self.auditor)
        self.evidence(t);self.review.get_prototype_review_facts(t['id'])
        return t

    async def test_same_contract_survives_wording_changes_and_is_in_review_facts(self):
        t=await self.captured();contract=current(self.local,self.idea['id'])
        changed=bind(self.local,{'idea_id':self.idea['id'],'scope_ceiling':'FULL_MECHANISM'},
                     {'local_operation':'Changed target requiring unrelated public deployment'})
        self.assertEqual(changed,contract)
        self.assertEqual(self.review.get_prototype_review_facts(t['id'])['local_contract'],contract)
        self.assertEqual(self.review.get_review_task()['prototype_plan']['local_contract'],contract)

    async def test_passing_local_component_can_be_accepted_without_public_upload(self):
        t=await self.captured()
        verdict=self.review.review_prototype_test(t['id'],'SUBCOMPONENT',
            'The relevant local operation has executable positive and negative cases; public custody remains untested.',
            **self.evidence(t),observed_recovery='MATCHES_INPUT',review_basis='EXTERNAL_GAP_ONLY')
        self.assertEqual(verdict['verdict'],'SUBCOMPONENT')
        self.assertTrue(self.idea['prototype_component_tested']);self.assertFalse(self.idea['prototype_tested'])
        self.assertEqual(self.engine.state['external_actions'],[])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_actual_sdk_tool_carries_contract_assessment_without_publication(self):
        t=await self.captured();args=dict(test_id=t['id'],verdict='SUBCOMPONENT',
            reason='Relevant local operation passes the executed positive and negative checks; remote custody is untested.',
            **self.evidence(t),observed_recovery='MATCHES_INPUT',review_basis='EXTERNAL_GAP_ONLY',
            required_local_change='',defect_code='')
        provider=FakeProvider([tool_response('review_prototype_test',scope_fixture.range_args(self.review,t,args)),final_response()])
        await OpenAIBackend(provider).step(self.auditor,self.engine.prompt(self.auditor),[],self.review,self.engine.state['config'])
        self.assertEqual(t['prototype_review']['verdict'],'SUBCOMPONENT')
        self.assertNotIn('local_contract_status',t['prototype_review'])
        self.assertEqual(t['prototype_review']['local_contract_id'],t['prototype_plan']['local_contract']['id'])
        self.assertEqual(self.engine.state['external_actions'],[])
        args,kwargs=provider.model.calls[0]
        tools=kwargs.get('tools',args[3] if len(args)>3 else [])
        tool=next(t for t in tools if t.name=='review_prototype_test')
        self.assertNotIn('local_contract_status',tool.params_json_schema['properties'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_resume_archives_old_status_context_and_sdk_revise_reaches_coder(self):
        t=await self.captured()
        from metaweb_swarm.engine import unblock
        from metaweb_swarm.research_tasks import prepare_task_context
        from metaweb_swarm.prototype_queue import synchronize
        self.engine.state['config'].update(coding_backend='sdk_shell',max_steps=40)
        self.auditor.update(status='BLOCKED',active_task_key='old-0.7.7-review',
            history=[{'role':'user','content':'Obsolete local_contract_status SATISFIED instruction'}])
        self.proto.update(status='BLOCKED',prototype_queue_hold='AWAITING_INDEPENDENT_PROTOTYPE_REVIEW')
        prior=copy.deepcopy(self.engine.state['config']);original_script=t['prototype_plan']['script']['sha256']
        unblock(self.engine.store,self.engine.state,self.auditor['id'],'Single verdict interface fixed; finish this review')
        prepare_task_context(self.engine,self.auditor,self.review.workspace)
        self.assertEqual(self.auditor['history'],[])
        self.assertIn('review-environment-0.8.3',self.auditor['active_task_key'])
        self.evidence(t);self.review.get_prototype_review_facts(t['id'])
        change='Read a damaged saved specimen through the decoder and assert actual rejection'
        args=dict(test_id=t['id'],verdict='REVISE',reason='The negative case must exercise damaged saved input rather than a copied variable',
            required_local_change=change,negative_code='encoded=base64.b64encode(data)',
            observed_recovery='MATCHES_INPUT',recovered_path='prototype/recovered.bin',review_basis='LOCAL_DEFECT')
        provider=FakeProvider([tool_response('review_prototype_test',scope_fixture.range_args(self.review,t,args)),final_response()])
        await OpenAIBackend(provider).step(self.auditor,self.engine.prompt(self.auditor),[],self.review,self.engine.state['config'])
        synchronize(self.engine)
        self.assertEqual(t['prototype_review']['verdict'],'REVISE')
        self.assertEqual(self.local.get_research_task()['test_revision']['required_local_change'],change)
        self.assertEqual(self.proto['status'],'PENDING')
        self.assertEqual(self.engine.state['config'],prior)
        self.assertEqual(t['prototype_plan']['script']['sha256'],original_script)

    async def test_old_secondary_field_is_ignored_for_grounded_revise(self):
        t=await self.captured()
        result=self.review.review_prototype_test(t['id'],'REVISE','The negative test must exercise the saved specimen through its decoder',
            observed_recovery='MATCHES_INPUT',recovered_path='prototype/recovered.bin',
            review_basis='LOCAL_DEFECT',local_contract_status='SATISFIED',
            required_local_change='Read a damaged saved specimen through the decoder and assert rejection',
            defect_code='encoded=base64.b64encode(data)')
        self.assertEqual(result['verdict'],'REVISE')
        self.assertNotIn('local_contract_status',result)

    async def test_revise_requires_specific_local_change_and_real_code_quote(self):
        t=await self.captured()
        args=dict(required_local_change='Read the saved generated specimen before decoding instead of the in-memory buffer',
                  defect_code='this nonexistent operation was never executed')
        first=self.review.review_prototype_test(t['id'],'REVISE','The frozen operation needs a saved-file decoder path',**args)
        self.assertEqual(first['reason'],'LOCAL_DEFECT_CODE_NOT_IN_EXECUTED_SOURCE')
        args['defect_code']='encoded=base64.b64encode(data)'
        result=self.review.review_prototype_test(t['id'],'REVISE','The frozen operation needs a saved-file decoder path',
            observed_recovery='MATCHES_INPUT',recovered_path='prototype/recovered.bin',review_basis='LOCAL_DEFECT',**args)
        self.assertEqual(result['verdict'],'REVISE')
        self.assertEqual(result['required_local_change'],args['required_local_change'])
        self.assertEqual(result['local_contract_id'],t['prototype_plan']['local_contract']['id'])

    async def test_missing_repair_evidence_is_bounded_without_fabricating_verdict(self):
        t=await self.captured()
        if SDK_AVAILABLE:
            args=dict(test_id=t['id'],verdict='REVISE',reason='The local operation needs a real damaged input case',positive_refs=[],negative_refs=[])
            provider=FakeProvider([tool_response('review_prototype_test',args,ident='bad-review-'+str(n)) for n in range(4)])
            with self.assertRaisesRegex(BackendBlocked,'LOCAL_CONTRACT_REVIEW_STALLED'):
                await OpenAIBackend(provider).step(self.auditor,self.engine.prompt(self.auditor),[],self.review,self.engine.state['config'])
            self.assertEqual(len(provider.model.calls),3)
        else:
            for _ in range(2):
                self.review.review_prototype_test(t['id'],'REVISE','The local operation needs a real damaged input case')
            with self.assertRaisesRegex(BackendBlocked,'LOCAL_CONTRACT_REVIEW_STALLED'):
                self.review.review_prototype_test(t['id'],'REVISE','The local operation needs a real damaged input case')
        self.assertNotIn('prototype_review',t)
        self.assertFalse(self.proto.get('research_task_blocks'))
        # No fake verdict means the same review can be completed correctly after resolution.
        accepted=self.review.review_prototype_test(t['id'],'SUBCOMPONENT','The local operation passes; public custody remains untested',
            **self.evidence(t),observed_recovery='MATCHES_INPUT',review_basis='EXTERNAL_GAP_ONLY')
        self.assertEqual(accepted['verdict'],'SUBCOMPONENT')

    async def test_three_repairs_retain_hypothesis_without_scientific_rejection(self):
        original=await self.captured();t=original
        for n in range(4):
            if n:
                t=copy.deepcopy(original);t['id']='TEST-REPAIR-'+str(n);t.pop('prototype_review',None)
                self.engine.state['tests'].append(t);assign(self.engine,self.auditor)
                self.evidence(t);self.review.get_prototype_review_facts(t['id'])
            verdict=self.review.review_prototype_test(t['id'],'REVISE','Saved specimen is not read through the actual decoder',
                required_local_change='Read the saved generated specimen through the decoder instead of the original buffer',
                defect_code='encoded=base64.b64encode(data)',observed_recovery='MATCHES_INPUT',
                recovered_path='prototype/recovered.bin',review_basis='LOCAL_DEFECT')
            self.assertEqual(verdict['verdict'],'REVISE')
            self.assertEqual(bool(self.proto.get('research_task_blocks')),n==3)
        self.assertEqual(self.proto['research_task_blocks'][-1]['reason'],'LOCAL_CONTRACT_REPAIR_LIMIT')
        self.assertNotEqual(self.idea['status'],'REJECTED')


class LocalImplementationRepairTests(unittest.IsolatedAsyncioTestCase):
    setUp=coding_fixture.CodingWorkerTests.setUp
    tearDown=coding_fixture.CodingWorkerTests.tearDown
    for_agent=coding_fixture.CodingWorkerTests.for_agent
    prepare=coding_fixture.CodingWorkerTests.prepare
    setup_worker=coding_fixture.CodingWorkerTests.setup_worker
    mock_command=coding_fixture.CodingWorkerTests.mock_command

    async def revised(self):
        self.setup_worker();self.result['local_operation']='Encode the recovery specimen and decode it through the real local parser'
        self.mock_command(self.local.workspace.root,['sh','INITIAL'])
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=self.mock_command
            self.assertEqual((await finalize(self.local,self.result,task(self.local)))['status'],'COMPLETED')
        test=self.engine.state['tests'][-1];assign(self.engine,self.auditor)
        self.review.review_prototype_test(test['id'],'REVISE','Implement the missing semantic corruption check in the helper',
            required_local_change='Implement semantic corruption rejection inside the current decoder helper',
            defect_code='# Mock implementation dependency retained for independent source review')
        return test

    async def test_adding_readme_json_and_outputs_cannot_resubmit_same_driver(self):
        t=await self.revised();before=len(self.engine.state['experiments'])
        self.local.workspace.write_file('source/vojtamaur-web/new-reference.md','New reference is not executable repair')
        self.local.workspace.write_file('work/reference.json','{"unrelated":"new reference"}')
        value=copy.deepcopy(self.result);value['source_paths']=['source/vojtamaur-web/new-reference.md','work/reference.json']
        value['output_paths'].append('work/extra-output.json')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            out=await finalize(self.local,value,task(self.local));docker.assert_not_called()
        self.assertEqual(out['status'],'CONTINUE')
        self.assertEqual(self.proto['coding_last_result']['reason'],'REVISED_IMPLEMENTATION_UNCHANGED')
        self.assertEqual(len(self.engine.state['experiments']),before)

    async def test_new_unreferenced_code_file_does_not_count_as_fix_to_existing_driver(self):
        await self.revised()
        self.local.workspace.write_file('prototype/unused.py','print("not imported by the driver")\n')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            await finalize(self.local,self.result,task(self.local));docker.assert_not_called()
        self.assertEqual(self.proto['coding_last_result']['reason'],'REVISED_IMPLEMENTATION_UNCHANGED')

    async def test_existing_helper_change_reexecutes_under_original_local_contract(self):
        t=await self.revised();contract=copy.deepcopy(t['prototype_plan']['local_contract'])
        self.local.workspace.write_file('prototype/codec.py','assert "repaired" != "original"\n')
        changed=copy.deepcopy(self.result);changed.update(local_operation='A different weaker operation',positive_assertion='Ignore old expected behavior')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            docker.return_value.run.side_effect=self.mock_command
            out=await finalize(self.local,changed,task(self.local))
        self.assertEqual(out['status'],'COMPLETED')
        plan=self.engine.state['tests'][-1]['prototype_plan']
        self.assertEqual(plan['local_contract'],contract)
        self.assertEqual(plan['property_tested'],contract['operation'])
        self.assertEqual(plan['positive_assertion'],contract['positive_assertion'])
