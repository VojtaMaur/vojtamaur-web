"""Mechanism identity, generic helper reuse and independent assertion probes."""
import copy,hashlib,unittest
from pathlib import Path
from unittest.mock import patch
from metaweb_swarm.dedup import identity,resolve,merge_submission
from metaweb_swarm.prototype_components import signature,submission_issue
from metaweb_swarm.review_probe import run
from tests import test_local_contract as fixture
from tests.test_prototype_review import range_args


class IdentityTests(unittest.TestCase):
    def pointer(self,key,scope,title):
        return dict(id='IDEA-1',provider='Open Library',mechanism_key=key,mechanism_scope=scope,
            title=title,mechanism='Public bibliographic record stores a reconstructable recovery pointer',status='INVESTIGATING')
    def test_work_edition_subject_pointer_aliases_merge_with_all_contributors(self):
        a=self.pointer('openlibrary-recovery-pointer','edition-subject-record-pointer-seed','Open Library edition/subject record recovery pointer')
        b=self.pointer('bibliographic-catalog-pointer-layer','work-edition-metadata-entrypoint','Open Library work/edition record recovery pointer')
        a=merge_submission(None,a,'AGENT-1','t1');a['id']='IDEA-1'
        self.assertEqual(identity(a),identity(b));self.assertIs(resolve([a],b),a)
        merged=merge_submission(a,b,'AGENT-2','t2')
        self.assertEqual(merged['id'],'IDEA-1');self.assertEqual(merged['contributors'],['AGENT-1','AGENT-2'])
        self.assertEqual(len(merged['submissions']),2)
    def test_payload_deposit_and_other_custodian_are_not_collapsed(self):
        a=self.pointer('a','scope-a','Open Library recovery pointer')
        b=dict(a,mechanism='Upload exact EPUB file payload with independent readback',title='Open Library EPUB upload')
        c=dict(a,provider='Other Library')
        self.assertNotEqual(identity(a),identity(b));self.assertNotEqual(identity(a),identity(c))
    def test_provider_comparison_mention_is_not_forced_into_open_library(self):
        a=self.pointer('a','scope-a','Open Library recovery pointer')
        b=dict(a,provider='Other Library, compared with Open Library')
        self.assertNotEqual(identity(a),identity(b))

    def test_ast_signature_ignores_comments_and_formatting_but_not_algorithm(self):
        self.assertEqual(signature([('a.py',b'x=1 # comment\n')]),signature([('b.py',b'x = 1\n')]))
        self.assertNotEqual(signature([('a.py',b'x=1\n')]),signature([('a.py',b'x=2\n')]))


class QualityTests(unittest.IsolatedAsyncioTestCase):
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
        t=await self.captured();self.engine.state['config'].update(coding_backend='sdk_shell',independent_review_probes=True)
        return t

    async def test_helper_is_retained_without_awarding_candidate_coverage(self):
        t=await self.ready()
        result=self.review.review_prototype_test(t['id'],'HELPER_ONLY','Generic extraction helper does not exercise the assigned external record primitive',
            positive_code='encoded=base64.b64encode(data)',observed_recovery=None,review_basis=None)
        self.assertEqual(result['verdict'],'HELPER_ONLY');self.assertFalse(self.idea.get('prototype_component_tested'))
        self.assertFalse(self.idea['prototype_tested']);self.assertNotEqual(self.idea['status'],'PROTOTYPED')
        self.assertEqual(len(self.engine.state['shared_components']),1)

    async def test_approval_without_independent_probe_is_deferred(self):
        t=await self.ready();e=self.evidence(t);e.pop('recovered_path')
        result=self.review.review_prototype_test(t['id'],'SUBCOMPONENT','Actual captured local cases seem meaningful but still need independent challenge',
            observed_recovery=None,review_basis=None,**e)
        self.assertEqual(result['reason'],'INDEPENDENT_PROBE_REQUIRED');self.assertNotIn('prototype_review',t)

    async def test_reused_implementation_is_caught_before_new_capture(self):
        await self.ready()
        result=submission_issue(self.local,{'script_path':'prototype/test.py'},[],'IDEA-OTHER')
        self.assertEqual(result['reason'],'EXISTING_IMPLEMENTATION_REUSE')
        self.assertEqual(result['existing_components'][0]['idea_id'],self.idea['id'])
        result=submission_issue(self.local,{'script_path':'prototype/test.py'},[],'IDEA-OTHER')
        self.assertEqual(len(self.engine.state['prototype_component_reuses']),1)

    async def test_probe_mounts_only_fresh_private_copy_and_then_allows_judgment(self):
        t=await self.ready();original=(self.local.workspace.root/'prototype/test.py').read_bytes()
        roots=[]
        def execute(root,argv):
            roots.append(root)
            self.assertNotEqual(root,self.local.workspace.root);self.assertNotEqual(root,self.review.workspace.root)
            self.assertTrue(root.is_relative_to(self.run))
            self.assertEqual((root/'prototype/test.py').read_bytes(),original)
            self.assertEqual((root/t['prototype_plan']['input']['path']).stat().st_size,t['prototype_plan']['input']['bytes'])
            return {'status':'COMPLETED','returncode':0,'output':'independent assertions passed','cleanup_ok':True}
        with patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            executor.return_value.run.side_effect=execute
            probe=await run(self.review,t['id'],'actual=2; assert actual == 2  # mocked transport only; not scientific proof')
        self.assertEqual(probe['status'],'COMPLETED');self.assertTrue(probe['implementation_unchanged'])
        self.assertEqual((self.local.workspace.root/'prototype/test.py').read_bytes(),original)
        e=self.evidence(t);e.pop('recovered_path')
        result=self.review.review_prototype_test(t['id'],'SUBCOMPONENT','Fixture reviewer judges the actual cases; probe exit alone did not assign this verdict',
            observed_recovery=None,review_basis=None,**e)
        self.assertEqual(result['verdict'],'SUBCOMPONENT')

    async def test_failed_probe_cannot_certify_component(self):
        t=await self.ready()
        with patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            executor.return_value.run.return_value={'status':'BLOCKED','returncode':1,'output':'tampered data accepted','cleanup_ok':True}
            await run(self.review,t['id'],'raise AssertionError("tampered data accepted")')
        e=self.evidence(t);e.pop('recovered_path')
        result=self.review.review_prototype_test(t['id'],'SUBCOMPONENT','Unsupported approval must be rejected despite author exit zero',
            observed_recovery=None,review_basis=None,**e)
        self.assertEqual(result['reason'],'INDEPENDENT_PROBE_FAILED')

    async def test_modifying_captured_implementation_invalidates_probe(self):
        t=await self.ready()
        def execute(root,argv):
            (root/'prototype/test.py').write_text('print("rewritten")')
            return {'status':'COMPLETED','returncode':0,'output':'OK','cleanup_ok':True}
        with patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            executor.return_value.run.side_effect=execute
            result=await run(self.review,t['id'],'assert True  # implementation changes must invalidate this probe')
        self.assertEqual(result['reason'],'REVIEW_PROBE_MODIFIED_IMPLEMENTATION')
        self.assertFalse(result['implementation_unchanged'])

    async def test_probe_budget_and_disabled_docker_start_no_process(self):
        t=await self.ready()
        self.engine.state['config']['experiments']='disabled'
        with patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            result=await run(self.review,t['id'],'assert True  # no command permitted')
            executor.assert_not_called()
        self.assertEqual(result['reason'],'EXPERIMENTS_DISABLED')
        self.engine.state['config']['experiments']='docker'
        self.engine.state['prototype_review_probes']=[dict(test_id=t['id']) for _ in range(3)]
        with patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            result=await run(self.review,t['id'],'assert True  # no command permitted')
            executor.assert_not_called()
        self.assertEqual(result['reason'],'MAX_REVIEW_PROBES_PER_TEST')

    async def test_printed_pass_without_assertions_cannot_certify_component(self):
        t=await self.ready()
        with patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            executor.return_value.run.return_value={'status':'COMPLETED','returncode':0,'output':'PASS','cleanup_ok':True}
            probe=await run(self.review,t['id'],'print("PASS")  # printing is not an independent assertion')
        self.assertFalse(probe['assertion_syntax'])
        e=self.evidence(t);e.pop('recovered_path')
        result=self.review.review_prototype_test(t['id'],'SUBCOMPONENT','Printing passed is not an independent behavioral check',
            observed_recovery=None,review_basis=None,**e)
        self.assertEqual(result['reason'],'INDEPENDENT_PROBE_FAILED')

    async def test_failed_staging_reserves_attempt_and_bytes_without_starting_docker(self):
        t=await self.ready()
        with patch('metaweb_swarm.review_probe.Workspace',side_effect=OSError('fixture preparation failure')),patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            result=await run(self.review,t['id'],'actual=1; assert actual == 1')
            executor.assert_not_called()
        self.assertEqual(result['reason'],'REVIEW_PROBE_PREPARATION_FAILED')
        self.assertTrue(result['cleanup_ok']);self.assertGreater(result['staged_bytes'],0)
        self.assertEqual(len(self.engine.state['prototype_review_probes']),1)

    async def test_cleanup_uncertainty_stops_another_probe_without_docker(self):
        t=await self.ready()
        self.engine.state['prototype_review_probes']=[{'test_id':t['id'],'status':'UNKNOWN','cleanup_ok':False}]
        with patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            result=await run(self.review,t['id'],'actual=1; assert actual == 1')
            executor.assert_not_called()
        self.assertEqual(result['reason'],'CONTAINER_CLEANUP_UNRESOLVED')

    async def test_real_sdk_routes_probe_then_judgment_with_small_tool_set(self):
        from tests.test_backend import SDK_AVAILABLE,FakeProvider,tool_response,final_response
        if not SDK_AVAILABLE:self.skipTest('SDK optional')
        from metaweb_swarm.backend import OpenAIBackend
        t=await self.ready();e=self.evidence(t);e.pop('recovered_path')
        provider=FakeProvider([
            tool_response('run_review_probe',{'test_id':t['id'],'code':'actual=2; assert actual == 2  # fake transport test only'},ident='probe'),
            tool_response('review_prototype_test',range_args(self.review,t,dict(test_id=t['id'],verdict='SUBCOMPONENT',
                reason='Fixture scope judgment following independent mock execution; not a real scientific test',**e)),ident='review'),final_response()])
        with patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            executor.return_value.run.return_value={'status':'COMPLETED','returncode':0,'output':'mock assertions','cleanup_ok':True}
            await OpenAIBackend(provider).step(self.auditor,self.engine.prompt(self.auditor),[],self.review,self.engine.state['config'])
        first_args,first_kwargs=provider.model.calls[0]
        tools=first_kwargs.get('tools',first_args[3] if len(first_args)>3 else [])
        self.assertEqual({t.name for t in tools},{'run_review_probe','review_prototype_test'})
        self.assertEqual(t['prototype_review']['verdict'],'SUBCOMPONENT')
        self.assertEqual(len(self.engine.state['prototype_review_probes']),1)

    async def test_repeated_reuse_retains_local_attempt_without_blocking_entire_worker(self):
        await self.ready()
        from metaweb_swarm.coding_worker import bounded_submission,output
        self.local.agent['coding_last_result']={'status':'DEFERRED','reason':'EXISTING_IMPLEMENTATION_REUSE'}
        current={'idea_id':self.idea['id']}
        for _ in range(2):
            result=bounded_submission(self.local,current,output('CONTINUE','Implement the candidate primitive'))
            self.assertEqual(result['status'],'CONTINUE')
        result=bounded_submission(self.local,current,output('CONTINUE','Implement the candidate primitive'))
        self.assertEqual(result['status'],'COMPLETED')
        block=self.local.agent['research_task_blocks'][-1]
        self.assertEqual(block['status'],'LIMIT_REACHED')
        self.assertEqual(block['reason'],'NO_NEW_IMPLEMENTATION_WITHIN_LOCAL_ATTEMPTS')
        self.assertNotEqual(self.idea['status'],'REJECTED')

    async def test_snapshot_budget_is_checked_before_loading_or_copying_artifacts(self):
        t=await self.ready();self.engine.state['config']['max_snapshot_bytes']=1
        with patch('metaweb_swarm.prototype_review.artifact_bytes',side_effect=AssertionError('must not load')) as read,patch('metaweb_swarm.review_probe.DockerExecutor') as executor:
            result=await run(self.review,t['id'],'actual=1; assert actual == 1')
            read.assert_not_called();executor.assert_not_called()
        self.assertEqual(result['reason'],'MAX_REVIEW_PROBE_BYTES')
