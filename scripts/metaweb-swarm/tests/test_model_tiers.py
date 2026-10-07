import asyncio
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from metaweb_swarm.backend import OpenAIBackend
from metaweb_swarm.budget import reserve, settle, mark_unknown
from metaweb_swarm.cli import main
from metaweb_swarm.config import estimated_cost, load_config, validate_config
from metaweb_swarm.console import progress
from metaweb_swarm.engine import Engine, ToolAPI, initialize
from metaweb_swarm.models import assign_model, prices_for, search_allowance
from metaweb_swarm.roles import seed_agents, new_agent
from metaweb_swarm.storage import Store
from metaweb_swarm.workspace import Workspace
from tests.test_backend import SDK_AVAILABLE

if SDK_AVAILABLE:
    from tests.test_backend import FakeProvider, final_response


class ModelTierTests(unittest.TestCase):
    def config(self):
        config = load_config()
        config.update(model="mini", model_tiers={"cheap": "mini", "strong": "large", "flag": "flagship"})
        return config

    def test_seed_assignments_emergent_default_and_operator_override(self):
        config = self.config()
        agents = {a['role']: a for a in seed_agents(config)}
        self.assertEqual(agents['Meta-Archivist / Orchestrator']['model'], 'flagship')
        self.assertEqual(agents['Loophole Archivist']['model'], 'flagship')
        self.assertEqual(agents['Infrastructure Scout']['model'], 'mini')
        config['role_model_tiers'] = {'Loophole Archivist': 'cheap', 'New Specialist': 'flag'}
        self.assertEqual(seed_agents(config)[1]['model'], 'mini')
        self.assertEqual(assign_model(config, new_agent('AGENT-020', 'Other Specialist', 'Explore'))['model'], 'large')
        self.assertEqual(assign_model(config, new_agent('AGENT-021', 'New Specialist', 'Explore'))['model'], 'flagship')
        self.assertEqual(assign_model(config, new_agent('AGENT-022', 'Hostile Reviewer', 'Explore', parent_id='AGENT-001'))['model'], 'large')

    def test_legacy_config_uses_global_model_for_every_role(self):
        config = self.config(); config['model_tiers'] = {}
        self.assertEqual({a['model'] for a in seed_agents(config)}, {'mini'})

    def test_dollar_limits_require_prices_for_expensive_tiers(self):
        config = self.config()
        config.update(estimated_budget_usd=1, input_price_per_million=1, output_price_per_million=2, web_search_price_per_call=.01)
        with self.assertRaisesRegex(ValueError, 'every configured model'):
            validate_config(config)
        config['model_prices'] = {m: dict(input_price_per_million=20, output_price_per_million=40, web_search_price_per_call=.02) for m in ('large', 'flagship')}
        validate_config(config)
        usage = {'total_tokens': 20, 'input_tokens': 10, 'output_tokens': 10, 'web_search_calls': 0,
                 'by_model': {'mini': {'input_tokens': 5, 'output_tokens': 5}, 'large': {'input_tokens': 5, 'output_tokens': 5}}}
        self.assertAlmostEqual(estimated_cost(usage, config), .000315)
        state = {'config': config, 'usage': usage}
        hold = reserve(state, 'AGENT-001', 1000, 1000, 1, 'large')
        self.assertEqual(hold['model'], 'large')
        self.assertEqual(hold['usd_upper'], '0.08')
        result = settle(state, 'AGENT-001', dict(input_tokens=5, output_tokens=5, total_tokens=10, web_search_calls=0))
        self.assertEqual(result['actual_usd_at_reserved_prices'], '0.0003')
        usage['by_model']['mini']['input_tokens'] = 0
        self.assertIsNone(estimated_cost(usage, config))
        self.assertIn('per-model usage', reserve(state, 'AGENT-002', 1, 1, 0, 'large'))

    def test_search_is_absent_for_synthesis_coordination_and_local(self):
        config = self.config(); config['max_web_search_calls_per_request'] = 3
        for kind in ('SYNTHESIS', 'COORDINATION', 'LOCAL'):
            self.assertEqual(search_allowance(config, {'work_kind': kind}), 0)
        self.assertEqual(search_allowance(config, {'work_kind': 'DISCOVERY'}), 3)
        self.assertEqual(search_allowance(config, {'work_kind': 'REVIEW'}), 3)

    def test_invalid_tiers_prices_and_assignments(self):
        for change in ({'model_tiers': {'unknown': 'mini'}}, {'model_tiers': {'strong': ''}},
                       {'role_model_tiers': {'Scout': 'expensive'}}, {'emergent_model_tier': 'unknown'},
                       {'model_prices': {'large': {'input_price_per_million': 1}}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_config(self.config() | change)

    def test_console_suppresses_identical_updates_but_shows_status_change(self):
        seen = {}; out = io.StringIO()
        with redirect_stdout(out):
            data = {'id': 'IDEA-0001', 'title': 'A\nnew candidate', 'status': 'DISCOVERED'}
            progress('idea_recorded', 'AGENT-001', data, seen)
            progress('idea_recorded', 'AGENT-001', data, seen)
            progress('idea_recorded', 'AGENT-002', dict(data, status='PROTOTYPED'), seen)
            progress('file_read', 'AGENT-001', {}, seen)
        self.assertEqual(len(out.getvalue().splitlines()), 2)
        self.assertIn('A new candidate', out.getvalue())

    def test_init_global_override_sets_all_tiers_and_snapshots_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = root / 'project'; project.mkdir()
            profile = root / 'config.json'; profile.write_text(json.dumps(self.config()))
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(['init', '--project', str(project), '--runs-root', str(root/'runs'), '--config', str(profile), '--model', 'test-only'])
            self.assertEqual(rc, 0)
            store = Store(Path(out.getvalue().strip()))
            try:
                self.assertEqual({a['model'] for a in store.load()['agents']}, {'test-only'})
            finally:
                store.close()

    def test_start_missing_key_leaves_no_run_and_calls_no_api(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {}, clear=True):
            root = Path(temp); project = root/'project'; project.mkdir()
            with redirect_stdout(io.StringIO()), patch('sys.stderr', new=io.StringIO()):
                rc = main(['start', '--project', str(project), '--runs-root', str(root/'runs'), '--backend', 'openai'])
            self.assertEqual(rc, 2)
            self.assertFalse((root/'runs').exists())

    def test_legacy_reconciliation_preserves_previously_accounted_model_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = root/'project'; project.mkdir()
            config = self.config(); config['model_tiers'] = {}
            run = initialize(project, root/'runs', config)
            store = Store(run)
            try:
                state = store.load(); agent = state['agents'][0]
                hold = reserve(state, agent['id'], 1000, 1000, 0)
                accounted = dict(input_tokens=100, output_tokens=50, total_tokens=150, web_search_calls=0)
                state['budget_reservations'][hold['id']]['accounted_usage'] = accounted
                state['usage'].update(accounted, unknown_steps=1)
                agent['usage'] = dict(state['usage'])
                mark_unknown(state, hold['id'], 'Legacy disconnected request fixture')
                store.commit(state, 'legacy_reconciliation_fixture', {})
            finally:
                store.close()
            with redirect_stdout(io.StringIO()):
                rc = main(['reconcile-budget', str(run), hold['id'], '--input-tokens', '110', '--output-tokens', '50', '--web-search-calls', '0', '--note', 'Verified fixture counters'])
            self.assertEqual(rc, 0)
            store = Store(run)
            try:
                usage = store.load()['usage']
                self.assertEqual(usage['total_tokens'], 160)
                self.assertEqual(usage['by_model']['mini']['total_tokens'], 160)
                self.assertEqual(usage['unknown_steps'], 0)
                self.assertEqual(usage['by_model']['mini']['unknown_steps'], 0)
            finally:
                store.close()

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK dependency absent')
    def test_real_sdk_calls_three_models_and_accounts_each_across_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = root/'project'; project.mkdir()
            config = self.config()
            config.update(seed_roles=['Evidence Auditor', 'Role Architect', 'Synthesizer / Reporter'],
                          max_concurrent_agents=1, max_total_tokens=1000000)
            run = initialize(project, root/'runs', config)
            provider = FakeProvider([final_response(), final_response(), final_response()])
            engine = Engine(run, OpenAIBackend(provider), 'openai')
            try:
                with redirect_stdout(io.StringIO()):
                    state = asyncio.run(engine.run())
                self.assertEqual(state['status'], 'COMPLETED')
                self.assertEqual(provider.models_requested, ['large', 'mini', 'flagship'])
                self.assertEqual(len(provider.model.calls), 3)
                self.assertEqual({m: u['total_tokens'] for m, u in state['usage']['by_model'].items()}, {'large': 15, 'mini': 15, 'flagship': 15})
                engine.store.verify()
            finally:
                engine.close()
            restored = Engine(run, OpenAIBackend(provider), 'openai')
            try:
                self.assertEqual(restored.state['usage']['total_tokens'], 45)
                self.assertEqual({a['model'] for a in restored.state['agents']}, {'large', 'mini', 'flagship'})
            finally:
                restored.close()

    @unittest.skipUnless(SDK_AVAILABLE, 'SDK dependency absent')
    def test_real_sdk_routes_models_and_reporter_fits_after_discovery_reservation_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); project = root/'project'; project.mkdir()
            config = self.config()
            config.update(seed_roles=['Evidence Auditor', 'Synthesizer / Reporter'], max_concurrent_agents=1,
                          max_web_search_calls_per_request=3, max_total_tokens=200000)
            run = initialize(project, root/'runs', config)
            provider = FakeProvider([final_response()])
            engine = Engine(run, OpenAIBackend(provider), 'openai')
            try:
                with redirect_stdout(io.StringIO()):
                    state = asyncio.run(engine.run())
                auditor, reporter = state['agents']
                self.assertEqual(auditor['status'], 'LIMIT_REACHED')
                self.assertEqual(reporter['status'], 'COMPLETED')
                self.assertEqual(provider.models_requested, ['large', 'flagship'])
                kwargs = provider.model.calls[0][1]
                self.assertFalse(any(t.__class__.__name__ == 'WebSearchTool' for t in kwargs['tools']))
                self.assertEqual(state['usage']['by_model']['flagship']['total_tokens'], 15)
                self.assertGreater(engine.store.verify()['events'], 0)
            finally:
                engine.close()
            restored = Engine(run, OpenAIBackend(provider), 'openai')
            try:
                self.assertEqual(restored.state['agents'][1]['model'], 'flagship')
                manifest = json.loads((run/'manifest.json').read_text(encoding='utf-8'))
                self.assertEqual(manifest['agents'][1]['model_tier'], 'flag')
            finally:
                restored.close()
