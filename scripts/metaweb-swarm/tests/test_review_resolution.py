"""Invalid reviewer evidence never becomes a coding defect; resume retains history."""
import copy,unittest
from metaweb_swarm.backend import BackendBlocked,_make_sdk_tools
from metaweb_swarm.prototype_review import pending,packet
from metaweb_swarm.prototype_queue import synchronize
from metaweb_swarm.review_resolution import recover
from metaweb_swarm.review_tasks import assign
from tests import test_local_contract as fixture
from tests.test_backend import SDK_AVAILABLE

class ReviewResolutionTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.LocalContractReviewTests.setUp
    tearDown=fixture.LocalContractReviewTests.tearDown
    for_agent=fixture.LocalContractReviewTests.for_agent
    prepare=fixture.LocalContractReviewTests.prepare
    plan=fixture.LocalContractReviewTests.plan
    artifacts=fixture.LocalContractReviewTests.artifacts
    executed=fixture.LocalContractReviewTests.executed
    evidence=fixture.LocalContractReviewTests.evidence
    captured=fixture.LocalContractReviewTests.captured

    async def ready(self):
        t=await self.captured()
        self.engine.state['config'].update(coding_backend='sdk_shell',max_steps=40)
        return t

    async def test_host_binds_full_recovery_without_model_path_or_hash_enum(self):
        t=await self.ready();t['prototype_plan']['scope']='FULL_MECHANISM'
        e=self.evidence(t);e.pop('recovered_path')
        result=self.review.review_prototype_test(t['id'],'FULL_MECHANISM',
            'Mock review of the actual local roundtrip and negative case; no external custody claim',
            observed_recovery=None,review_basis=None,**e)
        self.assertEqual(result['recovered_path'],'prototype/recovered.bin')
        self.assertEqual(result['observed_recovery'],'MATCHES_INPUT')
        self.assertEqual(result['observation_source'],'HOST_HASHES')

    async def test_invented_code_stops_without_verdict_or_owner_repair(self):
        t=await self.ready()
        args=dict(observed_recovery=None,review_basis=None,
            positive_code='assert fabricated_output_is_valid',negative_code='assert invented_corruption_is_rejected')
        for _ in range(2):
            result=self.review.review_prototype_test(t['id'],'SUBCOMPONENT','Reviewer tries to approve nonexistent executable evidence',**args)
            self.assertEqual(result['reason'],'ACTUAL_TEST_CASE_EVIDENCE_REQUIRED')
        with self.assertRaisesRegex(BackendBlocked,'PROTOTYPE_REVIEW_EVIDENCE_STALLED'):
            self.review.review_prototype_test(t['id'],'SUBCOMPONENT','Reviewer tries to approve nonexistent executable evidence',**args)
        self.assertNotIn('prototype_review',t)
        self.assertFalse(self.proto.get('research_task_blocks'))
        self.assertTrue(any(x['target_id']==t['id'] for x in pending(self.engine.state,self.auditor)))

    async def test_legacy_unresolved_review_reopens_then_grounded_revise_reaches_worker(self):
        t=await self.ready();state=self.engine.state
        unresolved=dict(id='INVALID-LEGACY',test_id=t['id'],agent_id=self.auditor['id'],
            verdict='REVISE',requested_verdict='SUBCOMPONENT',review_unresolved=True)
        state.setdefault('prototype_reviews',[]).append(unresolved);t['prototype_review']=unresolved
        block=dict(idea_id=self.idea['id'],test_id=t['id'],phase='LOCAL',reason='INDEPENDENT_REVIEW_UNRESOLVED')
        unrelated=dict(reason='DO_NOT_CLEAR_HUMAN_CREDENTIAL_BLOCK')
        self.proto['research_task_blocks']=[block,unrelated]
        self.proto.update(status='BLOCKED',prototype_queue_hold='AWAITING_INDEPENDENT_PROTOTYPE_REVIEW')
        self.auditor.update(status='PENDING')
        budget=copy.deepcopy(state['config']);rounds=self.auditor['rounds']
        self.assertEqual(recover(self.engine),[t['id']]);self.assertEqual(recover(self.engine),[])
        self.assertTrue(block['resolved']);self.assertNotIn('resolved',unrelated)
        self.assertTrue(unresolved['review_unresolved']);self.assertEqual(unresolved['verdict'],'REVISE')
        self.assertEqual(packet(state,self.auditor,dict(target_id=t['id']))['stage'],'REVIEW_TEST')
        assign(self.engine,self.auditor)
        result=self.review.review_prototype_test(t['id'],'REVISE',
            'The saved negative specimen must actually pass through the decoder',
            observed_recovery=None,review_basis=None,
            required_local_change='Decode a deliberately corrupted saved specimen and assert actual rejection',
            defect_code='encoded=base64.b64encode(data)')
        self.assertEqual(result['verdict'],'REVISE')
        self.assertIs(t['prototype_review'],result)
        self.assertFalse(any(x['target_id']==t['id'] for x in pending(state,self.auditor)))
        self.proto['research_task_blocks'].remove(unrelated)
        synchronize(self.engine)
        self.assertEqual(self.proto['status'],'PENDING')
        self.assertEqual(state['config'],budget);self.assertEqual(self.auditor['rounds'],rounds)
        self.assertEqual(len(state['prototype_reviews']),2)

    async def test_resolved_review_is_not_reopened(self):
        t=await self.ready();e=self.evidence(t);e.pop('recovered_path')
        self.review.review_prototype_test(t['id'],'SUBCOMPONENT','Actual bounded local cases work; remote custody remains untested',
            observed_recovery=None,review_basis=None,**e)
        self.assertEqual(recover(self.engine),[])
        self.assertFalse(any(x['target_id']==t['id'] for x in pending(self.engine.state,self.auditor)))

    @unittest.skipUnless(SDK_AVAILABLE,'SDK optional')
    async def test_live_schema_asks_for_judgment_not_host_facts(self):
        await self.ready()
        import agents
        tool=next(t for t in _make_sdk_tools(agents,self.review)[0] if t.name=='review_prototype_test')
        fields=tool.params_json_schema['properties']
        for name in ('local_contract_status','observed_recovery','review_basis','recovered_path','defect_code'):
            self.assertNotIn(name,fields)
        for name in ('verdict','positive_refs','negative_refs','required_local_change'):
            self.assertIn(name,fields)

    async def test_new_context_rereads_source_and_does_not_receive_old_fabricated_quote(self):
        t=await self.ready();state=self.engine.state
        invented="NONEXISTENT_SHELL_CODE output/recovery_seed.json"
        record=dict(id='INVALID',test_id=t['id'],idea_id=self.idea['id'],agent_id=self.auditor['id'],
            verdict='REVISE',review_unresolved=True,positive_code=invented,negative_code=invented)
        state.setdefault('prototype_reviews',[]).append(record);t['prototype_review']=record
        self.auditor.update(active_task_key='old-context',history=[{'role':'user','content':invented}])
        from metaweb_swarm.research_tasks import prepare_task_context
        from metaweb_swarm.review_dispatch import action
        prepare_task_context(self.engine,self.auditor,self.review.workspace)
        self.assertNotIn(invented,self.engine.prompt(self.auditor))
        self.assertEqual(self.auditor['history'],[])
        self.assertEqual(action(self.review)['tool'],'read_test_artifact')
        self.assertEqual(action(self.review)['arguments']['path'],t['prototype_plan']['script']['path'])
        self.assertNotIn(t['id'],self.auditor.get('prototype_artifact_reads',{}))
        self.assertNotIn(t['id'],self.auditor.get('prototype_fact_reads',{}))
        self.assertEqual(record['positive_code'],invented)
        # Current context really reads immutable source and outputs, then facts.
        self.evidence(t)
        self.assertEqual(action(self.review)['tool'],'get_prototype_review_facts')
        self.review.get_prototype_review_facts(t['id'])
        self.assertEqual(action(self.review)['tool'],'review_prototype_test')
        prepare_task_context(self.engine,self.auditor,self.review.workspace)
        self.assertEqual(action(self.review)['tool'],'review_prototype_test')

    async def test_overview_keeps_status_and_ids_without_replaying_model_claims_as_source(self):
        await self.ready()
        from metaweb_swarm.memory import concise_state
        record=dict(id='HISTORICAL',test_id='T',idea_id=self.idea['id'],agent_id=self.auditor['id'],
                    verdict='REVISE',review_unresolved=True,positive_code='fake executable',reason='false claim')
        self.engine.state['prototype_reviews']=[record]
        preview=concise_state(self.engine.state)['execution_receipts']['prototype_reviews'][0]
        self.assertEqual(preview['id'],'HISTORICAL');self.assertIsNone(preview['verdict'])
        self.assertNotIn('positive_code',preview);self.assertNotIn('reason',preview)
        self.assertEqual(record['reason'],'false claim')

    async def test_repair_uses_existing_source_case_once_with_host_provenance(self):
        t=await self.ready()
        quote="assert hashlib.sha256(decoded+b'!').digest()!=hashlib.sha256(data).digest()"
        result=self.review.review_prototype_test(t['id'],'REVISE','The negative case must invoke the decoder on a saved corrupted specimen',
            negative_code=quote,required_local_change='Read a corrupted saved specimen through the decoder and assert actual rejection',
            observed_recovery=None,review_basis=None,defect_code=None)
        self.assertEqual(result['verdict'],'REVISE')
        self.assertEqual(result['defect_code'],quote)
        self.assertEqual(result['defect_evidence']['field'],'negative_code')
        self.assertEqual(result['defect_evidence']['path'],t['prototype_plan']['script']['path'])
        self.assertEqual(result['defect_evidence']['sha256'],t['prototype_plan']['script']['sha256'])

    async def test_prose_or_invented_case_cannot_supply_repair_source_evidence(self):
        t=await self.ready()
        result=self.review.review_prototype_test(t['id'],'REVISE','A damaged input validation path is missing from the executed code',
            negative_code='This test is broken because the validation is a no-op',
            required_local_change='Feed a corrupted saved specimen to the actual validator and assert its rejection',
            observed_recovery=None,review_basis=None,defect_code=None)
        self.assertEqual(result['reason'],'CONCRETE_LOCAL_REPAIR_REQUIRED')
        self.assertNotIn('prototype_review',t)
