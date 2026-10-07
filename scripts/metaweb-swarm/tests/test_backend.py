"""Real SDK with a local fake model: no API key, HTTP request, or paid inference."""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

from metaweb_swarm.backend import (
    BackendBlocked, BackendLimit, OpenAIBackend, check_sdk, _json_object, _make_sdk_tools,
    _repair_interrupted_history,
    _error_diagnostics,
    _file_page,
    BackendYield,
)

try:
    import agents as sdk
    from agents.items import ModelResponse
    from agents.models.interface import Model, ModelProvider, ModelTracing
    from agents.usage import Usage
    from agents.tool_context import ToolContext
    from openai.types.responses import (
        ResponseFunctionToolCall, ResponseFunctionWebSearch, ResponseOutputMessage,
        ResponseOutputText,
    )
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False


AGENT = {"id": "agent-001", "role": "Reviewer", "mission": "Review evidence"}
CONFIG = {"model": "explicit-test-model", "max_turns": 6, "max_output_tokens": 4000,
          "step_timeout_seconds": 2, "history_chars": 150000}
FINAL = {"status": "COMPLETED", "reason_for_stopping": "Reviewed assigned work",
         "summary": "Evidence inspected", "unexplored_leads": [], "blind_spots": [], "handoff_leads": []}


class Tools:
    def __init__(self):
        self.events = []
        self.approvals = []
        self.ideas = []

    def record_sdk_event(self, kind, data):
        self.events.append((kind, data))

    def list_files(self, path):
        return ["CURRENT_STATE.md"]

    def read_file(self, path, offset=0, limit=60000):
        return "Piql/AWA already in progress"

    def write_file(self, path, content):
        return {"path": path}

    async def run_experiment(self, argv):
        return {"status": "BLOCKED", "reason": "Experiments disabled"}

    def submit_idea(self, idea):
        self.ideas.append(idea)
        return {"id": idea.get("id") or "IDEA-001"}

    def request_approval(self, action):
        self.approvals.append(action)
        return {"status": "PENDING", "id": "APPROVAL-001"}

    def spawn_agent(self, request):
        return {"status": "QUEUED", "id": "agent-002"}

    def note(self, text):
        return {"recorded": True}


class CoreTests(unittest.IsolatedAsyncioTestCase):
    def test_file_listing_pages_are_bounded_and_complete(self):
        files = [str(i) + "x" * 200 for i in range(1500)]
        found = []
        offset = 0
        while offset is not None:
            page = _file_page(files, offset, 100)
            self.assertLess(len(json.dumps(page)), 8500)
            found.extend(page["files"])
            offset = page["next_offset"]
        self.assertEqual(found, files)
        with self.assertRaises(ValueError):
            _file_page(files, -1)

    async def test_model_must_be_explicit(self):
        with self.assertRaises(BackendBlocked) as caught:
            await OpenAIBackend().step(AGENT, "review", [{"role": "user", "content": "old"}],
                                       Tools(), {"model": None})
        self.assertEqual(caught.exception.history[0]["content"], "old")

    async def test_no_key_fails_without_loading_sdk(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(BackendBlocked) as caught:
                await OpenAIBackend().step(AGENT, "review", [], Tools(), CONFIG)
        self.assertIn("OPENAI_API_KEY", caught.exception.reason)

    async def test_history_limit_preserves_history(self):
        history = [{"role": "user", "content": "x" * 100}]
        with self.assertRaises(BackendLimit) as caught:
            await OpenAIBackend(model_provider=object()).step(
                AGENT, "review", history, Tools(), {**CONFIG, "history_chars": 20})
        self.assertEqual(caught.exception.history, history)
        self.assertTrue(caught.exception.raw["usage_complete"])

    def test_json_map_rejects_array(self):
        with self.assertRaises(ValueError):
            _json_object("[]")

    def test_http_error_body_is_preserved_and_credentials_redacted(self):
        error = ValueError("Error code: 400")
        error.status_code = 400
        error.request_id = "req_fixture"
        error.body = {"error": {"message": "Invalid parameter example, fixture-key", "param": "example", "type": "invalid_request_error"}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}):
            details = _error_diagnostics(error)
        self.assertEqual(details["status_code"], 400)
        self.assertEqual(details["body"]["error"]["param"], "example")
        self.assertNotIn("fixture-key", json.dumps(details))

    def test_interrupted_call_result_is_explicit_and_idempotent(self):
        history = [{"type": "function_call", "name": "write_file", "call_id": "call-a",
                    "arguments": '{"path":"x","content":"y"}'}]
        recovered = _repair_interrupted_history(history)
        self.assertEqual(recovered[1]["call_id"], "call-a")
        self.assertEqual(json.loads(recovered[1]["output"])["status"], "INTERRUPTED")
        self.assertEqual(_repair_interrupted_history(recovered), recovered)
        self.assertEqual(len(history), 1)


if SDK_AVAILABLE:
    def response(output, ident="response-1", tokens=15):
        return ModelResponse(output=output,
                             usage=Usage(requests=1, input_tokens=10,
                                         output_tokens=tokens - 10, total_tokens=tokens),
                             response_id=ident,
                             raw_usage={"input_tokens": 10, "output_tokens": tokens - 10,
                                        "total_tokens": tokens})

    def final_response(ident="response-final", output=FINAL):
        return response([ResponseOutputMessage(
            id="msg-" + ident, type="message", role="assistant", status="completed",
            content=[ResponseOutputText(type="output_text", text=json.dumps(output), annotations=[])]
        )], ident)

    def tool_response(name, arguments, ident="call-a"):
        return response([ResponseFunctionToolCall(id="fc-" + ident, type="function_call",
                                                  name=name, call_id=ident,
                                                  arguments=json.dumps(arguments))], ident)

    class FakeModel(Model):
        def __init__(self, outputs):
            self.outputs = list(outputs)
            self.calls = []

        async def get_response(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            item = self.outputs.pop(0)
            if isinstance(item, Exception):
                raise item
            if item == "wait":
                await asyncio.sleep(10)
                raise AssertionError("Timeout should cancel this model")
            return item

        async def stream_response(self, *args, **kwargs):
            raise AssertionError("Streaming is not used")
            yield

    class FakeProvider(ModelProvider):
        def __init__(self, outputs):
            self.model = FakeModel(outputs)
            self.models_requested = []

        def get_model(self, model_name):
            self.models_requested.append(model_name)
            return self.model


@unittest.skipUnless(SDK_AVAILABLE, "Install requirements-openai.txt for SDK integration tests")
class SDKTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_final_schema_history_and_settings(self):
        provider = FakeProvider([final_response()])
        tools = Tools()
        history = [{"role": "user", "content": "Previous work"}]
        result = await OpenAIBackend(provider).step(AGENT, "review", history, tools, CONFIG)
        self.assertEqual(result["output"], FINAL)
        self.assertEqual(result["history"][0], history[0])
        self.assertEqual(result["usage"]["total_tokens"], 15)
        self.assertTrue(result["raw"]["usage_complete"])
        self.assertEqual(provider.models_requested, ["explicit-test-model"])
        args, kwargs = provider.model.calls[0]
        self.assertEqual(kwargs["model_settings"].max_tokens, 4000)
        self.assertFalse(kwargs["model_settings"].parallel_tool_calls)
        self.assertFalse(kwargs["model_settings"].store)
        self.assertEqual(kwargs["model_settings"].response_include, ["web_search_call.action.sources"])
        self.assertEqual(kwargs["tracing"], ModelTracing.DISABLED)
        self.assertIsNone(kwargs["conversation_id"])
        hosted = [tool for tool in kwargs["tools"] if isinstance(tool, sdk.WebSearchTool)]
        self.assertEqual(len(hosted), 1)
        self.assertTrue(hosted[0].external_web_access)
        json.dumps(result, allow_nan=False)

    async def test_approval_only_queues_and_dict_payload_is_restored(self):
        tools = Tools()
        provider = FakeProvider([
            tool_response("request_approval", {"action": {
                "idea_id": "IDEA-001", "kind": "PAYMENT", "description": "One-time copy",
                "target": "https://example.org/archive", "payload_json": '{"amount":12}',
            }}), final_response(),
        ])
        result = await OpenAIBackend(provider).step(AGENT, "review", [], tools, CONFIG)
        self.assertEqual(tools.approvals[0]["payload"], {"amount": 12})
        self.assertEqual(result["usage"]["requests"], 2)
        outputs = [item for item in result["history"]
                   if item.get("type") == "function_call_output"]
        self.assertEqual(json.loads(outputs[0]["output"])["status"], "PENDING")

    async def test_stable_idea_id_and_scores_mapped(self):
        idea = {"id": "IDEA-007", "title": "Copy", "mechanism": "Optical", "provider": "",
                "summary": "hypothesis", "status": "INVESTIGATING", "payment": "ONE_TIME",
                "novelty": "unverified", "evidence": [], "failure_domains": ["physical"],
                "scores_json": '{"independence":0.7}', "blocker": "", "next_action": "verify",
                "rejection_reason": "", "artifacts": []}
        tools = Tools()
        provider = FakeProvider([tool_response("submit_idea", {"idea": idea}), final_response()])
        await OpenAIBackend(provider).step(AGENT, "review", [], tools, CONFIG)
        self.assertEqual(tools.ideas[0]["id"], "IDEA-007")
        self.assertEqual(tools.ideas[0]["scores"], {"independence": 0.7})
        self.assertNotIn("scores_json", tools.ideas[0])

    async def test_search_sources_preserved_in_raw_and_durable_audit(self):
        search = ResponseFunctionWebSearch.model_validate({
            "id": "ws-1", "type": "web_search_call", "status": "completed",
            "action": {"type": "search", "query": "archive optical", "sources": [
                {"type": "url", "url": "https://example.org/primary"}]} })
        provider = FakeProvider([response([search, *final_response().output])])
        tools = Tools()
        result = await OpenAIBackend(provider).step(AGENT, "review", [], tools, CONFIG)
        self.assertEqual(result["usage"]["web_search_calls"], 1)
        searches = [data for kind, data in tools.events if kind == "web_search_call"]
        self.assertEqual(searches[0]["action"]["sources"][0]["url"],
                         "https://example.org/primary")

    async def test_max_turns_retains_completed_tool_and_usage(self):
        provider = FakeProvider([tool_response("note", {"text": "Inspected document"})])
        tools = Tools()
        with self.assertRaises(BackendLimit) as caught:
            await OpenAIBackend(provider).step(AGENT, "review", [], tools,
                                               {**CONFIG, "max_turns": 1})
        error = caught.exception
        self.assertIsInstance(error, BackendYield)
        self.assertEqual(error.usage["total_tokens"], 15)
        self.assertTrue(error.raw["usage_complete"])
        self.assertTrue(any(item.get("type") == "function_call_output" for item in error.history))
        self.assertTrue(any(kind == "tool_finished" for kind, _ in tools.events))

    async def test_timeout_known_usage_is_retained_unknown_usage_flagged(self):
        provider = FakeProvider([tool_response("note", {"text": "Inspected evidence"}), "wait"])
        tools = Tools()
        with self.assertRaises(BackendLimit) as caught:
            await OpenAIBackend(provider).step(AGENT, "review", [], tools,
                                               {**CONFIG, "step_timeout_seconds": 0.5})
        error = caught.exception
        self.assertEqual(error.usage["requests"], 2)
        self.assertEqual(error.usage["total_tokens"], 15)
        self.assertFalse(error.raw["usage_complete"])
        self.assertTrue(any(item.get("type") == "function_call_output" for item in error.history))
        self.assertTrue(any(kind == "model_response" for kind, _ in tools.events))

    async def test_provider_failure_is_blocked_and_error_redacts_key(self):
        tools = Tools()
        secret = "sk-test-never-real-secret"
        provider = FakeProvider([RuntimeError("Provider unavailable " + secret)])
        with patch.dict(os.environ, {"OPENAI_API_KEY": secret}):
            with self.assertRaises(BackendBlocked) as caught:
                await OpenAIBackend(provider).step(AGENT, "review", [], tools, CONFIG)
        self.assertNotIn(secret, caught.exception.reason)
        self.assertEqual(caught.exception.usage["requests"], 1)
        self.assertFalse(caught.exception.raw["usage_complete"])

    async def test_all_tool_object_schemas_are_strict(self):
        tools, output = _make_sdk_tools(sdk, Tools())

        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False)
                    self.assertEqual(set(node.get("required", [])),
                                     set(node.get("properties", {})))
                for value in node.values():
                    check(value)
            elif isinstance(node, list):
                for value in node:
                    check(value)

        for tool in tools:
            self.assertTrue(tool.strict_json_schema)
            check(tool.params_json_schema)
        check(sdk.AgentOutputSchema(output).json_schema())

    async def test_bad_path_is_recoverable_and_audited(self):
        class RejectedPathTools(Tools):
            def read_file(self, path, offset=0, limit=60000):
                raise ValueError("Path leaves private workspace")
        tools = RejectedPathTools()
        provider = FakeProvider([
            tool_response("read_file", {"path": "../production", "offset": 0, "limit": 100}),
            final_response(),
        ])
        result = await OpenAIBackend(provider).step(AGENT, "review", [], tools, CONFIG)
        self.assertEqual(result["output"]["status"], "COMPLETED")
        outputs = [item for item in result["history"]
                   if item.get("type") == "function_call_output"]
        self.assertEqual(json.loads(outputs[0]["output"])["status"], "BLOCKED")
        self.assertTrue(any(kind == "tool_validation_error" for kind, _ in tools.events))

    async def test_checkpoint_contains_completed_tools_before_next_model_request(self):
        tools = Tools()
        provider = FakeProvider([tool_response("note", {"text": "Observation"}), "wait"])
        with self.assertRaises(BackendLimit):
            await OpenAIBackend(provider).step(AGENT, "review", [], tools,
                                               {**CONFIG, "step_timeout_seconds": 0.5})
        checkpoints = [data["history"] for kind, data in tools.events
                       if kind == "history_checkpoint"]
        self.assertTrue(any(item.get("type") == "function_call_output"
                            and json.loads(item["output"]).get("recorded") is True
                            for item in checkpoints[-1]), checkpoints[-1])

    def test_sdk_doctor_needs_no_key(self):
        with patch.dict(os.environ, {}, clear=True):
            result = check_sdk()
        self.assertTrue(result["compatible"])
        self.assertFalse(result["network_tested"])

    async def test_host_budget_stops_before_any_model_request(self):
        class BudgetTools(Tools):
            def check_model_budget(self):
                return "Global token budget reached"
        provider = FakeProvider([])
        with self.assertRaises(BackendLimit) as caught:
            await OpenAIBackend(provider).step(AGENT, "review", [], BudgetTools(), CONFIG)
        self.assertEqual(len(provider.model.calls), 0)
        self.assertEqual(caught.exception.usage["requests"], 0)
        self.assertTrue(caught.exception.usage_complete)

    async def test_host_budget_stops_next_request_preserving_known_usage(self):
        class BudgetTools(Tools):
            def __init__(self):
                super().__init__()
                self.checks = 0

            def check_model_budget(self):
                self.checks += 1
                return "Global token budget reached" if self.checks > 1 else None
        provider = FakeProvider([tool_response("note", {"text": "Evidence audited"})])
        with self.assertRaises(BackendLimit) as caught:
            await OpenAIBackend(provider).step(AGENT, "review", [], BudgetTools(), CONFIG)
        self.assertEqual(len(provider.model.calls), 1)
        self.assertEqual(caught.exception.usage["requests"], 1)
        self.assertEqual(caught.exception.usage["total_tokens"], 15)
        self.assertTrue(caught.exception.usage_complete)


if __name__ == "__main__":
    unittest.main()
