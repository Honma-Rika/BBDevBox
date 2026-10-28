"""Comparable metrics; errors stay in denominators and repeats are never cherry-picked."""
import html
import json
import math
from copy import deepcopy
from pathlib import Path

import yaml


def metrics(rows):
    completed = [r for r in rows if r["status"] in {"passed", "failed", "error"}]
    n = len(completed)
    successes = sum(r["status"] == "passed" for r in completed)
    p = successes / n if n else None
    ci = None
    if n:
        z = 1.96
        center = (p + z * z / (2 * n)) / (1 + z * z / n)
        radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        ci = [max(0, center - radius), min(1, center + radius)]
    grouped = {}
    timed = [r for r in completed if r["started"] is not None and r["finished"] is not None]
    for row in completed:
        grouped.setdefault(row["task_id"], []).append(row["status"] == "passed")
    return {"scheduled": len(rows), "completed": n, "passed": successes,
            "errors": sum(r["status"] == "error" for r in rows),
            "pending_or_interrupted": len(rows) - n,
            "attempt_pass_rate": p,
            "macro_pass_at_1": sum(sum(v) / len(v) for v in grouped.values()) / len(grouped) if grouped else None,
            "wilson_95": ci,
            "tokens": sum(r["input_tokens"] + r["output_tokens"] for r in rows),
            "estimated_calls": sum(r["estimated_calls"] for r in rows),
            "mean_steps": sum(r["step"] for r in completed) / n if n else None,
            "mean_seconds": sum(r["finished"] - r["started"] for r in timed) / len(timed) if timed else None}


def compare(store, run_ids):
    runs = [store.run(key) for key in run_ids]
    data = [store.attempts(key) for key in run_ids]
    keys = [{(r["task_id"], r["repetition"]) for r in rows} for rows in data]
    common = set.intersection(*keys) if keys else set()
    finished_keys = [{(r["task_id"], r["repetition"]) for r in rows
                      if r["status"] in {"passed", "failed", "error"}} for rows in data]
    common_completed = set.intersection(*finished_keys) if finished_keys else set()
    warnings = []
    if len({r["dataset_hash"] for r in runs}) > 1:
        warnings.append("Dataset fingerprints differ; check task content, not just UUIDs.")
    if any(r["dataset_hash"] == "legacy:unknown" for r in runs):
        warnings.append("Legacy results have unknown dataset/protocol provenance and total-only token usage.")
    if common != common_completed:
        warnings.append("Some common pairs are unfinished; paired metrics use only pairs completed in every run.")
    # Model is the independent variable; the rest of the execution protocol should match.
    protocols = [{k: v for k, v in r["config"].items() if k not in {"model", "workers"}} for r in runs]
    if len({json.dumps(p, sort_keys=True) for p in protocols}) > 1:
        warnings.append("Execution protocols differ (sandbox, memory, prompts, budgets, attempts, or seed).")
    if len({json.dumps(r["prompts"], sort_keys=True) for r in runs}) > 1:
        warnings.append("Initial system prompt profiles differ.")
    if any(r["config"].get("prompt_reload") for r in runs):
        warnings.append("Prompt hot reload enabled; consult prompt_selected events for the actual versions.")
    if len({json.dumps(r["memory_snapshot"]) for r in runs}) > 1:
        warnings.append("Frozen knowledge snapshots differ.")
    if any(r["config"]["memory"]["mode"] == "continual" for r in runs):
        warnings.append("Continual memory can change during evaluation; this is not a frozen baseline.")
    return {"common_attempts": len(common), "common_completed_attempts": len(common_completed),
            "warnings": warnings, "runs": [
        {"id": run["id"], "model": run["config"]["model"]["name"], "status": run["status"],
         "all": metrics(rows),
         "common": metrics([r for r in rows if (r["task_id"], r["repetition"]) in common_completed]),
         "domains": {domain: metrics([r for r in rows if r["domain"] == domain])
                     for domain in sorted({r["domain"] for r in rows})}}
        for run, rows in zip(runs, data)]}


def export_legacy(store, run_id, path):
    groups = {}
    for row in store.attempts(run_id):
        result = groups.setdefault(row["task_id"], {"success_flag": [], "success_rounds": [],
                                                    "total_rounds": [], "total_tokens": []})
        result["success_flag"].append(True if row["status"] == "passed" else False if row["status"] == "failed"
                                      else None)
        result["success_rounds"].append(row["step"] if row["status"] == "passed" else 0)
        result["total_rounds"].append(row["step"])
        result["total_tokens"].append(row["input_tokens"] + row["output_tokens"])
    Path(path).write_text(yaml.safe_dump([{"uuid": key, "result": value} for key, value in groups.items()],
                                         allow_unicode=True))


def import_legacy(store, path, label, duplicates="error"):
    if duplicates not in {"error", "concat"}:
        raise ValueError("duplicates must be error or concat")
    raw = yaml.safe_load(Path(path).read_text())
    tasks = []
    parsed = []
    if not isinstance(raw, list) or not raw:
        raise ValueError("Legacy results must be a nonempty YAML list")
    seen = {}
    duplicate_count = 0
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("uuid"), str):
            raise ValueError("Legacy records require a string UUID")
        if row["uuid"] in seen and duplicates == "error":
            raise ValueError("Duplicate UUID in legacy results; explicitly use --duplicates concat to retain all")
        result = row["result"]
        flags = result["success_flag"]
        if not flags or any(flag is not None and not isinstance(flag, bool) for flag in flags):
            raise ValueError("Legacy success_flag must contain booleans or null")
        for key in ("total_rounds", "total_tokens"):
            if len(result[key]) != len(flags) or any(not isinstance(v, int) or v < 0 for v in result[key]):
                raise ValueError(f"Invalid legacy array {key}")
        if row["uuid"] in seen:
            duplicate_count += 1
            previous = seen[row["uuid"]]["result"]
            for key in ("success_flag", "total_rounds", "total_tokens"):
                previous[key].extend(result[key])
        else:
            copied = deepcopy(row)
            seen[row["uuid"]] = copied
            parsed.append(copied)
            tasks.append({"uuid": row["uuid"], "subdomain": row.get("subdomain", "legacy")})
    # Use a uniform allocation and remove unused rows for variable repetition counts.
    from .config import Config
    config = Config().as_dict()
    config["model"]["name"] = label
    config["attempts"] = max(len(r["result"]["success_flag"]) for r in parsed)
    run_id = store.new_run(config, "legacy:unknown", tasks, {}, [])
    store.event(run_id, None, "legacy_import", {"source": str(path), "records": len(raw),
                                               "duplicate_records": duplicate_count,
                                               "duplicate_policy": duplicates})
    by_id = {r["uuid"]: r for r in parsed}
    for row in store.attempts(run_id):
        item = by_id[row["task_id"]]["result"]
        n = row["repetition"]
        if n >= len(item["success_flag"]):
            with store.connect() as db:
                db.execute("DELETE FROM attempts WHERE id=?", (row["id"],))
            continue
        flag = item["success_flag"][n]
        store.event(run_id, row["id"], "legacy_imported", status="error" if flag is None else
                    "passed" if flag else "failed", step=item["total_rounds"][n],
                    input_tokens=item["total_tokens"][n], estimated_calls=1)
    store.finish_run(run_id, "imported")
    return run_id


def write_report(result, path):
    payload = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    bars = []
    for run in result["runs"]:
        p = run["common"]["macro_pass_at_1"]
        width = 100 * p if p is not None else 0
        bars.append(f'<p>{html.escape(run["model"])} · {html.escape(run["id"])}</p>'
                    f'<div class="track"><div class="bar" style="width:{width}%">{width:.1f}%</div></div>')
    warnings = "".join(f"<li>{html.escape(w)}</li>" for w in result["warnings"])
    content = ('<!doctype html><meta charset="utf-8"><title>BBDevBox comparison</title>'
               '<style>body{font:16px system-ui;max-width:1000px;margin:50px auto;background:#101725;color:#edf2ff}'
               '.track{background:#253248;height:32px;border-radius:5px}.bar{background:#277c70;'
               'height:32px;min-width:55px;line-height:32px}pre{white-space:pre-wrap}li{color:#f0c483}</style>'
               '<h1>BBDevBox · benchmark comparison</h1><p>Macro pass@1 on common task/repetition pairs. '
               'Incomplete attempts are reported separately. Wilson intervals treat repeats as independent '
               'and are descriptive only.</p><ul>' + warnings + '</ul>' + ''.join(bars) +
               '<details><summary>Metrics and protocol warnings</summary><pre>' + payload + '</pre></details>')
    Path(path).write_text(content, encoding="utf-8")
