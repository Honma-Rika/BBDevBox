import pytest
import yaml

from bbdevbox.config import Config
from bbdevbox.dataset import load_tasks
from bbdevbox.report import compare, export_legacy, import_legacy, metrics, write_report


def test_historical_results_preserve_all_repetitions_and_errors(store, tmp_path):
    path = tmp_path / "old.yaml"
    path.write_text(yaml.safe_dump([{"uuid": "x", "result": {
        "success_flag": [True, False, None], "total_rounds": [1, 2, 0], "total_tokens": [10, 20, 0]}}]))
    key = import_legacy(store, path, "old-model")
    result = compare(store, [key])
    m = result["runs"][0]["all"]
    assert m["completed"] == 3 and m["attempt_pass_rate"] == 1 / 3
    assert m["tokens"] == 30 and m["errors"] == 1
    dest = tmp_path / "roundtrip.yaml"
    export_legacy(store, key, dest)
    assert yaml.safe_load(dest.read_text())[0]["result"]["success_flag"] == [True, False, None]
    report = tmp_path / "report.html"
    write_report(result, report)
    assert "33.3%" in report.read_text()


def test_empty_metrics_are_unknown_not_zero():
    assert metrics([])["macro_pass_at_1"] is None


def test_duplicate_legacy_records_require_explicit_policy_and_never_best_of(store, tmp_path):
    path = tmp_path / "duplicates.yaml"
    def row(flag):
        return {"uuid": "same", "result": {"success_flag": [flag], "total_rounds": [2], "total_tokens": [20]}}
    path.write_text(yaml.safe_dump([row(False), row(True)]))
    with pytest.raises(ValueError, match="Duplicate UUID"):
        import_legacy(store, path, "history")
    key = import_legacy(store, path, "history", duplicates="concat")
    rows = store.attempts(key)
    assert len(rows) == 2
    assert metrics(rows)["attempt_pass_rate"] == 0.5
    assert metrics(rows)["tokens"] == 40


def test_comparison_uses_pairs_completed_in_every_run(store, config):
    from dataclasses import asdict

    from bbdevbox.dataset import Task
    tasks = [asdict(Task("a", "nothing", "true")), asdict(Task("b", "nothing", "true"))]
    first = store.new_run(config.as_dict(), "hash", tasks, {}, [])
    second = store.new_run(config.as_dict(), "hash", tasks, {}, [])
    for row in store.attempts(first):
        store.event(first, row["id"], "test", status="passed")
    store.event(second, store.attempts(second)[0]["id"], "test", status="failed")
    result = compare(store, [first, second])
    assert result["common_attempts"] == 2 and result["common_completed_attempts"] == 1
    assert result["runs"][0]["common"]["completed"] == result["runs"][1]["common"]["completed"] == 1
    assert any("unfinished" in w for w in result["warnings"])


def test_config_rejects_typos_and_unsafe_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("typo: true")
    with pytest.raises(ValueError, match="Unknown"):
        Config.load(path)
    path.write_text("sandbox:\n  backend: local")
    with pytest.raises(ValueError, match="HOST"):
        Config.load(path)
    path.write_text("workers: 0")
    with pytest.raises(ValueError, match="positive"):
        Config.load(path)


def test_original_dataset_is_compatible():
    tasks = load_tasks("data/[TerminalBenchVer]uuid_bash_agent_questions.yaml")
    assert len(tasks) > 100
    assert len({t.uuid for t in tasks}) == len(tasks)
