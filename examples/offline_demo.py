"""No API key or container needed: actual LangGraph execution with scripted model fixtures.

Run from the repository root: python examples/offline_demo.py
The labels explicitly identify fixtures; these scores are not model evaluations.
"""
from langchain_core.messages import AIMessage

from bbdevbox.config import Config
from bbdevbox.dataset import load_tasks
from bbdevbox.report import compare, write_report
from bbdevbox.runner import run_benchmark
from bbdevbox.store import Store


class FixtureModel:
    def __init__(self, correct=True):
        self.correct = correct
        self.called = False

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kwargs):
        calls = []
        if not self.called:
            task = messages[-1].content
            command = "awk '{print $1*2}' input.txt > answer.txt" if "input.txt" in task else (
                "awk -F, 'NR>1{s+=$2}END{print s}' numbers.csv > total.txt")
            if not self.correct and "input.txt" in task:
                command = "printf 0 > answer.txt"
            calls = [{"name": "execute", "args": {"command": command}, "id": "fixture-call",
                      "type": "tool_call"}]
        self.called = True
        return AIMessage(content="" if calls else "Fixture complete", tool_calls=calls,
                         usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})


def main():
    store = Store("runs/demo")
    config = Config()
    config.sandbox.backend, config.sandbox.allow_local = "local", True
    config.workers = 2
    tasks = load_tasks("examples/local-tasks.yaml")
    ids = []
    for correct in (True, False):
        config.model.name = "scripted-fixture-correct" if correct else "scripted-fixture-partial"
        ids.append(run_benchmark(store, config, tasks, model_factory=lambda: FixtureModel(correct)))
    path = store.root / "comparison.html"
    write_report(compare(store, ids), path)
    print(f"Fixture run IDs: {', '.join(ids)}")
    print(f"Report: {path}")
    print("Dashboard: bbdevbox --root runs/demo serve")


if __name__ == "__main__":
    main()
