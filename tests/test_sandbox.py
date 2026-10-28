import time

import pytest

from bbdevbox.config import SandboxConfig
from bbdevbox.dataset import Task
from bbdevbox.sandbox import (
    CommandResult,
    ContainerSandbox,
    LocalSandbox,
    SandboxError,
    check_container_runtime,
    process,
)


def test_missing_runtime_fails_before_creating_run_and_cleanup_is_noop(store, tmp_path, monkeypatch):
    from bbdevbox.config import Config
    from bbdevbox.runner import run_benchmark

    monkeypatch.setattr("bbdevbox.sandbox.shutil.which", lambda _: None)
    with pytest.raises(SandboxError, match="Install and start Docker Desktop"):
        run_benchmark(store, Config(), [Task("one", "work", "true", dockerfile_content="FROM ubuntu")])
    assert store.overview() == []
    sandbox = ContainerSandbox(SandboxConfig(), tmp_path)
    with pytest.raises(SandboxError, match="executable not found"):
        sandbox.start(Task("one", "work", "true"))
    # This used to raise a second FileNotFoundError from docker rm/image rm.
    sandbox.close()


def test_installed_cli_with_unavailable_daemon_has_actionable_error(monkeypatch):
    monkeypatch.setattr("bbdevbox.sandbox.shutil.which", lambda _: "/usr/local/bin/docker")
    monkeypatch.setattr("bbdevbox.sandbox.process", lambda *a, **k: CommandResult(
        "", "Cannot connect to the Docker daemon", 1))
    with pytest.raises(SandboxError, match="Start the runtime.*Cannot connect"):
        check_container_runtime(SandboxConfig())


def test_preflight_uses_selected_runtime_and_local_needs_no_container_cli(monkeypatch):
    calls = []
    monkeypatch.setattr("bbdevbox.sandbox.shutil.which", lambda _: "/usr/bin/podman")
    def info(argv, timeout):
        calls.append(argv)
        return CommandResult("ready", "", 0)
    monkeypatch.setattr("bbdevbox.sandbox.process", info)
    check_container_runtime(SandboxConfig(backend="podman"))
    check_container_runtime(SandboxConfig(backend="local", allow_local=True))
    assert calls == [["podman", "info"]]


def test_failed_build_cleans_only_potential_image(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("bbdevbox.sandbox.shutil.which", lambda _: "/usr/bin/docker")
    sandbox = ContainerSandbox(SandboxConfig(), tmp_path)
    def engine(args, *a, **k):
        calls.append(args)
        return CommandResult("", "build failed", 1) if args[0] == "build" else CommandResult("", "", 0)
    monkeypatch.setattr(sandbox, "_engine", engine)
    with pytest.raises(SandboxError, match="Image build failed") as error:
        sandbox.start(Task("one", "work", "true", dockerfile_content="FROM ubuntu"))
    assert str((tmp_path / "build.log").resolve()) in str(error.value)
    assert "build failed" in str(error.value)
    assert (tmp_path / "build.log").read_text() == "build failed"
    sandbox.close()
    sandbox.close()
    assert ["rm", "--force", sandbox.name] not in calls
    assert calls.count(["image", "rm", "--force", sandbox.image]) == 1


def test_local_refuses_implicit_host_execution_and_dockerfiles(tmp_path):
    with pytest.raises(SandboxError, match="allow_local"):
        LocalSandbox(SandboxConfig(), tmp_path)
    local = LocalSandbox(SandboxConfig(allow_local=True), tmp_path)
    with pytest.raises(SandboxError, match="Dockerfiles"):
        local.start(Task("a", "a", "a", dockerfile_content="FROM ubuntu"))


def test_timeout_kills_descendants_not_just_waiter(tmp_path):
    marker = tmp_path / "marker"
    result = process(["bash", "-c", f"(sleep 0.5; touch '{marker}') & wait"], 0.1)
    assert result.timed_out and result.exit_code == 124
    time.sleep(0.6)
    assert not marker.exists()


def test_container_contract_preserves_cmd_enforces_limits_and_kills_on_timeout(tmp_path, monkeypatch):
    calls = []
    config = SandboxConfig(backend="podman", runtime="runsc")
    sandbox = ContainerSandbox(config, tmp_path)
    monkeypatch.setattr("bbdevbox.sandbox.shutil.which", lambda _: "/bin/podman")
    def engine(args, timeout, cancel=True):
        calls.append(args)
        return CommandResult("", "", 124 if args[0] == "exec" and "timeout" in args else 0)
    monkeypatch.setattr(sandbox, "_engine", engine)
    task = Task("a", "a", "true", dockerfile_content='FROM ubuntu\nCMD ["python3","server.py"]')
    sandbox.start(task)
    assert (tmp_path / "build/Dockerfile").read_text() == task.dockerfile_content
    command = next(c for c in calls if c[0] == "run")
    assert "--runtime" in command and "runsc" in command
    assert "--memory" in command and "--pids-limit" in command
    assert "--privileged" not in command and "--volume" not in command
    assert sandbox.execute("sleep 90").timed_out
    assert ["kill", sandbox.name] in calls
    sandbox.close()
    assert ["rm", "--force", sandbox.name] in calls
    assert not any("prune" in c for c in calls)
