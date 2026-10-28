import json

import httpx
import langchain_openai

from bbdevbox.dataset import Task
from bbdevbox.harness import create_model
from bbdevbox.runner import run_benchmark


def test_real_provider_adapter_tool_serialization_and_usage(store, config, monkeypatch):
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        message = {"role": "assistant", "content": "done"}
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "provider-call",
                       "type": "function", "function": {"name": "execute",
                       "arguments": json.dumps({"command": "touch done"})}}]}
        return httpx.Response(200, json={"id": "completion-test", "object": "chat.completion",
            "created": 0, "model": "fixture", "choices": [{"index": 0, "message": message,
            "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}})
    original = langchain_openai.ChatOpenAI
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kw: original(**kw, http_client=client))
        config.model.base_url = "http://fixture.invalid/v1"
        key = run_benchmark(store, config, [Task("provider", "create done", "test -f done")],
                            model_factory=lambda: create_model(config.model))
    row = store.attempts(key)[0]
    assert row["status"] == "passed", row["error"]
    assert row["input_tokens"] == 22 and row["output_tokens"] == 10
    assert requests[0]["tools"][0]["function"]["name"] == "execute"
    assert requests[1]["messages"][-1]["tool_call_id"] == "provider-call"
    assert requests[0].get("max_tokens", requests[0].get("max_completion_tokens")) <= config.model.max_output_tokens


def test_transient_provider_retry_is_visible_and_budgeted(store, config, monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"message": "retry later", "type": "rate_limit"}})
        return httpx.Response(200, json={"id": "retry-test", "object": "chat.completion",
            "created": 0, "model": "fixture", "choices": [{"index": 0,
            "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
    original = langchain_openai.ChatOpenAI
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kw: original(**kw, http_client=client))
        config.model.base_url = "http://fixture.invalid/v1"
        key = run_benchmark(store, config, [Task("retry", "nothing", "true")])
    row = store.attempts(key)[0]
    assert row["status"] == "passed" and row["step"] == 2
    assert row["estimated_calls"] == 1
    assert any(e["kind"] == "model_retry" and e["payload"]["usage_unknown"] for e in store.events(key))
