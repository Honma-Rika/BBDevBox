"""All model-authored OS commands cross this interface; no host tools reach containers."""
import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from .config import SandboxConfig
from .dataset import Task


class Cancelled(RuntimeError):
    pass


class SandboxError(RuntimeError):
    pass


def check_container_runtime(config: SandboxConfig):
    """Check shared prerequisites before creating a run or scheduling any attempts."""
    if config.backend == "local":
        return
    engine = config.backend
    if not shutil.which(engine):
        raise SandboxError(
            f"{engine} executable not found on PATH. Install and start "
            f"{'Docker Desktop (macOS) or Docker Engine (Linux)' if engine == 'docker' else 'Podman'}; "
            f"then run '{engine} info' successfully in the same terminal before retrying."
        )
    result = process([engine, "info"], 30)
    if result.exit_code:
        detail = (result.stderr or result.stdout).strip()[:1500]
        raise SandboxError(
            f"{engine} runtime is unavailable ('{engine} info' failed). "
            f"Start the runtime and check its context/socket permissions. {detail}"
        )


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    output_limited: bool = False

    def as_dict(self):
        return asdict(self)


class Sandbox(Protocol):
    def start(self, task: Task): ...
    def execute(self, command: str, timeout: float | None = None) -> CommandResult: ...
    def close(self): ...


def process(argv, timeout, cwd=None, cancelled: Callable[[], bool] = lambda: False,
            env=None, max_bytes=8_000_000, groups=None):
    """Drain to files, cap output, reap the host process group on every exceptional path."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        if groups is not None:
            groups.append(proc.pid)
        deadline = time.monotonic() + timeout
        timed_out = limited = False
        try:
            while proc.poll() is None:
                if cancelled():
                    raise Cancelled("Cancellation requested")
                timed_out = time.monotonic() >= deadline
                limited = os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > max_bytes
                if timed_out or limited:
                    break
                time.sleep(0.05)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc.wait()
        out.seek(0)
        err.seek(0)
        return CommandResult(out.read(max_bytes).decode(errors="replace"),
                             err.read(max_bytes).decode(errors="replace"),
                             124 if timed_out else 125 if limited else proc.returncode, timed_out, limited)


class ContainerSandbox:
    def __init__(self, config: SandboxConfig, workdir: Path, cancelled=lambda: False):
        self.config = config
        self.workdir = workdir
        self.cancelled = cancelled
        self.engine = config.backend
        self.name = f"bbdevbox-{uuid.uuid4().hex}"
        self.image = self.name + ":task"
        self.alive = False
        self._build_attempted = False
        self._run_attempted = False

    def _engine(self, args, timeout, cancel=True):
        return process([self.engine, *args], timeout, cancelled=self.cancelled if cancel else lambda: False)

    def start(self, task):
        if not shutil.which(self.engine):
            raise SandboxError(f"{self.engine} executable not found")
        if not task.dockerfile_content.strip():
            raise SandboxError("Container tasks require dockerfile_content")
        # Do not expose the repository or run artifacts as the Docker build context.
        build_dir = self.workdir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)
        dockerfile = task.dockerfile_content
        if not any(line.strip().upper().startswith(("CMD ", "ENTRYPOINT "))
                   for line in dockerfile.splitlines()):
            dockerfile += '\nCMD ["tail", "-f", "/dev/null"]\n'
        (build_dir / "Dockerfile").write_text(dockerfile)
        self._build_attempted = True
        result = self._engine(["build", "--tag", self.image, str(build_dir)], self.config.build_timeout)
        log_path = self.workdir / "build.log"
        log_text = result.stdout + result.stderr
        log_path.write_text(log_text, encoding="utf-8")
        if result.exit_code:
            detail = (result.stderr or result.stdout).strip()[-6000:] or "No build output returned."
            raise SandboxError(f"Image build failed ({result.exit_code}); log: {log_path.resolve()}\n{detail}")
        args = ["run", "--detach", "--name", self.name, "--label", "bbdevbox.managed=true",
                "--network", self.config.network, "--memory", self.config.memory,
                "--cpus", str(self.config.cpus), "--pids-limit", str(self.config.pids_limit),
                "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
                # Ordinary package installation and service configuration still work as container root.
                "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER",
                "--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "NET_BIND_SERVICE"]
        if self.config.runtime:
            args += ["--runtime", self.config.runtime]
        args.append(self.image)
        self._run_attempted = True
        result = self._engine(args, 30)
        if result.exit_code:
            raise SandboxError(f"Container startup failed: {result.stderr[:2000]}")
        self.alive = True
        result = self._engine(["exec", self.name, "bash", "-lc", "command -v timeout"], 15)
        if result.exit_code:
            raise SandboxError("Image must remain running and provide bash and GNU timeout")

    def execute(self, command, timeout=None):
        if not self.alive:
            raise SandboxError("Container is not available")
        seconds = timeout or self.config.command_timeout
        # GNU timeout terminates the command group *inside* the sandbox. Killing docker exec alone does not.
        try:
            result = self._engine(["exec", self.name, "timeout", "--signal=TERM", "--kill-after=2s",
                                   f"{seconds}s", "bash", "-lc", command], seconds + 5)
        except BaseException:
            self._engine(["kill", self.name], 10, cancel=False)
            self.alive = False
            raise
        if result.exit_code in (124, 137) or result.timed_out or result.output_limited:
            # Stop the entire container so background descendants cannot survive a timeout.
            self._engine(["kill", self.name], 10, cancel=False)
            self.alive = False
            result.timed_out = result.timed_out or result.exit_code in (124, 137)
        return result

    def close(self):
        failures = []
        # Only this attempt's named resources; never prune shared images, volumes, or containers.
        resources = []
        if self._run_attempted:
            resources.append((["rm", "--force", self.name], "_run_attempted"))
        if self._build_attempted:
            resources.append((["image", "rm", "--force", self.image], "_build_attempted"))
        for args, flag in resources:
            try:
                result = self._engine(args, 30, cancel=False)
                if result.exit_code and "no such" not in result.stderr.lower():
                    failures.append(result.stderr[:1000])
                else:
                    setattr(self, flag, False)
            except OSError as exc:
                failures.append(str(exc))
        self.alive = False
        if failures:
            raise SandboxError("Cleanup incomplete: " + "; ".join(failures))


class LocalSandbox:
    """Trusted test fixture executor. This is deliberately NOT a security boundary."""
    def __init__(self, config, workdir, cancelled=lambda: False):
        if not config.allow_local:
            raise SandboxError("Host execution requires allow_local=true")
        self.config = config
        self.workdir = workdir / "workspace"
        self.cancelled = cancelled
        self.temp = None
        self.groups = []

    def start(self, task):
        if task.dockerfile_content.strip():
            raise SandboxError("local cannot reproduce Dockerfiles; use a local fixture with setup")
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="bbdevbox-local-")
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.workdir),
                    "TMPDIR": self.temp.name, "LANG": "C.UTF-8"}
        if task.setup:
            result = self.execute(task.setup)
            if result.exit_code:
                raise SandboxError(f"Local setup failed: {result.stderr}")

    def execute(self, command, timeout=None):
        return process(["bash", "--noprofile", "--norc", "-c", command],
                       timeout or self.config.command_timeout, cwd=self.workdir, env=self.env,
                       cancelled=self.cancelled, groups=self.groups)

    def close(self):
        for group in self.groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.temp:
            self.temp.cleanup()


def create_sandbox(config, workdir, cancelled=lambda: False) -> Sandbox:
    if config.backend == "local":
        return LocalSandbox(config, workdir, cancelled)
    return ContainerSandbox(config, workdir, cancelled)
