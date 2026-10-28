import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

from .dataset import fingerprint
from .harness import Budget, BudgetExceeded, Harness
from .knowledge import Knowledge
from .prompts import load_profiles
from .sandbox import Cancelled, check_container_runtime, create_sandbox


def run_benchmark(store, config, tasks, resume=None, model_factory=None, on_start=None):
    config.validate()
    check_container_runtime(config.sandbox)
    profiles = load_profiles(config.prompt_file)
    knowledge = Knowledge(store, config.memory.collection)
    digest = fingerprint(tasks)
    if resume:
        store.resume(resume, config.as_dict(), digest, profiles)
        run_id = resume
        snapshot = store.run(run_id)["memory_snapshot"]
    else:
        snapshot = knowledge.snapshot() if config.memory.mode != "off" else []
        run_id = store.new_run(config.as_dict(), digest, [asdict(t) for t in tasks], profiles, snapshot)
    if on_start:
        on_start(run_id)
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(2):
            store.heartbeat(run_id)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    by_id = {t.uuid: t for t in tasks}

    def attempt(row):
        aid = row["id"]
        task = by_id[row["task_id"]].render(config.seed, row["repetition"])
        workdir = store.root / run_id / aid / uuid.uuid4().hex[:8]
        workdir.mkdir(parents=True)
        budget = Budget(config.agent, lambda: store.cancelled(run_id))
        budget.steps = row["step"]
        budget.input_tokens, budget.output_tokens = row["input_tokens"], row["output_tokens"]
        budget.estimated_calls = row["estimated_calls"]

        def check_cancel():
            budget.check()
            return False

        sandbox = create_sandbox(config.sandbox, workdir, check_cancel)
        if config.sandbox.backend != "local":
            (workdir / "sandbox.json").write_text(json.dumps({"backend": config.sandbox.backend,
                                                            "name": sandbox.name, "image": sandbox.image}))
        (workdir / "task.json").write_text(json.dumps(asdict(task), ensure_ascii=False))
        store.event(run_id, aid, "attempt_started", {"workdir": str(workdir)},
                    status="running", started=row["started"] or time.time(), phase="setup", agent="main")
        status, error, verification = "error", None, None
        try:
            budget.check()
            sandbox.start(task)
            store.event(run_id, aid, "sandbox_ready", phase="idle")
            agent_error = None
            try:
                harness = Harness(config, task, sandbox, store, run_id, aid, workdir, knowledge,
                                  snapshot, profiles, model=model_factory() if model_factory else None,
                                  budget=budget)
                harness.run_graph(task.problem)
            except BudgetExceeded as exc:
                store.event(run_id, aid, "budget_exhausted", {"error": str(exc)})
                error = str(exc)
            except Cancelled:
                raise
            except Exception as exc:
                agent_error = f"{type(exc).__name__}: {exc}"
                store.event(run_id, aid, "agent_error", {"error": agent_error})
            if store.cancelled(run_id):
                raise Cancelled("Run cancelled")
            # Grading has a separate command timeout and does not invoke the agent or consume its budget.
            # Preserve verification even when the agent reaches its time/token limit.
            sandbox.cancelled = lambda: store.cancelled(run_id)
            store.event(run_id, aid, "verification_started", phase="verification")
            result = sandbox.execute(task.verification, config.sandbox.command_timeout)
            verification = json.dumps(result.as_dict(), ensure_ascii=False)
            (workdir / "verification.json").write_text(verification)
            passed = result.exit_code == 0 and not result.timed_out and not result.output_limited
            status = "passed" if passed else "error" if agent_error else "failed"
            error = agent_error or error
            store.event(run_id, aid, "verification_finished", {"exit_code": result.exit_code,
                                                               "passed": passed})
        except Cancelled as exc:
            status, error = "cancelled", str(exc)
        except BudgetExceeded as exc:
            status, error = "failed", str(exc)
        except Exception as exc:
            status, error = "error", f"{type(exc).__name__}: {exc}"
        finally:
            store.event(run_id, aid, "cleanup_started", phase="cleanup")
            try:
                sandbox.close()
            except Exception as exc:
                store.event(run_id, aid, "cleanup_error", {"error": str(exc)})
                error = (error + "; " if error else "") + f"Cleanup: {exc}"
            store.event(run_id, aid, "attempt_finished", {"status": status, "error": error},
                        status=status, finished=time.time(), phase="finished", error=error,
                        verification=verification, step=budget.steps, input_tokens=budget.input_tokens,
                        output_tokens=budget.output_tokens, estimated_calls=budget.estimated_calls)

    pool = ThreadPoolExecutor(max_workers=config.workers)
    futures = []
    try:
        futures = [pool.submit(attempt, row) for row in store.attempts(run_id) if row["status"] == "pending"]
        for future in as_completed(futures):
            future.result()
    except KeyboardInterrupt:
        store.cancel(run_id)
        for future in futures:
            future.cancel()
    except BaseException:
        store.cancel(run_id)
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        for row in store.attempts(run_id):
            if row["status"] == "pending":
                store.event(run_id, row["id"], "attempt_cancelled", status="cancelled", finished=time.time())
        stop.set()
        thread.join(timeout=3)
        rows = store.attempts(run_id)
        state = "cancelled" if store.cancelled(run_id) else "error" if any(
            r["status"] in {"error", "running", "interrupted"} for r in rows) else "completed"
        store.finish_run(run_id, state)
    return run_id
