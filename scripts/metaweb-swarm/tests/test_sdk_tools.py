"""Exercise public-export and execution SDK adapters with a local fake model."""
import json
import unittest

from metaweb_swarm.backend import OpenAIBackend, _make_sdk_tools, check_sdk
from tests.test_backend import SDK_AVAILABLE, Tools, AGENT, CONFIG

if SDK_AVAILABLE:
    import agents as sdk
    from tests.test_backend import FakeProvider, tool_response, final_response


class CapabilityTools(Tools):
    def __init__(self):
        super().__init__()
        self.calls = []

    def list_exports(self):
        self.calls.append(("list_exports",))
        return {"files": [{"path": "web.pdf", "sha256": "a" * 64, "bytes": 12}]}

    def check_prior_work(self, terms):
        self.calls.append(('check_prior_work', terms))
        return {'matches': [{'ref': 'old-run/IDEA-0001'}], 'total_matches': 1}

    async def install_packages(self, packages, idea_id=''):
        self.calls.append(('install_packages', packages, idea_id))
        return {'status': 'COMPLETED', 'install_path': '.packages'}

    def materialize_export(self, export_path, workspace_path):
        self.calls.append(("materialize_export", export_path, workspace_path))
        return {"path": workspace_path, "sha256": "a" * 64}

    async def run_experiment(self, argv, idea_id=""):
        self.calls.append(("run_experiment", argv, idea_id))
        return {"experiment_id": "EXPERIMENT-001", "exit_code": 0}

    def record_test(self, idea_id, experiment_id, description):
        self.calls.append(("record_test", idea_id, experiment_id, description))
        return {"recorded": True, "execution_verified": True}

    def record_critique(self, idea_id, verdict, reason):
        self.calls.append(("record_critique", idea_id, verdict, reason))
        return {"recorded": True, "verdict": verdict}

    async def deposit_file(self, idea_id, resource_id, path, source="artifact", object_name=""):
        self.calls.append(("deposit_file", idea_id, resource_id, path, source, object_name))
        return {"status": "PENDING", "reason": "Host approval policy"}


@unittest.skipUnless(SDK_AVAILABLE, "Install requirements-openai.txt for SDK integration tests")
class CapabilitySDKTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_artifact_capture_requests_new_experiment_not_human_block(self):
        class MissingCapture(CapabilityTools):
            def record_test(self, *args):
                raise ValueError('Artifact bytes were not captured with this experiment; update IDEA paths before running the test')
        tools = MissingCapture(); tools.agent = {}
        provider = FakeProvider([tool_response('record_test', {'idea_id':'IDEA-001','experiment_id':'EXPERIMENT-old','description':'Check CBOR assertions'}), final_response()])
        result = await OpenAIBackend(provider).step(AGENT, 'Record test', [], tools, CONFIG)
        output = next(json.loads(i['output']) for i in result['history'] if i.get('type') == 'function_call_output')
        self.assertEqual(output['status'], 'RETRY_REQUIRED')
        self.assertIn('NEW experiment_id', output['next_action'])
        self.assertEqual(tools.agent['pending_test_recovery']['idea_id'], 'IDEA-001')

    def test_reporter_receives_only_observation_tools(self):
        tools = CapabilityTools()
        tools.agent = {'work_kind':'SYNTHESIS'}
        available, _ = _make_sdk_tools(sdk, tools)
        names = {t.name for t in available}
        self.assertIn('read_file', names)
        self.assertIn('note', names)
        self.assertFalse(names & {'install_packages','run_experiment','materialize_export','write_file','deposit_file','submit_idea'})
    async def test_prior_work_tool_forwards_exact_terms_and_provenance(self):
        tools = CapabilityTools()
        provider = FakeProvider([tool_response('check_prior_work', {'terms': ['ORCID', 'XMP']}), final_response()])
        result = await OpenAIBackend(provider).step(AGENT, 'Check prior work', [], tools, CONFIG)
        self.assertEqual(tools.calls, [('check_prior_work', ['ORCID', 'XMP'])])
        outputs = [json.loads(i['output']) for i in result['history'] if i.get('type') == 'function_call_output']
        self.assertEqual(outputs[0]['matches'][0]['ref'], 'old-run/IDEA-0001')

    async def test_package_tool_forwards_names_and_idea_through_real_sdk(self):
        tools = CapabilityTools()
        provider = FakeProvider([tool_response('install_packages', {'packages':['Pillow','qrcode[pil]','cbor2>=5'], 'idea_id':'IDEA-001'}), final_response()])
        result = await OpenAIBackend(provider).step(AGENT,'Install prototype dependencies',[],tools,CONFIG)
        self.assertEqual(tools.calls,[('install_packages',['Pillow','qrcode[pil]','cbor2>=5'],'IDEA-001')])
        outputs=[json.loads(i['output']) for i in result['history'] if i.get('type')=='function_call_output']
        self.assertEqual(outputs[0]['status'],'COMPLETED')
    async def test_public_export_tools_forward_exact_inputs_and_hashes(self):
        tools = CapabilityTools()
        provider = FakeProvider([
            tool_response("list_exports", {}),
            tool_response("materialize_export", {"export_path": "web.pdf", "workspace_path": "work/web.pdf"}, "call-b"),
            final_response(),
        ])
        result = await OpenAIBackend(provider).step(AGENT, "Inspect public inputs", [], tools, CONFIG)
        self.assertEqual(tools.calls, [("list_exports",), ("materialize_export", "web.pdf", "work/web.pdf")])
        outputs = [json.loads(item["output"]) for item in result["history"] if item.get("type") == "function_call_output"]
        self.assertEqual(outputs[0]["files"][0]["sha256"], "a" * 64)

    async def test_test_and_critique_and_deposit_remain_host_decisions(self):
        tools = CapabilityTools()
        provider = FakeProvider([
            tool_response("run_experiment", {"argv": ["python", "work/test.py"], "idea_id": "IDEA-001"}),
            tool_response("record_test", {"idea_id": "IDEA-001", "experiment_id": "EXPERIMENT-001", "description": "Recovered export hash matched"}, "call-b"),
            tool_response("record_critique", {"idea_id": "IDEA-001", "verdict": "PASS", "reason": "Independent custody is plausible"}, "call-c"),
            tool_response("deposit_file", {"idea_id": "IDEA-001", "resource_id": "public-test", "path": "work/web.pdf", "source": "artifact", "object_name": "specimen.pdf"}, "call-d"),
            final_response(),
        ])
        result = await OpenAIBackend(provider).step(AGENT, "Test then ask for deposit", [], tools, CONFIG)
        self.assertEqual(tools.calls[0], ("run_experiment", ["python", "work/test.py"], "IDEA-001"))
        self.assertEqual(tools.calls[1], ("record_test", "IDEA-001", "EXPERIMENT-001", "Recovered export hash matched"))
        self.assertEqual(tools.calls[2][2], "PASS")
        self.assertEqual(tools.calls[3], ("deposit_file", "IDEA-001", "public-test", "work/web.pdf", "artifact", "specimen.pdf"))
        outputs = [json.loads(item["output"]) for item in result["history"] if item.get("type") == "function_call_output"]
        self.assertEqual(outputs[-1]["status"], "PENDING")
        self.assertTrue(any(kind == "tool_finished" for kind, _ in tools.events))

    async def test_optional_mechanism_identity_fields_survive_sdk(self):
        idea = {"id": "", "title": "ORCID pointer", "mechanism": "Reconstruction links", "provider": "ORCID",
                "summary": "hypothesis", "status": "INVESTIGATING", "payment": "FREE", "novelty": "candidate",
                "evidence": [], "failure_domains": [], "scores_json": "{}", "blocker": "", "next_action": "verify",
                "rejection_reason": "", "artifacts": [], "mechanism_key": "orcid-pointer", "mechanism_scope": "public-recovery-pointer"}
        tools = CapabilityTools()
        provider = FakeProvider([tool_response("submit_idea", {"idea": idea}), final_response()])
        await OpenAIBackend(provider).step(AGENT, "Record same mechanism consistently", [], tools, CONFIG)
        self.assertEqual(tools.ideas[0]["mechanism_key"], "orcid-pointer")
        self.assertEqual(tools.ideas[0]["mechanism_scope"], "public-recovery-pointer")

    def test_new_tool_schemas_are_closed_and_no_key_probe_works(self):
        tools, output = _make_sdk_tools(sdk, CapabilityTools())
        by_name = {tool.name: tool for tool in tools}
        self.assertTrue({"list_exports", "materialize_export", "install_packages", "run_experiment", "record_test", "record_critique", "deposit_file"} <= set(by_name))
        for tool in tools:
            self.assertTrue(tool.strict_json_schema)
            self.assertIs(tool.params_json_schema["additionalProperties"], False)
            self.assertEqual(set(tool.params_json_schema["required"]), set(tool.params_json_schema["properties"]))
        self.assertIn("idea_id", by_name["run_experiment"].params_json_schema["properties"])
        self.assertEqual(by_name["record_critique"].params_json_schema["properties"]["verdict"]["enum"], ["PASS", "REVISE", "REJECT"])
        self.assertTrue(check_sdk()["compatible"])
