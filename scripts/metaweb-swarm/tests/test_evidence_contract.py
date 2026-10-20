"""Observed false-positive reviews and discovery loops; no provider inference."""
import hashlib
import unittest
from unittest.mock import patch
from metaweb_swarm.baseline import delegation_rejection
from metaweb_swarm.discovery_pivot import complete as finish_discovery
from metaweb_swarm.prototype_evidence import code_case, artifact_facts
from metaweb_swarm.research_tasks import prepare_task_context
from metaweb_swarm.review_tasks import assign as assign_review
from tests import test_prototype_review as fixture


class EvidenceContractTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.PrototypeScopeTests.setUp
    tearDown=fixture.PrototypeScopeTests.tearDown
    for_agent=fixture.PrototypeScopeTests.for_agent
    prepare=fixture.PrototypeScopeTests.prepare
    plan=fixture.PrototypeScopeTests.plan
    artifacts=fixture.PrototypeScopeTests.artifacts
    executed=fixture.PrototypeScopeTests.executed
    evidence=fixture.PrototypeScopeTests.evidence

    async def with_report(self, report='round_trip=True\n', bad_copy=False):
        self.artifacts()
        self.local.record_prototype_plan(self.idea['id'],'Recover exact original bytes and detect altered payload',
            'exports/input.epub','prototype/test.py',
            ['prototype/specimen.bin','prototype/recovered.bin','prototype/report.txt'],
            'Decoded bytes must equal retained input','Deliberately altered bytes must fail digest comparison','FULL_MECHANISM','')
        self.review.record_critique(self.idea['id'],'REVISE','Execute and inspect the actual byte recovery and negative cases first')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            def execute(*args):
                original=(self.local.workspace.root/'exports/input.epub').read_bytes()
                self.local.workspace.write_file('prototype/specimen.bin',b'generated simulated encoding')
                self.local.workspace.write_file('prototype/recovered.bin',original+b'\n' if bad_copy else original)
                self.local.workspace.write_file('prototype/report.txt',report)
                return {'status':'COMPLETED','returncode':0,'output':'mock transport; assertions are fixture data'}
            docker.return_value.run.side_effect=execute
            experiment=await self.local.run_experiment(['python','prototype/test.py'],self.idea['id'])
        test=self.local.record_test(self.idea['id'],experiment['experiment_id'],'Captured output fixture for validation contract')
        assign_review(self.engine,self.auditor)
        return test

    def test_natural_exclusions_still_refuse_positive_or_exception_tasks(self):
        rules=[{'id':'BAN','aliases':['WACZ','WARCZ'],'reason':'Owner excludes this direction'}]
        for phrase in ('Which services, not WACZ, work?','Exclude WACZ and any recurring subscription dependency.',
                       'Find alternatives without WACZ.','Investigate non-WACZ formats.'):
            self.assertIsNone(delegation_rejection({'role':'Scout','mission':phrase},rules))
        for phrase in ('Use WACZ.','Not only WACZ but other formats too.',
                       'Exclude WACZ unless it is useful.','Services not WACZ unless useful.',
                       'Use non-WACZ formats unless it is useful.','Services not WACZ (unless useful).',
                       'Find non-WACZ alternatives, then implement WARCZ.'):
            self.assertIsNotNone(delegation_rejection({'role':'Scout','mission':phrase},rules))

    def test_prefix_and_printed_labels_are_not_negative_case_evidence(self):
        prefix="first_chunk=body.split(b'\\n',1)[0]\nassert body.startswith(first_chunk)\n"
        self.assertFalse(code_case(prefix,prefix,True))
        self.assertFalse(code_case("print('NEGATIVE_CHECKS')\n","print('NEGATIVE_CHECKS')",True))
        self.assertFalse(code_case('assert 1+1==2\n','assert 1+1==2',True))
        self.assertFalse(code_case('assert data==decoded\n','assert missing==decoded'))
        self.assertTrue(code_case("bad=data+b'!'\nassert digest(bad)!=digest(data)\n",
                                  "bad=data+b'!'\nassert digest(bad)!=digest(data)",True))

    async def test_script_only_read_cannot_approve_without_actual_output_reads(self):
        test=await self.executed()
        self.review.read_test_artifact(test['id'],'prototype/test.py')
        result=self.review.review_prototype_test(test['id'],'SUBCOMPONENT','Claimed partial success before inspecting actual outputs',
            positive_code='assert data==decoded',
            negative_code="assert hashlib.sha256(decoded+b'!').digest()!=hashlib.sha256(data).digest()")
        self.assertEqual(result['reason'],'OWN_TEST_OUTPUT_READ_REQUIRED')
        self.assertFalse(self.engine.state.get('prototype_reviews'))

    async def test_reported_failed_recovery_probe_prevents_positive_review(self):
        test=await self.with_report('recovery_probe=False\nnegative_test=truncated_body_rejected=True\n')
        evidence=self.evidence(test)
        result=self.review.review_prototype_test(test['id'],'SUBCOMPONENT','Other packaging fields exist but probe failed',**evidence)
        self.assertEqual(result['reason'],'OBSERVED_PROTOTYPE_FAILURE')
        self.assertEqual(result['failures'][0]['flags'],['recovery_probe=False'])
        self.assertFalse(self.idea.get('prototype_component_tested'))
    async def test_json_failure_flag_does_not_confuse_unrelated_false_metadata(self):
        test=await self.with_report('{"round_trip": false, "unrelated_metadata": false}')
        facts=artifact_facts(self.review,test)
        report=next(a for a in facts['artifacts'] if a['path']=='prototype/report.txt')
        self.assertEqual(report['failed_positive_probes'],['round_trip=False'])

    async def test_repeated_unsupported_approval_becomes_revise_not_false_component(self):
        test=await self.executed()
        self.evidence(test)
        for _ in range(2):
            result=self.review.review_prototype_test(test['id'],'SUBCOMPONENT','Meaningful assertions claimed without actual executable cases')
            self.assertEqual(result['reason'],'ACTUAL_TEST_CASE_EVIDENCE_REQUIRED')
        final=self.review.review_prototype_test(test['id'],'SUBCOMPONENT','Same unsupported claim for the third time')
        self.assertEqual(final['verdict'],'REVISE')
        self.assertEqual(final['requested_verdict'],'SUBCOMPONENT')
        self.assertFalse(self.idea.get('prototype_component_tested'))
        self.assertNotEqual(self.idea['status'],'REJECTED')
        self.assertEqual(test['prototype_review']['verdict'],'REVISE')

    async def test_recovered_copy_must_match_raw_input_length_and_hash(self):
        test=await self.with_report(bad_copy=True)
        evidence=self.evidence(test)
        result=self.review.review_prototype_test(test['id'],'FULL_MECHANISM','Claims exact copy despite altered newline bytes',**evidence)
        self.assertEqual(result['reason'],'RECOVERED_BYTES_DO_NOT_MATCH')
        fact=next(a for a in artifact_facts(self.review,test)['artifacts'] if a['path']=='prototype/recovered.bin')
        self.assertFalse(fact['matches_retained_input'])
        self.assertFalse(self.idea['prototype_tested'])

    async def test_full_scope_requires_emitted_original_byte_artifact(self):
        test=await self.executed()
        evidence=self.evidence(test,recovered=False)
        result=self.review.review_prototype_test(test['id'],'FULL_MECHANISM','Round-trip code is not enough without recovered output identity',**evidence)
        self.assertEqual(result['reason'],'RECOVERED_BYTES_REQUIRED')
        full=self.review.review_prototype_test(test['id'],'FULL_MECHANISM','Actual input-matching recovered artifact and quoted cases',**self.evidence(test))
        self.assertEqual(full['verdict'],'FULL_MECHANISM')

    async def test_revise_cannot_trigger_identical_code_rerun(self):
        test=await self.executed()
        self.review.review_prototype_test(test['id'],'REVISE','Negative case needs a real altered encoded input and decoder rejection')
        with patch('metaweb_swarm.engine.DockerExecutor') as executor:
            result=await self.local.run_experiment(['python','prototype/test.py'],self.idea['id'])
            self.assertEqual(result['reason'],'REVISED_TEST_NEEDS_CODE_CHANGE')
            executor.assert_not_called()

    async def test_known_direction_note_is_not_completed_discovery_and_new_source_clears_pivot(self):
        self.prepare()
        self.engine.baseline.documents.append({'path':'snapshot/public/ARCHIVE.txt','sha256':'baseline-fixture',
            'lines':['ARCHIVAL COPIES AND DISTRIBUTIONS:', '  Zenodo', '    https://zenodo.org/records/123']})
        data={'title':'Zenodo repeat','mechanism':'Known provider storage','provider':'Zenodo'}
        result=self.api.submit_idea(data)
        self.assertEqual(result['reason'],'EXISTING_ARCHIVE_LAYER')
        self.api.note('I will try another family later')
        output=finish_discovery(self.engine.state,self.agent,
            {'status':'COMPLETED','unexplored_leads':[],'handoff_leads':[]})
        self.assertEqual(output['status'],'CONTINUE')
        self.assertEqual(output['reason_for_stopping'],'KNOWN_LAYER_PIVOT_PENDING')
        await self.api.read_document(self.origin+'/docs','Inspect actual primary documentation of a different fixture carrier')
        self.assertNotIn('discovery_pivot',self.agent)
        self.assertEqual(self.agent['known_discovery_directions'],['Zenodo'])

    def test_pivot_reset_preserves_history_archive_and_unknown_action(self):
        self.prepare()
        self.agent['rounds']=1
        prepare_task_context(self.engine,self.agent,self.api.workspace)
        self.agent['history']=[{'role':'user','content':'Old repeated known-provider plan'}]
        self.engine.state.setdefault('http_requests',[]).append({'id':'UNKNOWN','status':'UNKNOWN'})
        self.api.event('known_candidate_deferred',{'provider':'Known layer'})
        self.agent['rounds']=2
        prepare_task_context(self.engine,self.agent,self.api.workspace)
        self.assertEqual(self.agent['history'],[])
        self.assertTrue((self.run/'raw'/f"{self.agent['id']}-task-history-before-round-2.json").is_file())
        self.assertEqual(self.engine.state['http_requests'][-1]['status'],'UNKNOWN')
        self.assertEqual(self.api.get_research_task()['current_pivot']['provider'],'Known layer')
