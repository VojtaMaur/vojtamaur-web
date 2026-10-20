"""Real captured input selection, immutable repair IDs and independent review facts."""
import copy
import hashlib
import unittest
from metaweb_swarm.review_dispatch import action
from metaweb_swarm.research_tasks import local_candidates, revision
from metaweb_swarm.backend import OpenAIBackend
from tests import test_prototype_review as fixture
from tests.test_backend import SDK_AVAILABLE


class PayloadReviewFactsTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.PrototypeScopeTests.setUp
    tearDown=fixture.PrototypeScopeTests.tearDown
    for_agent=fixture.PrototypeScopeTests.for_agent
    prepare=fixture.PrototypeScopeTests.prepare
    plan=fixture.PrototypeScopeTests.plan
    artifacts=fixture.PrototypeScopeTests.artifacts
    executed=fixture.PrototypeScopeTests.executed
    evidence=fixture.PrototypeScopeTests.evidence

    def add_export(self,name,body):
        target=self.run/'input_exports'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
        receipt={'path':name,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
        self.engine.state['exports']['files'].append(receipt)
        return receipt

    def test_first_local_dispatch_copies_actual_export_without_host_experiment(self):
        self.prepare()
        self.assertEqual(action(self.local)['tool'],'prepare_prototype_input')
        result=self.local.prepare_prototype_input()
        self.assertEqual(result['input_kind'],'PAYLOAD')
        self.assertTrue(result['export'].endswith('.epub'))
        self.assertEqual(self.local.workspace.file_info(result['path'])['sha256'],result['sha256'])
        self.assertTrue(self.local.prepare_prototype_input()['replayed'])
        self.assertIsNone(action(self.local))
        self.assertFalse(self.engine.state['experiments'])

    def test_metadata_cannot_displace_content_and_full_plan_needs_payload(self):
        self.artifacts()
        self.add_export('build.epub.manifest.json',b'{"describes":"build.epub"}')
        self.local.materialize_export('build.epub.manifest.json','exports/descriptor.json')
        previous=copy.deepcopy(self.proto['prototype_plans'])
        result=self.plan(input_path='exports/descriptor.json')
        self.assertEqual(result['reason'],'PAYLOAD_EXPORT_REQUIRED')
        self.assertEqual(result['inputs']['recommended_payload']['path'],'build.epub')
        self.assertEqual(self.proto['prototype_plans'],previous)
        self.assertEqual(self.plan('SUBCOMPONENT',input_path='exports/descriptor.json')['scope'],'SUBCOMPONENT')

    def test_phantom_revision_hash_and_failed_experiment_are_rejected_atomically(self):
        self.artifacts()
        previous=copy.deepcopy(self.proto['prototype_plans'])
        args=[self.idea['id'],'Test actual content recovery','exports/input.epub','prototype/test.py',
              ['prototype/specimen.bin','prototype/recovered.bin'],'Recover all original bytes',
              'Reject actual changed bytes','FULL_MECHANISM','']
        for repair in [dict(revision_test_id=revision(self.idea)),dict(repair_experiment_id='EXPERIMENT-invented')]:
            result=self.local.record_prototype_plan(*args,**repair)
            self.assertEqual(result['reason'],'INVALID_REPAIR_REFERENCE')
            self.assertEqual(result['expected_id'],'')
            self.assertEqual(self.proto['prototype_plans'],previous)

    async def test_cross_owner_or_stale_review_id_cannot_be_used_for_a_new_plan(self):
        t=await self.executed()
        self.review.review_prototype_test(t['id'],'REVISE','A real code defect requires a repaired implementation')
        t['agent_id']='OTHER'
        from metaweb_swarm.prototype_revision import reference_issue
        self.assertEqual(reference_issue(self.local,self.idea['id'],t['id'])['reason'],'INVALID_REPAIR_REFERENCE')
        t['agent_id']=self.proto['id'];self.idea['mechanism']='New claim after the old test'
        self.assertEqual(reference_issue(self.local,self.idea['id'],t['id'])['reason'],'INVALID_REPAIR_REFERENCE')

    async def test_facts_identify_real_matching_bytes_without_certifying_decoding(self):
        t=await self.executed()
        self.evidence(t)
        self.assertEqual(action(self.review)['tool'],'get_prototype_review_facts')
        facts=self.review.get_prototype_review_facts(t['id'])
        self.assertEqual(facts['idea_id'],self.idea['id'])
        self.assertTrue(facts['identity_bound'])
        self.assertEqual(facts['matching_recovered_outputs'][0]['path'],'prototype/recovered.bin')
        self.assertEqual(facts['retained_input']['input_kind'],'PAYLOAD')
        self.assertEqual(facts['external_custody'],'NOT_ESTABLISHED_BY_LOCAL_EXECUTION')
        self.assertEqual(action(self.review)['tool'],'review_prototype_test')
        unresolved=self.review.review_prototype_test(t['id'],'REVISE','The local operation needs a specific conformance assessment')
        self.assertEqual(unresolved['reason'],'RECOVERY_OBSERVATION_REQUIRED')
        self.assertNotIn('prototype_review',t)
        self.assertFalse(self.idea['prototype_tested'])

    async def test_false_no_recovery_fact_is_corrected_but_concrete_local_defect_is_allowed(self):
        t=await self.executed();self.evidence(t);self.review.get_prototype_review_facts(t['id'])
        result=self.review.review_prototype_test(t['id'],'REVISE','There is no recovered output for this candidate',
            observed_recovery='NO_RECOVERED_OUTPUT',review_basis='LOCAL_DEFECT')
        self.assertEqual(result['reason'],'REVIEW_RECOVERY_FACT_CONFLICT')
        self.assertNotIn('prototype_review',t)
        result=self.review.review_prototype_test(t['id'],'REVISE','Recovered bytes match, but independent conformance validation is missing',
            recovered_path='prototype/recovered.bin',observed_recovery='MATCHES_INPUT',review_basis='LOCAL_DEFECT')
        self.assertEqual(result['verdict'],'REVISE')
        self.assertTrue(result['host_facts']['matching_recovered_outputs'])
        self.assertNotEqual(self.idea['status'],'REJECTED')

    async def test_external_gap_does_not_erase_valid_local_subcomponent(self):
        t=await self.executed();evidence=self.evidence(t);self.review.get_prototype_review_facts(t['id'])
        result=self.review.review_prototype_test(t['id'],'REVISE','The local inverse works but no public upload has occurred',
            **evidence,observed_recovery='MATCHES_INPUT',review_basis='EXTERNAL_GAP_ONLY')
        self.assertEqual(result['reason'],'LOCAL_COMPONENT_ASSESSMENT_REQUIRED')
        result=self.review.review_prototype_test(t['id'],'SUBCOMPONENT','The local inverse and corrupt-input cases work; public custody is untested',
            **evidence,observed_recovery='MATCHES_INPUT',review_basis='EXTERNAL_GAP_ONLY')
        self.assertEqual(result['verdict'],'SUBCOMPONENT')
        self.assertTrue(self.idea['prototype_component_tested'])
        self.assertFalse(self.idea['prototype_tested'])
        self.assertEqual(local_candidates(self.engine.state,self.proto),[])

    async def test_three_inconsistent_fact_attempts_are_a_review_block_not_code_failure(self):
        t=await self.executed();self.evidence(t);self.review.get_prototype_review_facts(t['id'])
        for _ in range(3):
            result=self.review.review_prototype_test(t['id'],'REVISE','Missing recovered bytes justify rejection of the local test',
                observed_recovery='NO_RECOVERED_OUTPUT',review_basis='LOCAL_DEFECT')
        self.assertEqual(result['contract_adjustment'],'MODEL_REVIEW_UNRESOLVED')
        self.assertTrue(result['review_unresolved'])
        self.assertEqual(self.proto['research_task_blocks'][-1]['reason'],'INDEPENDENT_REVIEW_UNRESOLVED')
        self.assertEqual(local_candidates(self.engine.state,self.proto),[])
        self.assertNotEqual(self.idea['status'],'REJECTED')

    async def test_legacy_descriptor_receipt_cannot_certify_full_web_preservation(self):
        test=await self.executed()
        # Simulate a pre-0.6.17 metadata-only FULL checkpoint; byte evidence stays identical.
        test['prototype_plan']['input']['export']='build.epub.manifest.json'
        evidence=self.evidence(test);self.review.get_prototype_review_facts(test['id'])
        result=self.review.review_prototype_test(test['id'],'FULL_MECHANISM',
            'Exact descriptor bytes were recovered but this is falsely claimed to preserve the web payload',
            **evidence,observed_recovery='MATCHES_INPUT')
        self.assertEqual(result['reason'],'DESCRIPTOR_SCOPE_LIMIT')
        self.assertFalse(self.idea['prototype_tested'])

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_actual_sdk_observes_facts_then_records_component_without_public_deposit(self):
        from tests.test_backend import FakeProvider,tool_response,final_response
        t=await self.executed()
        evidence=self.evidence(t)
        calls=[tool_response('get_prototype_review_facts',{'test_id':t['id']}),
            tool_response('review_prototype_test',dict(test_id=t['id'],verdict='SUBCOMPONENT',
                reason='Local byte inverse and corruption rejection are useful; external deposit remains untested',
                **evidence,observed_recovery='MATCHES_INPUT',review_basis='EXTERNAL_GAP_ONLY'),ident='review'),final_response()]
        provider=FakeProvider(calls);self.engine.backend=OpenAIBackend(provider)
        await self.engine.step(self.auditor)
        choices=[kw.get('model_settings',args[2] if len(args)>2 else None).tool_choice for args,kw in provider.model.calls]
        self.assertEqual(choices,['get_prototype_review_facts','review_prototype_test',None])
        self.assertEqual(t['prototype_review']['verdict'],'SUBCOMPONENT')
        self.assertFalse(self.engine.state['external_actions'])
