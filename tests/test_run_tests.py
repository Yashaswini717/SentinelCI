import json

import pytest

from ci.run_tests import classify_exit_code, run_tests


@pytest.mark.smoke
@pytest.mark.parametrize("code, status", [
    (0, "passed"),
    (1, "failed"),
    (4, "error"),
    (5, "no_tests"),
    (99, "error"),
])
def test_classify_exit_code(code, status):
    assert classify_exit_code(code) == status


def write_decision(tmp_path, runs):
    decision = tmp_path / "ci_decision.json"
    decision.write_text(json.dumps({"risk_level": "low", "test_runs": runs}), encoding="utf-8")
    return decision


def pytest_run(name, path, blocking=True):
    return {
        "name": name,
        "pytest_args": [str(path), "-q", "-p", "no:cacheprovider"],
        "command": f"python -m pytest {path}",
        "blocking": blocking
    }


def test_blocking_failure_fails_and_is_recorded(tmp_path):
    passing = tmp_path / "test_pass.py"
    passing.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    failing = tmp_path / "test_fail.py"
    failing.write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    decision = write_decision(tmp_path, [
        pytest_run("pass", passing),
        pytest_run("fail", failing),
    ])
    output = tmp_path / "out.json"

    exit_code = run_tests(str(decision), str(output))

    result = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert result["overall"] == "failed"
    assert [r["status"] for r in result["results"]] == ["passed", "failed"]


def test_non_blocking_failure_does_not_fail(tmp_path):
    failing = tmp_path / "test_fail.py"
    failing.write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    decision = write_decision(tmp_path, [pytest_run("generated", failing, blocking=False)])
    output = tmp_path / "out.json"

    assert run_tests(str(decision), str(output)) == 0


def test_no_runs_is_not_a_failure(tmp_path):
    decision = write_decision(tmp_path, [])
    output = tmp_path / "out.json"

    assert run_tests(str(decision), str(output)) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["overall"] == "no_tests"
