"""Exit-zero REVISE handoffs and bounded progress, with the actual SDK offline."""
import copy
import json
import unittest
from unittest.mock import patch
from metaweb_swarm.prototype_revision import begin, finish
from metaweb_swarm.research_tasks import assign, local_candidates, prepare_task_context, complete
from metaweb_swarm.review_dispatch import action
from metaweb_swarm.backend import OpenAIBackend
from tests.test_backend import SDK_AVAILABLE
from tests import test_prototype_review as fixture


class PrototypeRevisionTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.PrototypeScopeTests.setUp
    tearDown = fixture.PrototypeScopeTests.tearDown
    for_agent = fixture.PrototypeScopeTests.for_agent
    prepare = fixture.PrototypeScopeTests.prepare
    plan = fixture.PrototypeScopeTests.plan
    artifacts = fixture.PrototypeScopeTests.artifacts
    executed = fixture.PrototypeScopeTests.executed

    async def revised(self):
        test = await self.executed()
        self.review.review_prototype_test(test['id'], 'REVISE',
            'The script encodes in memory but must read the saved specimen and reject corrupt saved bytes')
        self.proto.update(status='PENDING', rounds=1)
        return test

    async def test_revision_context_archives_old_success_and_forces_frozen_read(self):
        test = await self.revised()
        self.proto['history'] = [{'role': 'assistant', 'content': 'Old receipt already means complete'}]
        prepare_task_context(self.engine, self.proto, self.local.workspace)
        self.assertEqual(self.proto['history'], [])
        self.assertIn('LOCAL_REVISION', self.proto['active_task_key'])
        self.assertTrue((self.run/'raw'/f"{self.proto['id']}-task-history-before-round-1.json").is_file())
        current = self.local.get_research_task()
        self.assertEqual(current['test_revision']['test_id'], test['id'])
        self.assertIn('saved specimen', current['test_revision']['reason'])
        self.assertEqual(action(self.local)['tool'], 'read_revised_test')
        original = self.local.workspace.read_file('prototype/test.py')
        self.local.workspace.write_file('prototype/test.py', 'raise RuntimeError("mutable workspace changed")\n')
        read = self.local.read_revised_test(test['id'])
        self.assertIn('encoded=base64', read['text'])
        self.assertNotIn('mutable workspace changed', read['text'])
        self.assertEqual(action(self.local)['tool'], 'required')

    async def test_repair_requires_own_read_changed_script_and_explicit_review_link(self):
        test = await self.revised()
        self.assertEqual(self.plan()['reason'], 'OWN_REVISED_SCRIPT_READ_REQUIRED')
        self.local.read_revised_test(test['id'])
        self.assertEqual(self.plan()['reason'], 'REVISED_TEST_NEEDS_CODE_CHANGE')
        self.local.workspace.write_file('prototype/test.py', 'assert True # changed fixture, not semantic proof\n')
        self.assertEqual(self.plan()['reason'], 'REVIEW_REPAIR_PLAN_REQUIRED')
        result = self.local.record_prototype_plan(self.idea['id'],
            'Decode saved specimen bytes and test changed specimen rejection', 'exports/input.epub',
            'prototype/test.py', ['prototype/specimen.bin', 'prototype/recovered.bin'],
            'Recovered bytes must match the complete original', 'Changed saved bytes must fail or recover safely',
            'FULL_MECHANISM', '', repair_notes='Read the stored specimen rather than only the in-memory original',
            repair_check='Compare recovered bytes and exercise actual corrupt saved input', revision_test_id=test['id'])
        self.assertEqual(result['revision_repair']['test_id'], test['id'])
        self.assertEqual(action(self.local)['tool'], 'run_experiment')

    async def test_two_unproductive_rounds_defer_idea_and_assign_the_next(self):
        await self.revised()
        other = copy.deepcopy(self.idea)
        other.update(id='IDEA-NEXT', title='Next distinct fixture', prototype_tested=False)
        other.pop('test_receipts', None)
        self.engine.state['ideas'].append(other)
        self.proto['rounds'] = 2
        begin(self.local)
        finish(self.local)
        finish(self.local)  # idempotent accounting for the same round
        self.assertEqual(self.proto['prototype_revision_progress']['stalled_rounds'], 1)
        self.proto['rounds'] = 3
        begin(self.local)
        finish(self.local)
        self.assertEqual(self.proto['research_task_blocks'][-1]['reason'], 'PROTOTYPE_REVISION_STALLED')
        self.assertEqual([i['id'] for i in local_candidates(self.engine.state, self.proto)], ['IDEA-NEXT'])
        assign(self.engine, self.proto)
        self.assertEqual(self.proto['research_assignment']['target_id'], 'IDEA-NEXT')
        self.assertNotEqual(self.idea['status'], 'REJECTED')

    async def test_actual_code_edit_resets_stall_counter_but_plan_wording_does_not(self):
        test = await self.revised()
        self.proto['rounds'] = 2
        begin(self.local)
        finish(self.local)
        self.proto['rounds'] = 3
        self.local.workspace.write_file('prototype/test.py', 'assert True # actual edited bytes\n')
        finish(self.local)
        self.assertEqual(self.proto['prototype_revision_progress']['stalled_rounds'], 0)
        self.assertFalse(self.proto.get('research_task_blocks'))

    async def test_operator_resolution_reopens_two_round_progress_allowance(self):
        await self.revised()
        for n in (2, 3):
            self.proto['rounds'] = n
            begin(self.local)
            finish(self.local)
        self.assertEqual(local_candidates(self.engine.state, self.proto), [])
        self.proto.setdefault('operator_notes', []).append('The missing public specimen was supplied')
        self.assertEqual([i['id'] for i in local_candidates(self.engine.state, self.proto)], [self.idea['id']])
        self.proto['rounds'] = 4
        begin(self.local)
        self.assertEqual(self.proto['prototype_revision_progress']['stalled_rounds'], 0)

    async def test_old_execution_receipt_cannot_finish_revised_assignment(self):
        await self.revised()
        output = complete(self.engine.state, self.proto,
            {'status': 'COMPLETED', 'unexplored_leads': [], 'handoff_leads': []})
        self.assertEqual(output['status'], 'CONTINUE')
        self.assertFalse(self.idea['prototype_tested'])
        with self.assertRaises(ValueError):
            self.review.read_revised_test(self.engine.state['tests'][0]['id'])

    async def test_new_pending_receipt_clears_old_repair_until_independent_review(self):
        test = await self.revised()
        newer = copy.deepcopy(test)
        newer.update(id='NEW-TEST', prototype_review={})
        self.engine.state['tests'].append(newer)
        self.assertIsNone(action(self.local))
        self.assertEqual(local_candidates(self.engine.state, self.proto), [])

    async def test_repaired_execution_requires_receipt_instead_of_another_rerun(self):
        test = await self.revised()
        self.local.read_revised_test(test['id'])
        self.local.workspace.write_file('prototype/test.py', 'assert True # mock-executor fixture repair\n')
        self.local.record_prototype_plan(self.idea['id'], 'Repair the saved-specimen test operation',
            'exports/input.epub', 'prototype/test.py', ['prototype/specimen.bin', 'prototype/recovered.bin'],
            'Compare all actual recovered bytes', 'Corrupt actual saved bytes and check safe rejection',
            'FULL_MECHANISM', '', revision_test_id=test['id'],
            repair_notes='Changed script to consume the persisted generated specimen',
            repair_check='Compare original bytes and exercise the altered specimen')
        with patch('metaweb_swarm.engine.DockerExecutor') as docker:
            def execute(*args):
                self.local.workspace.write_file('prototype/specimen.bin', b'new fixture specimen')
                self.local.workspace.write_file('prototype/recovered.bin', b'mock recovered output')
                return {'status': 'COMPLETED', 'returncode': 0, 'output': 'Mock executor; unit test checks dispatch only'}
            docker.return_value.run.side_effect = execute
            experiment = await self.local.run_experiment(['python', 'prototype/test.py'], self.idea['id'])
        self.assertEqual(action(self.local)['tool'], 'record_test')
        self.assertEqual(action(self.local)['experiment_id'], experiment['experiment_id'])
        receipt = self.local.record_test(self.idea['id'], experiment['experiment_id'], 'New execution-bound revision fixture')
        self.assertNotEqual(receipt['id'], test['id'])
        self.assertIsNone(action(self.local))
        self.assertFalse(self.idea['prototype_tested'])

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK optional')
    async def test_actual_sdk_reads_revision_then_records_real_obstacle_and_moves_on(self):
        from tests.test_backend import FakeProvider, tool_response, final_response
        test = await self.revised()
        provider = FakeProvider([
            tool_response('read_revised_test', {'test_id': test['id'], 'offset': 0, 'limit': 16000}),
            tool_response('record_research_blocker', {'idea_id': self.idea['id'],
                'reason': 'This external retrieval property needs a public specimen and dedicated credentials not available in this local task'}, ident='block'),
            final_response()])
        self.engine.backend = OpenAIBackend(provider)
        await self.engine.step(self.proto)
        choices = [kw.get('model_settings', args[2] if len(args)>2 else None).tool_choice
                   for args, kw in provider.model.calls]
        self.assertEqual(choices[:2], ['read_revised_test', 'required'])
        self.assertNotEqual(self.proto['status'], 'PENDING')
        self.assertFalse(self.engine.state['external_actions'])
