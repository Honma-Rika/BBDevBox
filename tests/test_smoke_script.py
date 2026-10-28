import importlib.util
from pathlib import Path

from bbdevbox.sandbox import CommandResult, SandboxError


def load_smoke_script():
    spec = importlib.util.spec_from_file_location("manual_smoke", Path(__file__).resolve().parents[1] /
                                                "test_docker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_preserves_log_and_primary_error_when_cleanup_fails(tmp_path, monkeypatch, capsys):
    script = load_smoke_script()
    class FailedSandbox:
        name, image = "fixture-container", "fixture-image"
        def __init__(self, config, workdir):
            self.workdir = workdir

        def start(self, task):
            (self.workdir / "build.log").write_text("failed to authorize: DeadlineExceeded")
            raise SandboxError("failed to authorize: DeadlineExceeded")

        def close(self):
            raise SandboxError("cleanup diagnostic")
    monkeypatch.setattr(script, "check_container_runtime", lambda _: None)
    monkeypatch.setattr(script, "ContainerSandbox", FailedSandbox)
    assert script.main(["docker", "--artifacts", str(tmp_path)]) == 1
    assert list(tmp_path.glob("*/build.log"))[0].read_text() == "failed to authorize: DeadlineExceeded"
    error = capsys.readouterr().err
    assert "DeadlineExceeded" in error and "cleanup diagnostic" in error and "Diagnostics retained" in error


def test_smoke_success_retains_verification(tmp_path, monkeypatch):
    script = load_smoke_script()
    class ReadySandbox:
        name, image = "fixture-container", "fixture-image"
        def __init__(self, config, workdir):
            pass

        def start(self, task):
            pass

        def execute(self, command):
            return CommandResult("", "", 0)

        def close(self):
            pass
    monkeypatch.setattr(script, "check_container_runtime", lambda _: None)
    monkeypatch.setattr(script, "ContainerSandbox", ReadySandbox)
    assert script.main(["docker", "--artifacts", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*/verification.json"))) == 1
