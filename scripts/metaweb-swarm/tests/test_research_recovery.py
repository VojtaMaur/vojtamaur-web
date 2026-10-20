"""Replay the observed cheap-model mistakes without inference/public deposits."""
import copy
import json
import unittest
from pathlib import Path
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine
from metaweb_swarm.research_tasks import assign as assign_local, complete, recover, packet
from metaweb_swarm.review_tasks import assign as assign_review, complete as complete_review
from metaweb_swarm.research_recovery import evidence_gap, input_hint
from tests import test_research_handoffs as fixture
from tests.test_backend import SDK_AVAILABLE, FINAL


class ResearchRecoveryTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.ResearchHandoffTests.setUp
    tearDown = fixture.ResearchHandoffTests.tearDown
    for_agent = fixture.ResearchHandoffTests.for_agent
    prepare = fixture.ResearchHandoffTests.prepare
    normalized = fixture.ResearchHandoffTests.normalized

    def plan(self, input_path='missing.epub', script_path='prototype/test.py'):
        return self.local.record_prototype_plan(self.idea['id'], 'Recover exact retained bytes and check digest',
            input_path, script_path, ['prototype/result.bin'], 'Recovered export equals the original bytes',
            'Modified decoded bytes fail the original digest comparison', 'SUBCOMPONENT',
            'Local encoding only; public storage is not exercised')

    def pass_review(self):
        return self.review.record_critique(self.idea['id'], 'PASS', 'Primary documentation supports a local research hypothesis',
                                          decision_basis='EVIDENCE_GAP')

    async def test_missing_sources_are_exact_own_reads_required_and_can_be_revised(self):
        self.prepare(two=True)
        self.idea['evidence'] = [{'url':self.origin+'/docs'}, {'url':self.origin+'/terms'}]
        assign_review(self.engine, self.auditor)
        await self.api.read_document(self.origin+'/terms', 'Another agent reading does not certify the auditor')
        await self.review.read_document(self.origin+'/docs', 'Read the first independent primary source')
        result = self.pass_review()
        self.assertEqual([d['url'] for d in result['details']['missing_documents']], [self.origin+'/terms'])
        self.assertEqual(packet(self.engine.state, self.auditor)['missing_documents'], result['details']['missing_documents'])
        self.review.record_critique(self.idea['id'], 'REVISE', 'Terms still unread; preserve the candidate as an evidence gap', decision_basis='EVIDENCE_GAP')
        self.assertFalse(self.auditor['research_repairs'])
        assign_review(self.engine, self.auditor)
        self.assertEqual(self.auditor['review_assignment']['target_id'], self.other['id'])
        self.assertNotEqual(self.idea['status'], 'REJECTED')

    async def test_only_observed_own_redirects_satisfy_original_citation(self):
        self.prepare()
        self.idea['evidence'] = [{'url': self.origin+'/redirect#section'}]
        assign_review(self.engine, self.auditor)
        await self.review.read_document(self.origin+'/docs', 'Read canonical page but no redirect observed')
        self.assertEqual(len(evidence_gap(self.auditor, self.idea)['missing_documents']), 1)
        redirect = await self.review.read_document(self.origin+'/redirect', 'Observe the actual citation redirect')
        self.assertEqual(redirect['redirect_url'], self.origin+'/docs')
        self.assertEqual(self.pass_review()['verdict'], 'PASS')
        self.assertFalse(self.idea['prototype_tested'])

    async def test_url_slash_or_query_is_not_an_inferred_redirect(self):
        self.prepare()
        self.idea['evidence'] = [{'url': self.origin+'/docs/'}, {'url': self.origin+'/docs?v=2'}]
        assign_review(self.engine, self.auditor)
        await self.review.read_document(self.origin+'/docs', 'Observe only the original document URL')
        self.assertEqual(len(evidence_gap(self.auditor, self.idea)['missing_documents']), 2)

    async def test_identical_pass_retries_are_bounded_without_automatic_verdict(self):
        self.prepare(two=True)
        self.idea['evidence'] = [{'url': self.origin+'/docs'}, {'url': self.origin+'/terms'}]
        assign_review(self.engine, self.auditor)
        for n in range(3):
            await self.review.read_document(self.origin+'/docs', 'Repeating the same source does not resolve terms')
            result = self.pass_review()
            self.assertEqual(result['same_attempts'], n+1)
        self.assertEqual(result['reason'], 'RESEARCH_REPAIR_STALLED')
        self.assertNotIn('critique', self.idea)
        self.assertEqual(self.engine.state['tests'], [])
        self.assertEqual(complete_review(self.engine.state, self.auditor, self.normalized())[0]['status'], 'CONTINUE')
        assign_review(self.engine, self.auditor)
        self.assertEqual(self.auditor['review_assignment']['target_id'], self.other['id'])
        self.review.record_critique(self.other['id'], 'REVISE', 'Keep this unsupported hypothesis for later evidence')
        finished = complete_review(self.engine.state, self.auditor, self.normalized())[0]
        self.assertEqual(finished['status'], 'BLOCKED')
        self.auditor.update(finished, rounds=2)
        recover(self.engine)
        self.assertEqual(self.auditor['status'], 'BLOCKED')
        self.auditor['operator_notes'] = ['Review the missing primary terms source again']
        recover(self.engine)
        self.assertEqual(self.auditor['status'], 'PENDING')

    async def test_real_evidence_progress_resets_repair_attempts(self):
        self.prepare()
        self.idea['evidence'] = [{'url': self.origin+'/docs'}, {'url': self.origin+'/terms'}]
        assign_review(self.engine, self.auditor)
        self.pass_review(); self.pass_review()
        await self.review.read_document(self.origin+'/docs', 'Make concrete progress on the required source set')
        self.assertEqual(self.pass_review()['same_attempts'], 1)
        await self.review.read_document(self.origin+'/terms', 'Complete independent source reads')
        self.assertEqual(self.pass_review()['verdict'], 'PASS')

    def test_wrong_path_reports_actual_materialized_input_and_correct_plan_recovers(self):
        self.prepare()
        self.local.materialize_export('build.epub', 'actual/input.epub')
        self.local.write_file('prototype/test.py', "from pathlib import Path\ndata=Path('actual/input.epub').read_bytes()\nassert data\n")
        result = self.plan('build.epub')
        self.assertEqual(result['status'], 'DEFERRED')
        self.assertEqual(result['reason'], 'PROTOTYPE_INPUT_PATH_MISSING')
        self.assertEqual(result['details']['materialized_inputs'][0]['path'], 'actual/input.epub')
        output = dict(self.normalized(), status='BLOCKED', reason_for_stopping='Mistakenly treat wrong path as host failure')
        self.assertEqual(complete(self.engine.state, self.proto, output)['status'], 'CONTINUE')
        good = self.plan('actual/input.epub')
        self.assertEqual(good['input']['path'], 'actual/input.epub')
        self.assertFalse(self.proto['research_repairs'])
        self.assertEqual(self.engine.state['experiments'], [])
        self.assertEqual(self.engine.state['tests'], [])

    def test_missing_script_is_data_repair_but_unsafe_paths_still_refused(self):
        self.prepare()
        self.local.materialize_export('build.epub', 'actual/input.epub')
        result = self.plan('actual/input.epub')
        self.assertEqual(result['reason'], 'PROTOTYPE_SCRIPT_PATH_MISSING')
        with self.assertRaises(ValueError): self.plan('../escape')
        self.assertFalse(self.engine.state['experiments'])

    def test_repeated_wrong_path_moves_to_next_idea_and_same_materialization_not_progress(self):
        self.prepare(two=True)
        for n in range(3):
            self.local.materialize_export('build.epub', 'actual/input.epub')
            self.assertEqual(self.plan()['same_attempts'], n+1)
        result = complete(self.engine.state, self.proto, dict(self.normalized(), status='BLOCKED'))
        self.assertEqual(result['status'], 'CONTINUE')
        assign_local(self.engine, self.proto)
        self.assertEqual(self.proto['research_assignment']['target_id'], self.other['id'])
        self.local.record_research_blocker(self.other['id'], 'System-level decoder unavailable in this Docker image')
        self.assertEqual(complete(self.engine.state, self.proto, self.normalized())['status'], 'BLOCKED')
        self.assertNotEqual(self.idea['status'], 'REJECTED')

    def test_stalled_repair_survives_checkpoint_and_report_without_changing_limits(self):
        self.prepare()
        config = copy.deepcopy(self.engine.state['config'])
        for _ in range(3): self.plan()
        self.engine.close()
        self.engine = Engine(self.run, DemoBackend(), 'demo')
        self.proto = self.engine.state['agents'][2]
        self.assertEqual(config, self.engine.state['config'])
        self.assertEqual(self.proto['research_task_blocks'][0]['same_attempts'], 3)
        from metaweb_swarm.reporting import generate_reports
        generate_reports(self.run, self.engine.state)
        self.assertIn('PROTOTYPE_INPUT_PATH_MISSING', (self.run/'SWARM_REPORT.md').read_text(encoding='utf-8'))
        manifest = json.loads((self.run/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['agents'][2]['research_task_blocks'][0]['phase'], 'LOCAL')
        self.engine.store.verify()

    def test_json_format_hint_and_only_rejected_data_pairs_are_archived(self):
        self.assertIn('json.loads', input_hint('manifest.json', 'input.json')['format_hint'])
        from metaweb_swarm.memory import obsolete_planning_pairs, compact_history
        history = []
        for name, status, reason in [('record_prototype_plan','DEFERRED','PROTOTYPE_INPUT_PATH_MISSING'),
                                     ('record_critique','DEFERRED','RESEARCH_PRIMARY_EVIDENCE_REQUIRED'),
                                     ('http_request','UNKNOWN','PROTOTYPE_INPUT_PATH_MISSING'),
                                     ('run_experiment','BLOCKED','PROTOTYPE_INPUT_PATH_MISSING')]:
            history += [{'type':'function_call','call_id':name,'name':name,'arguments':'{}'},
                        {'type':'function_call_output','call_id':name,'output':json.dumps({'status':status,'reason':reason})}]
        self.assertEqual(obsolete_planning_pairs(history), {'record_prototype_plan','record_critique'})
        compact = compact_history(history, 'raw/history.json', 20000)
        self.assertEqual({r.get('call_id') for r in compact if r.get('call_id')}, {'http_request','run_experiment'})

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK optional')
    async def test_actual_sdk_wrong_path_is_recoverable_and_upload_edit_not_offered(self):
        import agents
        from metaweb_swarm.backend import OpenAIBackend, _make_sdk_tools
        from tests.test_backend import FakeProvider, tool_response, final_response
        self.prepare()
        names = {t.name for t in _make_sdk_tools(agents, self.local)[0]}
        self.assertIn('record_prototype_plan', names)
        for name in ('edit_deposit_plan_step','read_deposit_plan_draft','bind_deposit_step_response'):
            self.assertNotIn(name, names)
        self.assertIn('http_request', names)
        self.assertIn('execute_deposit_plan', names)
        self.proto['deposit_plan_draft']={'idea_id':self.idea['id']}
        self.assertIn('edit_deposit_plan_step', {t.name for t in _make_sdk_tools(agents, self.local)[0]})
        self.proto.pop('deposit_plan_draft')
        args = dict(idea_id=self.idea['id'], property_tested='Recover the real bytes of a retained public export',
                    input_path='original.epub', script_path='prototype/test.py', output_paths=['prototype/result.bin'],
                    positive_assertion='Decode the original bytes and compare their digest', negative_assertion='Reject corrupted decoded bytes',
                    scope='SUBCOMPONENT', limitations='Does not test real remote publication or retention')
        provider = FakeProvider([tool_response('record_prototype_plan', args),
                                 final_response(output=dict(FINAL,status='BLOCKED',reason_for_stopping='Wrong file path'))])
        self.engine.backend = OpenAIBackend(provider)
        await self.engine.step(self.proto)
        self.assertEqual(self.proto['status'], 'PENDING')
        self.assertEqual(self.proto['research_repairs']['LOCAL']['reason'], 'PROTOTYPE_INPUT_PATH_MISSING')
        self.assertFalse(self.engine.state['experiments'])
        self.assertFalse(self.engine.state['external_actions'])
        # The general external phase keeps its tools after the local assignment.
        self.proto['research_assignment'] = {'kind':'NONE'}
        self.assertIn('execute_deposit_plan', {t.name for t in _make_sdk_tools(agents, self.local)[0]})
