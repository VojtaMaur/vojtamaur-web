import tempfile
import unittest
from pathlib import Path
from metaweb_swarm.config import load_config, validate_config
from metaweb_swarm.engine import initialize, Engine, OBJECTIVE
from metaweb_swarm.demo import DemoBackend

class DepositTrialTests(unittest.TestCase):
    def test_profile_objective_survives_checkpoint_and_enters_prompt(self):
        config = load_config(Path(__file__).resolve().parents[1]/"config.deposit-trial.json")
        self.assertTrue(config["approval_required"])
        self.assertTrue(config["require_independent_http_review"])
        self.assertIn("SWARM ACCOUNTS AND API CREDENTIALS ARE ALLOWED", config["operator_objective"])
        self.assertEqual(config["max_external_actions"], 1)
        self.assertEqual(config["estimated_budget_usd"], 5)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); project = root/"project"; project.mkdir()
            (project/"site.txt").write_text("public content", encoding="utf-8")
            (project/"exports").mkdir()
            (project/"exports"/config["export_filenames"][0]).write_bytes(b"opaque public export fixture")
            (project/"exports"/"unselected-large.pdf").write_bytes(b"unselected")
            run = initialize(project, root/"runs", config)
            engine = Engine(run, DemoBackend(), "demo")
            try:
                self.assertEqual(engine.state["objective"], config["operator_objective"])
                self.assertEqual(len(engine.state["agents"]), 4)
                phases = {a["role"]: a["phase"] for a in engine.state["agents"]}
                self.assertLess(phases["Evidence Auditor"], phases["Prototyper"])
                self.assertLess(phases["Prototyper"], phases["Synthesizer / Reporter"])
                self.assertEqual([f["path"] for f in engine.state["exports"]["files"]], config["export_filenames"])
                prompt = engine.prompt(engine.state["agents"][0])
                self.assertIn("FOCUSED REAL-EXPORT DEPOSIT TRIAL", prompt)
                self.assertIn("HUMAN_APPROVAL_REQUIRED", prompt)
                self.assertNotIn("Explore at least three unrelated families", prompt)
                self.assertNotIn("create an encoder/decoder and assertion script", prompt)
            finally: engine.close()
    def test_invalid_objective_rejected(self):
        for value in ("", "   ", 5, "x"*12001):
            config = load_config(); config["operator_objective"] = value
            with self.assertRaises(ValueError): validate_config(config)
    def test_default_objective_unchanged(self):
        self.assertIsNone(load_config()["operator_objective"])
