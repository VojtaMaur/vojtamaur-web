import json
import unittest

from metaweb_swarm.memory import compact_history, concise_state
from metaweb_swarm.research import external_sources, research_brief
from metaweb_swarm.config import load_config
from metaweb_swarm.roles import seed_agents
from metaweb_swarm.policy import normalize_idea
from metaweb_swarm.demo import DemoBackend


class MemoryResearchTests(unittest.TestCase):
    def test_compaction_keeps_call_result_pairs_and_archives_excerpts(self):
        history = [{"role": "user", "content": "old task"}]
        for i in range(30):
            history += [{"type": "function_call", "name": "read_file", "call_id": str(i), "arguments": '{"path":"source.txt"}'},
                        {"type": "function_call_output", "call_id": str(i), "output": "data " * 1000}]
        compact = compact_history(history, "context/archive.json", target=8000)
        self.assertLess(len(json.dumps(compact)), 16000)
        calls = [x["call_id"] for x in compact if x.get("type") == "function_call"]
        outputs = [x["call_id"] for x in compact if x.get("type") == "function_call_output"]
        self.assertEqual(calls, outputs)
        self.assertNotIn("old task", json.dumps(compact))
        self.assertIn("context/archive.json", json.dumps(compact))
        self.assertEqual(len(history), 61)
        self.assertEqual(history[2]["output"], "data " * 1000)

    def test_compaction_preserves_parallel_call_group(self):
        history = [{"type": "function_call", "call_id": "a", "name": "read_file"},
                   {"type": "function_call", "call_id": "b", "name": "read_file"},
                   {"type": "function_call_output", "call_id": "a", "output": "x" * 5000},
                   {"type": "function_call_output", "call_id": "b", "output": "y" * 5000}]
        result = compact_history(history, "context/original.json", 1000)
        self.assertFalse(any(x.get("type") == "function_call_output" for x in result))
        self.assertIn("original.json", json.dumps(result))

    def test_shared_state_omits_revision_chain_and_caps_summaries(self):
        state = {"ideas": [{"id": "IDEA-1", "title": "Candidate", "revisions": [{"previous": "x" * 100000}]}],
                 "agents": [{"id": "AGENT-1", "summary": "z" * 8000}], "approvals": []}
        result = concise_state(state)
        self.assertNotIn("revisions", json.dumps(result))
        self.assertEqual(len(result["roles"][0]["summary"]), 600)
        self.assertEqual(len(state["agents"][0]["summary"]), 8000)

    def test_owner_sources_do_not_count_as_external(self):
        data = {"action": {"sources": [{"url": "https://vojtamaur.cz/documentation/"},
                                          {"url": "https://www.vojtamaur.cz/"},
                                          {"url": "https://example.org/standard"}]}}
        self.assertEqual(external_sources(data), ["https://example.org/standard"])

    def test_research_roster_selection_and_distinct_assignments(self):
        config = load_config()
        config["seed_roles"] = ["Infrastructure Scout", "Format Mutant"]
        agents = seed_agents(config)
        self.assertEqual(len(agents), 2)
        self.assertNotEqual(research_brief(agents[0]), research_brief(agents[1]))
        self.assertTrue(all("Start with external web search" in research_brief(a) for a in agents))

    def test_negative_audit_is_observation_not_candidate(self):
        with self.assertRaisesRegex(ValueError, "use note"):
            normalize_idea(DemoBackend.idea("No novel preservation mechanism verified", "Audit conclusion", "UNKNOWN", "INVESTIGATING"))
