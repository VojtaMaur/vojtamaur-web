import asyncio
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from metaweb_swarm.config import PACKAGE_ROOT, load_config, round_allowance, schedule_batch, validate_config
from metaweb_swarm.cli import main
from metaweb_swarm.engine import Engine, initialize
from metaweb_swarm.workspace import DockerExecutor


class SchedulingTests(unittest.TestCase):
    def test_fair_same_phase_quantum(self):
        pending = [{'id': 'A', 'phase': 1, 'rounds': 2}, {'id': 'B', 'phase': 1, 'rounds': 0}, {'id': 'C', 'phase': 1, 'rounds': 1}]
        self.assertEqual([a['id'] for a in schedule_batch(pending, 8, 2)], ['B', 'C'])

    def test_reserve_keeps_concurrent_batch_from_consuming_final_step(self):
        pending = [{'id': 'A', 'phase': 1, 'rounds': 0}, {'id': 'B', 'phase': 1, 'rounds': 0}, {'id': 'Z', 'phase': 3, 'rounds': 0}]
        self.assertEqual(len(schedule_batch(pending, 2, 3)), 1)
        self.assertEqual(schedule_batch(pending, 1, 3)[0]['id'], 'Z')

    def test_role_limits_allow_manual_extension_and_legacy_configs(self):
        config = load_config()
        config['role_round_limits'] = {'Coordinator': 1}
        self.assertEqual(round_allowance(config, {'role': 'Coordinator'}), 1)
        self.assertEqual(round_allowance(config, {'role': 'Coordinator', 'round_limit': 2}), 2)
        del config['role_round_limits']
        validate_config(config)
        self.assertEqual(round_allowance(config, {'role': 'Coordinator'}), config['max_agent_rounds'])

    def test_invalid_round_cap_rejected(self):
        config = load_config()
        for value in (0, True, -1, 'two'):
            config['role_round_limits'] = {'Example': value}
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_windows_utf8_bom_profile_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'profile.json'
            path.write_text('{"model":"fixture-model"}', encoding='utf-8-sig')
            self.assertEqual(load_config(path)['model'], 'fixture-model')

    def test_research_profile_reaches_prototyper_and_reporter_with_emergence(self):
        calls = []
        class Continuing:
            async def step(self, agent, prompt, history, api, config):
                calls.append(agent['role'])
                if agent['role'] == 'Meta-Archivist / Orchestrator' and agent['rounds'] == 1:
                    api.spawn_agent({'role': 'Recovery transport specialist', 'mission': 'Investigate transport recovery mechanisms', 'reason': 'Coverage gap', 'question': 'Which independent transport can preserve a recovery pointer?', 'unique_expertise': 'Transport metadata', 'expected_output': 'Primary-source evidence', 'work_kind': 'DISCOVERY'})
                return {'output': {'status': 'CONTINUE', 'reason_for_stopping': 'More useful work', 'summary': '', 'unexplored_leads': ['Next concrete experiment'], 'blind_spots': []}, 'history': [], 'usage': {}, 'raw': {}}
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'project'
            project.mkdir()
            config = load_config(PACKAGE_ROOT / 'config.research.json')
            config['run_mode'] = 'autonomous'  # Scheduler coverage includes realization; supervised deliberately defers it.
            config['max_steps'] = 10  # Nine seeds plus one emergent role: exact first-pass budget.
            run = initialize(project, Path(temp) / 'runs', config)
            engine = Engine(run, Continuing(), 'demo')
            try:
                with redirect_stdout(io.StringIO()):
                    state = asyncio.run(engine.run())
                self.assertEqual(state['steps'], 10)
                self.assertTrue(all(a['rounds'] >= 1 for a in state['agents']))
                self.assertIn('Prototyper', calls)
                self.assertEqual(calls[-1], 'Synthesizer / Reporter')
                researchers = [role for role in calls if role in ('Loophole Archivist', 'Anomaly Engineer', 'Format Mutant', 'Infrastructure Scout')]
                self.assertEqual(len(set(researchers[:4])), 4)
            finally:
                engine.close()

    def test_init_model_override_is_snapshotted_without_editing_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'project'
            project.mkdir()
            profile = Path(temp) / 'profile.json'
            profile.write_text('{"model":"original-model"}', encoding='utf-8')
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(['init', '--project', str(project), '--runs-root', str(Path(temp) / 'runs'), '--config', str(profile), '--model', 'chosen-model'])
            self.assertEqual(code, 0)
            state = json.loads((Path(output.getvalue().strip()) / 'checkpoint.json').read_text(encoding='utf-8'))
            self.assertEqual(state['config']['model'], 'chosen-model')
            self.assertEqual(json.loads(profile.read_text())['model'], 'original-model')

    def test_docker_check_only_reads_daemon_and_local_image_without_secrets(self):
        executor = DockerExecutor()
        calls = []
        def fake(argv, environment, timeout):
            calls.append(argv)
            self.assertNotIn('OPENAI_API_KEY', environment)
            return {'returncode': 0, 'output': 'linux\n' if 'info' in argv else '[]', 'timed_out': False}
        with patch.object(executor, '_call', side_effect=fake), patch.dict('os.environ', {'OPENAI_API_KEY': 'fixture'}):
            result = executor.check_ready()
        self.assertTrue(result['ready'])
        self.assertFalse(result['experiment_executed'])
        self.assertEqual(len(calls), 2)
        self.assertFalse(any(word in argv for argv in calls for word in ('create', 'start', 'pull', 'build', '--mount')))

    def test_docker_missing_daemon_is_actionable(self):
        with patch.object(DockerExecutor, '_call', side_effect=FileNotFoundError('Docker not installed')):
            result = DockerExecutor().check_ready()
        self.assertFalse(result['ready'])
        self.assertEqual(result['reason'], 'DOCKER_UNAVAILABLE')
