import shutil
import subprocess
from pathlib import Path

import pytest


def test_dashboard_javascript_regressions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for dashboard state regression checks")
    result = subprocess.run([node, "--test", "tests/dashboard.test.cjs"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
