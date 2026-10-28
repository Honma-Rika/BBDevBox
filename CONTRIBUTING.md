# Contributing

Use Python 3.11+ and install `pip install -e '.[dev]'`. Before submitting, run `pytest -q`, `ruff check src tests examples test_docker.py`, and `python -m build --no-isolation`. Node.js 22+ runs the dashboard selection/race regression checks (`node --test tests/dashboard.test.cjs`).

Changes to scoring, prompts, budgets, sandbox flags, memory selection, or task rendering must describe their effect on comparability. Preserve original datasets and results. Add tests for behavior that changes evaluation correctness, resource cleanup, state recovery, or provider interoperability. Network and model calls should use fixtures in unit tests; real runtime checks belong in explicit integration tests.

Do not commit credentials, run artifacts, generated skills containing task answers, private endpoints, or personal data. Report security issues privately to the repository maintainers once a contact is established; avoid publishing working exploits against shared infrastructure.
