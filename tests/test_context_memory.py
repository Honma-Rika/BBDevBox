from dataclasses import asdict

import pytest
from conftest import answer, tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from bbdevbox.config import ContextConfig
from bbdevbox.context import Artifacts, ContextManager, size
from bbdevbox.dataset import Task
from bbdevbox.knowledge import Knowledge


def test_offload_unicode_chunking_and_path_confinement(tmp_path):
    artifacts = Artifacts(tmp_path, 4)
    ref = artifacts.dump("你好世界abc", "test")
    assert artifacts.read(ref["ref"], 0) == "你好世界"
    assert artifacts.read(ref["ref"], 1) == "abc"
    for bad in ("../secret", "/etc/passwd", "a" * 33):
        with pytest.raises(ValueError):
            artifacts.read(bad)
    with pytest.raises(ValueError):
        artifacts.read(ref["ref"], 2)


def test_compaction_preserves_tool_call_pairs_and_full_archive(tmp_path):
    cfg = ContextConfig(max_input_tokens=8000, summary_chars=1000, keep_recent_turns=2)
    artifacts = Artifacts(tmp_path, 1000)
    events = []
    manager = ContextManager(cfg, artifacts, lambda k, p: events.append((k, p)))
    messages = [HumanMessage(content="original task")]
    for n in range(10):
        messages += [answer(tools=[tool("execute", {"command": "echo test"}, str(n))]),
                     ToolMessage(content="a" * 900, tool_call_id=str(n))]
    result = manager.compact(messages, 1000)
    assert result[0].content == "original task"
    assert size(result) + 1000 <= cfg.max_input_tokens
    for n, message in enumerate(result):
        if isinstance(message, ToolMessage):
            assert isinstance(result[n - 1], AIMessage)
            assert message.tool_call_id == result[n - 1].tool_calls[0]["id"]
    assert events[-1][0] == "context_compacted"
    assert "echo test" in artifacts.read(events[-1][1]["ref"], 0)


def test_llm_summary_uses_bounded_chunks_and_is_audited(tmp_path):
    chunks = []
    cfg = ContextConfig(max_input_tokens=6000, chunk_chars=1000, keep_recent_turns=1, llm_summary=True)
    manager = ContextManager(cfg, Artifacts(tmp_path), lambda *_: None,
                             lambda text: chunks.append(text) or "remember filenames")
    messages = [HumanMessage(content="task")]
    for n in range(6):
        messages += [answer(tools=[tool("execute", {"command": "pwd"}, str(n))]),
                     ToolMessage(content="z" * 1500, tool_call_id=str(n))]
    result = manager.compact(messages)
    assert chunks and max(map(len, chunks)) <= 1000
    assert "remember filenames" in result[1].content


def test_memory_approval_provenance_frozen_snapshot_and_self_exclusion(store, config):
    tasks = [asdict(Task("source", "nothing", "true")), asdict(Task("failure", "nothing", "false"))]
    key = store.new_run(config.as_dict(), "hash", tasks, {}, [])
    rows = {r["task_id"]: r for r in store.attempts(key)}
    store.event(key, rows["source"]["id"], "test", status="passed")
    knowledge = Knowledge(store)
    candidate = knowledge.propose("source", "general", "nginx diagnose configuration", rows["source"]["id"])
    frozen = knowledge.snapshot()
    assert knowledge.search("nginx", "other") == []
    path = knowledge.promote(candidate)
    assert path.name == "SKILL.md" and "source_task=source" in path.read_text()
    assert knowledge.search("nginx", "other", frozen) == []
    assert knowledge.search("nginx", "source") == []
    assert knowledge.search("nginx", "other")[0]["id"] == candidate
    assert Knowledge(store, "isolated").search("nginx", "other") == []
    bad = knowledge.propose("failure", "general", "nginx", rows["failure"]["id"])
    with pytest.raises(ValueError, match="verification-passed"):
        knowledge.promote(bad)
