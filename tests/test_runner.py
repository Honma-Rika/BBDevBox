import time
from dataclasses import asdict

import pytest
from conftest import ScriptedModel, answer, tool

from bbdevbox.dataset import Task, fingerprint
from bbdevbox.runner import run_benchmark


def test_actual_graph_executes_shell_and_verifier_is_hidden(store, config):
    task = Task("one", "Create answer.txt containing 42", "test $(cat answer.txt) = 42")
    model = ScriptedModel([answer(tools=[tool("execute", {"command": "printf 42 > answer.txt"})]), answer()])
    key = run_benchmark(store, config, [task], model_factory=lambda: model)
    row = store.attempts(key)[0]
    assert row["status"] == "passed"
    assert (row["step"], row["input_tokens"], row["output_tokens"]) == (2, 14, 6)
    assert task.verification not in str(model.requests)
    assert store.run(key)["status"] == "completed"


def test_verifier_exit_code_not_stdout_or_stderr(store, config):
    tasks = [Task("false", "do nothing", "echo True; exit 1"),
             Task("true", "do nothing", "echo diagnostic >&2; exit 0")]
    config.workers = 2
    key = run_benchmark(store, config, tasks, model_factory=lambda: ScriptedModel([answer()]))
    rows = {r["task_id"]: r for r in store.attempts(key)}
    assert rows["false"]["status"] == "failed"
    assert rows["true"]["status"] == "passed"


def test_last_budgeted_step_still_executes_its_command(store, config):
    config.agent.max_steps = 1
    model = ScriptedModel([answer(tools=[tool("execute", {"command": "touch done"})])])
    key = run_benchmark(store, config, [Task("one", "create done", "test -f done")], model_factory=lambda: model)
    assert store.attempts(key)[0]["status"] == "passed"
    assert len(model.requests) == 1


def test_children_share_environment_and_global_usage(store, config):
    config.agent.multi_agent = True
    model = ScriptedModel([
        answer(tools=[tool("delegate", {"task": "create child.txt", "role": "builder"})]),
        answer(tools=[tool("execute", {"command": "echo child > child.txt"})]),
        answer("child complete"), answer("parent complete")])
    key = run_benchmark(store, config, [Task("child", "create child.txt", "grep -q child child.txt")],
                        model_factory=lambda: model)
    row = store.attempts(key)[0]
    assert row["status"] == "passed"
    assert row["step"] == 4 and row["input_tokens"] + row["output_tokens"] == 40
    events = store.events(key)
    assert any(e["kind"] == "delegation_finished" for e in events)
    assert "create child.txt" not in str(model.requests[1][2:-1])  # no parent transcript in child


def test_delegation_cannot_bypass_step_budget(store, config):
    config.agent.multi_agent = True
    config.agent.max_steps = 2
    model = ScriptedModel([
        answer(tools=[tool("delegate", {"task": "create done"})]),
        answer(tools=[tool("execute", {"command": "echo observed"})])])
    key = run_benchmark(store, config, [Task("one", "create done", "test -f done")], model_factory=lambda: model)
    row = store.attempts(key)[0]
    assert row["status"] == "failed" and row["step"] == 2
    assert any(e["kind"] == "budget_exhausted" for e in store.events(key))


def test_parallel_attempts_are_not_lost(store, config):
    config.workers = 4
    config.attempts = 2
    tasks = [Task(str(n), "create done", "test -f done", setup="touch done") for n in range(8)]
    key = run_benchmark(store, config, tasks, model_factory=lambda: ScriptedModel([answer()]))
    rows = store.attempts(key)
    assert len(rows) == 16 and all(r["status"] == "passed" for r in rows)
    assert store.overview()[0]["tokens"] == 160


def test_estimates_marked_and_model_error_not_task_failure(store, config):
    key = run_benchmark(store, config, [Task("one", "nothing", "exit 1")],
                        model_factory=lambda: ScriptedModel([answer(usage=False)]))
    assert store.attempts(key)[0]["estimated_calls"] == 1
    other = run_benchmark(store, config, [Task("two", "nothing", "exit 1")],
                          model_factory=lambda: ScriptedModel([RuntimeError("provider unavailable")]))
    assert store.attempts(other)[0]["status"] == "error"


def test_stop_during_model_response_prevents_execution(store, config):
    def cancel(_):
        store.cancel(store.overview()[0]["id"])
        return answer(tools=[tool("execute", {"command": "touch should-not-exist"})])
    key = run_benchmark(store, config, [Task("one", "nothing", "exit 0")],
                        model_factory=lambda: ScriptedModel([cancel]))
    assert store.attempts(key)[0]["status"] == "cancelled"
    assert not any(e["kind"] == "command_started" for e in store.events(key))


def test_recovery_resume_preserves_completed_attempt(store, config):
    tasks = [Task("a", "nothing", "true"), Task("b", "nothing", "true")]
    key = store.new_run(config.as_dict(), fingerprint(tasks), [asdict(t) for t in tasks], {}, [])
    first, second = store.attempts(key)
    store.event(key, first["id"], "test", status="passed", step=5)
    store.event(key, second["id"], "test", status="running", step=9)
    with pytest.raises(ValueError, match="expired heartbeat"):
        store.recover(key)
    with store.connect() as db:
        db.execute("UPDATE runs SET heartbeat=? WHERE id=?", (time.time() - 60, key))
    store.recover(key)
    run_benchmark(store, config, tasks, resume=key, model_factory=lambda: ScriptedModel([answer()]))
    rows = store.attempts(key)
    assert rows[0]["step"] == 5 and rows[1]["step"] == 10
    config.seed = 99
    with pytest.raises(ValueError, match="identical"):
        run_benchmark(store, config, tasks, resume=key)


def test_hot_reload_and_attempt_prompt_updates_are_audited(store, config, tmp_path):
    from bbdevbox.prompts import set_profile
    path = tmp_path / "prompts.yaml"
    set_profile(path, "initial profile")
    config.prompt_file, config.prompt_reload = str(path), True
    config.agent.allow_prompt_updates = True
    def first(_):
        set_profile(path, "updated profile")
        return answer(tools=[tool("update_prompt", {"instructions": "Inspect files first"})])
    model = ScriptedModel([first, answer()])
    key = run_benchmark(store, config, [Task("one", "nothing", "true")], model_factory=lambda: model)
    versions = [e["payload"]["sha256"] for e in store.events(key) if e["kind"] == "prompt_selected"]
    assert len(set(versions)) == 2
    assert "updated profile" in model.requests[1][0].content
    assert "Inspect files first" in model.requests[1][0].content
    assert "You cannot see or edit" in model.requests[1][0].content


def test_task_substitution_deterministic_and_no_arbitrary_template_expansion():
    task = Task("a", "${random_num} $HOME", "test ${random_num} = $random_num")
    assert task.render(42, 0) == task.render(42, 0)
    assert "$HOME" in task.render(42, 0).problem
    assert task.render(42, 0) != task.render(42, 1)


def test_heartbeat_advances_during_inflight_model_call(store, config):
    def pending(_):
        key = store.overview()[0]["id"]
        previous = store.run(key)["heartbeat"]
        row = store.attempts(key)[0]
        assert row["phase"] == "model" and row["step"] == 1
        time.sleep(2.2)
        assert store.run(key)["heartbeat"] > previous
        return answer()
    key = run_benchmark(store, config, [Task("heartbeat", "nothing", "true")],
                        model_factory=lambda: ScriptedModel([pending]))
    assert store.attempts(key)[0]["status"] == "passed"
