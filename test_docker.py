"""Manual container smoke test without an LLM; preserve diagnostics under runs/smoke."""
import argparse
import json
import sys
import uuid
from pathlib import Path

from bbdevbox.config import SandboxConfig
from bbdevbox.dataset import load_tasks
from bbdevbox.sandbox import ContainerSandbox, SandboxError, check_container_runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", nargs="?", choices=["docker", "podman"], default="docker")
    parser.add_argument("--artifacts", default="runs/smoke", help="Persistent diagnostic directory")
    args = parser.parse_args(argv)
    config = SandboxConfig(backend=args.backend)
    try:
        check_container_runtime(config)
    except (SandboxError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    task = load_tasks(str(Path(__file__).resolve().parent / "examples/smoke.yaml"))[0]
    workdir = Path(args.artifacts).resolve() / f"{args.backend}-{uuid.uuid4().hex[:12]}"
    workdir.mkdir(parents=True)
    print(f"Smoke artifacts: {workdir}", flush=True)
    sandbox = ContainerSandbox(config, workdir)
    (workdir / "sandbox.json").write_text(json.dumps({"backend": args.backend, "name": sandbox.name,
                                                    "image": sandbox.image}))
    failed = False
    try:
        sandbox.start(task)
        result = sandbox.execute("printf '42\\n' > /workspace/answer.txt")
        if result.exit_code:
            raise SandboxError(f"File creation failed: {result.as_dict()}")
        result = sandbox.execute(task.verification)
        (workdir / "verification.json").write_text(json.dumps(result.as_dict()))
        if result.exit_code or result.timed_out or result.output_limited:
            raise SandboxError(f"Verification failed: {result.as_dict()}")
    except (SandboxError, OSError) as exc:
        failed = True
        print(f"Smoke failed: {exc}", file=sys.stderr)
    finally:
        try:
            sandbox.close()
        except (SandboxError, OSError) as exc:
            failed = True
            print(f"Cleanup failed: {exc}", file=sys.stderr)
    if failed:
        print(f"Diagnostics retained: {workdir}", file=sys.stderr)
        return 1
    print("Container smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
