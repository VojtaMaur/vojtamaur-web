"""Offline regression checks for depleted request headroom and read-only rounds."""
import asyncio
import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from metaweb_swarm.budget import capacity_reason, mark_unknown, reserve
from metaweb_swarm.config import PACKAGE_ROOT, load_config
from metaweb_swarm.engine import Engine, ToolAPI, initialize
from metaweb_swarm.storage import atomic_write


def completed():
    return {'output': {'status': 'COMPLETED', 'summary': 'Retained research reported.',
            'reason_for_stopping': 'Assignment finished', 'unexplored_leads': [],
            'handoff_leads': [], 'blind_spots': []}, 'history': [], 'usage': {}, 'raw': {}}


class CapacityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        project = root / 'project'
        project.mkdir()
        config = load_config(PACKAGE_ROOT / 'config.research.json')
        config.update(semantic_dedupe=False, max_total_tokens=80000, max_output_tokens=8000)
        self.run = initialize(project, root / 'runs', config)
        self.engine = Engine(self.run, None, 'openai')
        self.discovery = next(a for a in self.engine.state['agents'] if a['work_kind'] == 'DISCOVERY')
        self.coordinator = next(a for a in self.engine.state['agents'] if a['work_kind'] == 'COORDINATION')

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def test_capacity_probe_is_side_effect_free_and_still_counts_unknown_holds(self):
        state = self.engine.state
        before = copy.deepcopy(state)
        self.assertIsNone(capacity_reason(state, self.discovery['id'], 1000, 1000, 0))
        self.assertIn('MAX_TOTAL_TOKENS', capacity_reason(state, self.discovery['id'], 80000, 1, 0))
        self.assertEqual(state, before)
        hold = reserve(state, self.discovery['id'], 1000, 1000, 0)
        mark_unknown(state, hold['id'], 'Cancellation left provider outcome unknown')
        before = copy.deepcopy(state)
        self.assertIn('RECONCILIATION', capacity_reason(state, self.coordinator['id'], 1, 1, 0))
        self.assertEqual(state, before)

    async def test_lower_bound_rejection_creates_no_workspace_round_request_or_charge(self):
        before = (self.engine.state['steps'], self.discovery['rounds'], copy.deepcopy(self.engine.state['usage']))
        with patch('metaweb_swarm.engine.Workspace', side_effect=AssertionError('Unnecessary project copy')) as workspace:
            await self.engine.step(self.discovery)
            await self.engine.step(self.discovery)
        workspace.assert_not_called()
        self.assertEqual(self.discovery['status'], 'LIMIT_REACHED')
        saved = next(a for a in self.engine.store.load()['agents'] if a['id'] == self.discovery['id'])
        self.assertEqual(saved['status'], 'LIMIT_REACHED')
        self.assertEqual((self.engine.state['steps'], self.discovery['rounds'], self.engine.state['usage']), before)
        self.assertFalse(self.engine.state.get('budget_reservations'))
        self.assertFalse(self.engine.state.get('budget_request_sequences'))
        self.assertFalse((self.run / 'agents' / self.discovery['id']).exists())
        events = self.engine.store.db.execute('SELECT body FROM events').fetchall()
        self.assertEqual(sum('"kind":"model_request_capacity_stopped"' in row[0] for row in events), 1)

    def test_other_preflight_fault_does_not_leave_a_pending_scheduler_spin(self):
        with patch.object(self.engine,'request_capacity_reason',return_value='USD_PRICE_CEILINGS_REQUIRED'):
            self.engine.prepare_request_capacity(self.coordinator)
            self.engine.prepare_request_capacity(self.coordinator)
        self.assertEqual(self.coordinator['status'],'BLOCKED')
        self.assertEqual(self.engine.state['steps'],0)
        self.assertEqual(self.engine.state['usage']['requests'],0)
        events=self.engine.store.db.execute('SELECT body FROM events').fetchall()
        self.assertEqual(sum('"kind":"agent_request_preflight_blocked"' in row[0] for row in events),1)

    def test_exact_refusal_is_retained_until_budget_or_task_context_changes(self):
        state = self.engine.state
        api = ToolAPI(self.engine, self.coordinator, None)
        # The cheap minimum fits, but the real request payload does not.
        reason = api.begin_model_request('x' * 80000, [], [], None, search_calls=0)
        self.assertIn('MAX_TOTAL_TOKENS', reason)
        marker = copy.deepcopy(self.coordinator['request_budget_stop'])
        self.coordinator['status'] = 'LIMIT_REACHED'
        self.assertIn('MAX_TOTAL_TOKENS', self.engine.prepare_request_capacity(self.coordinator))
        self.assertEqual(self.coordinator['request_budget_stop'], marker)
        self.assertEqual(state['usage']['requests'], 0)
        state['config']['max_total_tokens'] = 200000
        self.assertIsNone(self.engine.prepare_request_capacity(self.coordinator))
        self.assertEqual(self.coordinator['status'], 'PENDING')
        self.assertNotIn('request_budget_stop', self.coordinator)
        saved = next(a for a in self.engine.store.load()['agents'] if a['id'] == self.coordinator['id'])
        self.assertEqual(saved['status'], 'PENDING')
        state['config']['max_total_tokens'] = 80000
        self.assertIn('MAX_TOTAL_TOKENS', api.begin_model_request('x' * 80000, [], [], None, search_calls=0))
        self.coordinator['status'] = 'LIMIT_REACHED'
        self.coordinator['final_report_only'] = True
        self.coordinator['history'] = []
        self.assertIsNone(self.engine.prepare_request_capacity(self.coordinator))
        self.assertEqual(self.coordinator['status'], 'PENDING')

    async def test_unaffordable_discovery_does_not_prevent_a_later_no_search_report(self):
        calls = []
        reporter = next(a for a in self.engine.state['agents'] if a['work_kind'] == 'SYNTHESIS')
        self.engine.state['agents'] = [self.discovery, reporter]

        class OfflineBackend:
            async def step(backend, agent, prompt, history, api, config):
                calls.append(agent['id'])
                api.record_research_report([], 'No verified discoveries; capacity-limited research retained.', [])
                return completed()

        self.engine.backend = OfflineBackend()
        with redirect_stdout(io.StringIO()):
            state = await self.engine.run()
        self.assertEqual(calls, [reporter['id']])
        self.assertEqual(state['steps'], 1)
        self.assertEqual(self.discovery['rounds'], 0)
        self.assertEqual(state['status'], 'LIMIT_REACHED')
        self.assertIn('REQUEST_CAPACITY_REQUIRED', state['stop_reason'])
        self.assertEqual(reporter['status'], 'COMPLETED')
        self.assertFalse(state.get('budget_reservations'))

    async def test_brainstorming_skips_patch_scan_and_retains_historical_patch(self):
        class OfflineBackend:
            async def step(*args):
                return completed()
        self.engine.backend = OfflineBackend()
        historical = {'path': 'patches/old.patch', 'changes': 2}
        self.coordinator['patch'] = copy.deepcopy(historical)
        with patch('metaweb_swarm.engine.export_patch', side_effect=AssertionError('Read-only scan')) as export:
            await self.engine.step(self.coordinator)
        export.assert_not_called()
        self.assertEqual(self.coordinator['patch'], historical)
        self.assertEqual(self.coordinator['status'], 'COMPLETED')

    async def test_cancelled_inflight_request_keeps_unknown_reservation(self):
        entered = asyncio.Event()

        class WaitingBackend:
            async def step(backend, agent, prompt, history, api, config):
                self.assertIsNone(api.begin_model_request('small request', [], [], None, search_calls=0))
                api.record_sdk_event('model_request_started', {'attempt': 1})
                entered.set()
                await asyncio.Future()

        self.engine.backend = WaitingBackend()
        with patch('metaweb_swarm.engine.export_patch') as export:
            task = asyncio.create_task(self.engine.step(self.coordinator))
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        export.assert_not_called()
        holds = list(self.engine.state['budget_reservations'].values())
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]['status'], 'UNKNOWN')
        self.assertEqual(self.engine.state['usage']['requests'], 1)
        self.assertEqual(self.engine.state['usage']['unknown_steps'], 1)


class AtomicWriteTests(unittest.TestCase):
    def test_transient_windows_file_lock_retries_then_atomically_replaces(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'checkpoint.json'
            target.write_text('old', encoding='utf-8')
            import os
            real_replace = os.replace
            calls = []

            def replace(source, destination):
                calls.append((source, destination))
                if len(calls) < 3:
                    raise PermissionError('Windows reader temporarily holds destination')
                real_replace(source, destination)

            with patch('metaweb_swarm.storage.os.replace', side_effect=replace), patch('metaweb_swarm.storage.time.sleep') as sleep:
                atomic_write(target, 'new')
            self.assertEqual(target.read_text(encoding='utf-8'), 'new')
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(len(list(Path(temp).glob('*.tmp'))), 0)
            first = calls[0][0]
            with patch('metaweb_swarm.storage.os.replace', wraps=real_replace) as replacement:
                atomic_write(target, 'another')
            self.assertNotEqual(replacement.call_args.args[0], first)

    def test_persistent_permission_error_is_not_hidden_or_retried_forever(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'checkpoint.json'
            target.write_text('old', encoding='utf-8')
            with (patch('metaweb_swarm.storage.os.replace', side_effect=PermissionError('still locked')) as replacement,
                  patch('metaweb_swarm.storage.time.sleep') as sleep,
                  self.assertRaisesRegex(PermissionError, 'still locked')):
                atomic_write(target, 'new')
            self.assertEqual(replacement.call_count, 5)
            self.assertEqual(sleep.call_count, 4)
            self.assertEqual(target.read_text(encoding='utf-8'), 'old')
            self.assertFalse(list(Path(temp).glob('*.tmp')))


if __name__ == '__main__':
    unittest.main()
