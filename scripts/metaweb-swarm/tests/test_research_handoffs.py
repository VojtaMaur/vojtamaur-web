"""Broad research must hand off real ideas, not an empty deposit-only packet."""
import copy
import json
import unittest
from unittest.mock import patch
from metaweb_swarm.demo import DemoBackend
from metaweb_swarm.engine import Engine
from metaweb_swarm.research_tasks import assign, packet, complete, recover, revision
from metaweb_swarm.review_tasks import assign as assign_review
from metaweb_swarm.review_contract import complete_review
from metaweb_swarm.config import load_config, validate_config
from tests import test_focused_tasking as fixture
from tests.test_backend import SDK_AVAILABLE, FINAL


class ResearchHandoffTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.FocusedTests.setUp
    tearDown = fixture.FocusedTests.tearDown
    for_agent = fixture.FocusedTests.for_agent

    def prepare(self, two=False):
        self.engine.state['config'].update(task_style='research', research_handoffs=True,
            require_deposit_qualification=False, require_independent_http_review=False,
            experiments='docker', semantic_dedupe=False, prompt_chars=20000)
        self.auditor = self.engine.state['agents'][1]
        self.proto = self.engine.state['agents'][2]
        self.reporter = self.engine.state['agents'][3]
        self.review = self.for_agent(self.auditor)
        self.local = self.for_agent(self.proto)
        self.idea = self.api.submit_idea(DemoBackend.idea('Current format claim', 'format-one', 'FREE', 'DISCOVERED'))
        if two:
            self.other = self.api.submit_idea(DemoBackend.idea('Other current claim', 'format-two', 'FREE', 'DISCOVERED'))
        assign_review(self.engine, self.auditor)
        assign(self.engine, self.proto)

    def normalized(self):
        return dict(FINAL, unexplored_leads=[], handoff_leads=[])

    def test_auditor_gets_actual_unqualified_ideas_and_cannot_skip_receipts(self):
        self.prepare(two=True)
        task = self.review.get_review_task()
        self.assertEqual(task['kind'], 'RESEARCH_IDEA')
        self.assertEqual(task['target_id'], self.idea['id'])
        result, _ = complete_review(self.engine.state, self.auditor, FINAL, self.normalized())
        self.assertEqual(result['status'], 'CONTINUE')
        wrong = self.review.record_critique(self.other['id'], 'REVISE', 'Insufficient evidence for the other claim')
        self.assertEqual(wrong['reason'], 'ASSIGNED_CURRENT_REVIEW_REQUIRED')
        critique = self.review.record_critique(self.idea['id'], 'REVISE', 'No primary evidence or actual functional test is present')
        self.assertEqual(critique['research_revision'], revision(self.idea))
        result, _ = complete_review(self.engine.state, self.auditor, FINAL, self.normalized())
        self.assertEqual(result['status'], 'CONTINUE')
        assign_review(self.engine, self.auditor)
        self.assertEqual(self.review.get_review_task()['target_id'], self.other['id'])
        self.review.record_critique(self.other['id'], 'REJECT', 'No deployment has been executed yet')
        self.assertNotEqual(self.other['status'], 'REJECTED')
        result, _ = complete_review(self.engine.state, self.auditor, FINAL, self.normalized())
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertFalse(self.engine.state.get('deposit_qualifications'))

    async def test_pass_needs_own_actual_cited_sources_not_another_agents_search(self):
        self.prepare()
        self.idea['evidence'] = [{'url': self.origin+'/docs', 'claim': 'API capability', 'verified':False}]
        assign_review(self.engine, self.auditor)
        result = self.review.record_critique(self.idea['id'], 'PASS', 'Capability appears supported by the source')
        self.assertEqual(result['reason'], 'RESEARCH_PRIMARY_EVIDENCE_REQUIRED')
        await self.review.read_document(self.origin+'/docs', 'Independently inspect the cited source')
        self.assertEqual(self.review.record_critique(self.idea['id'], 'PASS', 'Read capability; local assertions still need separate testing')['verdict'], 'PASS')
        self.assertFalse(self.idea['prototype_tested'])
        self.assertFalse(self.engine.state['external_actions'])

    async def test_unlinked_or_wrong_id_never_starts_docker_and_exit_zero_is_unfinished(self):
        self.prepare()
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            for ident in ('', 'IDEA-0003'):
                result = await self.local.run_experiment(['python', '-c', "print('prototype pending')"], ident)
                self.assertEqual(result['reason'], 'ASSIGNED_CURRENT_IDEA_REQUIRED')
            docker.assert_not_called()
            docker.return_value.run.return_value = {'status':'COMPLETED','exit_code':0,'stdout':'prototype pending'}
            result = await self.local.run_experiment(['python', '-c', "print('prototype pending')"], self.idea['id'])
        self.assertEqual(result['reason'], 'PROTOTYPE_PLAN_REQUIRED')
        output = complete(self.engine.state, self.proto, self.normalized())
        self.assertEqual(output['status'], 'CONTINUE')
        self.assertFalse(self.idea['prototype_tested'])
        with self.assertRaises(ValueError):
            self.local.record_test(self.idea['id'], 'EXPERIMENT-NONE', 'Exit-zero placeholder proves nothing')

    async def test_registered_artifacts_preserve_provenance_and_allow_linked_test(self):
        self.prepare(two=True)
        self.api.workspace.write_file('original.txt', 'original discovery artifact')
        self.api.register_idea_artifacts(self.idea['id'], ['original.txt'])
        original = copy.deepcopy(self.idea['artifact_checks'])
        author = self.idea['agent_id']
        self.local.materialize_export('build.epub', 'exports/input.epub')
        self.local.workspace.write_file('prototype/test.py', 'assert decoder(encoder(payload)) == payload\n')
        self.local.workspace.write_file('prototype/specimen.bin', b'enc:actual public export bytes')
        self.local.register_idea_artifacts(self.idea['id'], ['prototype/test.py', 'prototype/specimen.bin'])
        self.assertEqual(self.idea['agent_id'], author)
        self.assertTrue(all(c in self.idea['artifact_checks'] for c in original))
        self.local.record_prototype_plan(self.idea['id'],'Recover real export bytes with the proposed format','exports/input.epub',
            'prototype/test.py',['prototype/specimen.bin'],'Decode the encoding and compare actual original bytes','Tampered payload must fail hash verification','FULL_MECHANISM','')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            def mock_run(*args):
                self.local.workspace.write_file('prototype/specimen.bin',b'generated mock transport specimen')
                return {'status':'COMPLETED','exit_code':0,'stdout':'mock assertion execution'}
            docker.return_value.run.side_effect = mock_run
            experiment = await self.local.run_experiment(['python', 'prototype/test.py'], self.idea['id'])
        test = self.local.record_test(self.idea['id'], experiment['experiment_id'], 'Mock transport regression; actual test assertions remain subject to review')
        self.assertTrue(test['host_execution_verified'])
        self.assertNotEqual(self.idea['status'], 'PROTOTYPED')
        self.assertTrue(test['prototype_review_required'])
        self.assertEqual(complete(self.engine.state, self.proto, self.normalized())['status'], 'CONTINUE')
        assign(self.engine, self.proto)
        self.assertEqual(packet(self.engine.state, self.proto)['target_id'], self.other['id'])
        self.local.record_research_blocker(self.other['id'], 'Required system decoder is unavailable inside this container')
        self.assertEqual(complete(self.engine.state, self.proto, self.normalized())['status'], 'BLOCKED')
        self.assertNotEqual(self.other['status'], 'REJECTED')
        self.assertEqual(len(self.engine.state['tests']), 1)

    def test_registration_is_atomic_and_cannot_escape_or_change_claim(self):
        self.prepare()
        self.local.workspace.write_file('test.txt', 'safe known file')
        before = copy.deepcopy(self.idea)
        with self.assertRaises(ValueError):
            self.local.register_idea_artifacts(self.idea['id'], ['test.txt', '../escape.txt'])
        self.assertEqual(before, self.idea)
        self.assertEqual(self.local.register_idea_artifacts('IDEA-0003', ['test.txt'])['reason'], 'ASSIGNED_CURRENT_IDEA_REQUIRED')
        self.assertNotIn('Do not call get_review_task.', self.engine.prompt(self.proto))
        self.assertIn('Prototype ONLY the assigned current IDEA', self.engine.prompt(self.proto))

    def test_report_packet_and_prompt_exclude_prior_run_as_active_candidate(self):
        self.prepare()
        self.engine.prior_candidates = [{'id':'IDEA-0007','title':'OLD GOOGLE DRIVE CLAIM','run_id':'previous'}]
        prompt = self.engine.prompt(self.reporter)
        self.assertIn(self.idea['id'], prompt)
        self.assertNotIn('OLD GOOGLE DRIVE CLAIM', prompt)
        self.assertLess(len(prompt), 20000)
        self.assertEqual(complete(self.engine.state, self.reporter, self.normalized())['status'], 'CONTINUE')
        task = self.for_agent(self.reporter).get_research_task()
        self.assertEqual([i['id'] for i in task['ideas']], [self.idea['id']])
        self.assertEqual(task['tests'], [])
        self.for_agent(self.reporter).record_research_report([self.idea['id']],
            'Current candidate remains an untested hypothesis; no deposit or recorded test exists.',
            ['Primary sources and actual mechanism assertions remain unverified'])
        self.assertEqual(complete(self.engine.state, self.reporter, self.normalized())['status'], 'COMPLETED')
        self.reporter.update(status='COMPLETED', rounds=1)
        self.engine.state['experiments'].append({'experiment_id':'new','idea_id':self.idea['id']})
        recover(self.engine)
        self.assertEqual(self.reporter['status'], 'PENDING')

    def test_checkpoint_keeps_assignment_blocker_and_no_unbounded_auto_retry(self):
        self.prepare()
        self.local.record_research_blocker(self.idea['id'], 'Required native dependency is missing in Docker')
        self.engine.close()
        self.engine = Engine(self.run, DemoBackend(), 'demo')
        proto = self.engine.state['agents'][2]
        self.assertEqual(proto['research_assignment']['target_id'], self.idea['id'])
        proto.update(status='COMPLETED', rounds=1)
        recover(self.engine)
        self.assertEqual(proto['status'], 'COMPLETED')
        proto['operator_notes'] = ['Native dependency installed in updated container']
        recover(self.engine)
        self.assertEqual(proto['status'], 'PENDING')
        self.engine.store.verify()

    def test_fresh_profile_enables_handoffs_but_preserves_permissions_and_limits(self):
        from metaweb_swarm.roles import seed_agents
        from pathlib import Path
        config = load_config(Path(__file__).resolve().parents[1]/'config.http.json')
        self.assertTrue(config['research_handoffs'])
        self.assertFalse(config['require_deposit_qualification'])
        self.assertTrue(config['approval_required'])
        self.assertEqual(config['max_steps'], 40)
        roster = seed_agents(config)
        auditor = next(a for a in roster if a['role']=='Evidence Auditor')
        proto = next(a for a in roster if a['role']=='Prototyper')
        reporter = next(a for a in roster if a['work_kind']=='SYNTHESIS')
        self.assertLess(auditor['phase'], proto['phase'])
        self.assertLess(proto['phase'], reporter['phase'])
        config['research_handoffs'] = 'yes'
        with self.assertRaises(ValueError): validate_config(config)

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK optional')
    async def test_real_sdk_broad_audit_stores_receipt_instead_of_false_empty_completion(self):
        import agents
        from metaweb_swarm.backend import OpenAIBackend, _make_sdk_tools
        from tests.test_backend import FakeProvider, tool_response, final_response
        self.prepare()
        tools, _ = _make_sdk_tools(agents, self.review)
        names = {t.name for t in tools}
        self.assertIn('get_review_task', names)
        self.assertNotIn('submit_idea', names)
        self.assertNotIn('record_discovery_lead', names)
        provider = FakeProvider([
            tool_response('get_review_task', {}, ident='actual-packet'),
            tool_response('record_critique', {'idea_id':self.idea['id'], 'verdict':'REVISE',
                'reason':'Missing independent primary evidence and functional assertions',
                'decision_basis':'EVIDENCE_GAP','failure_kind':'NONE','failure_fact':'','negative_evidence_urls':[]}, ident='review'),
            final_response(output=FINAL)])
        self.engine.backend = OpenAIBackend(provider)
        await self.engine.step(self.auditor)
        self.assertEqual(self.auditor['status'], 'COMPLETED')
        self.assertEqual(self.idea['critique']['verdict'], 'REVISE')
        for a in (self.agent, self.proto, self.reporter):
            names = {t.name for t in _make_sdk_tools(agents, self.for_agent(a))[0]}
            self.assertNotIn('get_review_task', names)
        names = {t.name for t in _make_sdk_tools(agents, self.local)[0]}
        self.assertIn('register_idea_artifacts', names)
        self.assertIn('submit_idea', names)
        proposal = DemoBackend.idea('Unassigned invented candidate', 'new-claim', 'FREE', 'DISCOVERED')
        self.assertEqual(self.local.submit_idea(proposal)['reason'], 'ASSIGNED_CURRENT_IDEA_REQUIRED')
        self.assertEqual(len(self.engine.state['ideas']), 1)
