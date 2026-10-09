import json

import pytest

from ci.ci_decision import CIDecision


def write_inputs(tmp_path, risk_level="medium", tests_to_run=None, generated=None):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "risk_report.json").write_text(json.dumps({
        "risk_score": 50,
        "risk_level": risk_level,
        "recommendation": {"action": "run_selected_tests", "message": "msg"},
        "drivers": ["a", "b", "c", "d"]
    }), encoding="utf-8")
    (storage / "test_selection.json").write_text(json.dumps({
        "tests_to_run": tests_to_run or [],
        "coverage_gaps": []
    }), encoding="utf-8")
    (storage / "test_generation.json").write_text(json.dumps({
        "generated_tests": [{"path": p} for p in (generated or [])]
    }), encoding="utf-8")
    return storage


def make_decision(tmp_path, repo, storage):
    return CIDecision(
        risk_report_path=str(storage / "risk_report.json"),
        test_selection_path=str(storage / "test_selection.json"),
        test_generation_path=str(storage / "test_generation.json"),
        repo_path=str(repo)
    )


@pytest.mark.smoke
def test_no_test_folder_means_no_test_runs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    storage = write_inputs(tmp_path)

    result = make_decision(tmp_path, repo, storage).decide()

    assert result["test_runs"] == []
    assert result["test_commands"] == []


def test_selected_tests_and_smoke_suite_for_medium_risk(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_x.py").write_text("", encoding="utf-8")
    storage = write_inputs(tmp_path, "medium", tests_to_run=["tests/test_x.py", "tests/gone.py"])

    runs = make_decision(tmp_path, repo, storage).decide()["test_runs"]

    assert [r["name"] for r in runs] == ["selected_tests", "smoke_tests"]
    # Missing files are dropped instead of making pytest error out
    assert runs[0]["pytest_args"][0] == "tests/test_x.py"
    assert "tests/gone.py" not in runs[0]["pytest_args"]
    assert all(r["blocking"] for r in runs)


def test_full_suite_when_nothing_selected(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    storage = write_inputs(tmp_path, "low")

    runs = make_decision(tmp_path, repo, storage).decide()["test_runs"]

    assert [r["name"] for r in runs] == ["full_suite"]


def test_generated_tests_are_non_blocking(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    generated = tmp_path / "generated_tests" / "test_mod.py"
    generated.parent.mkdir()
    generated.write_text("", encoding="utf-8")
    storage = write_inputs(tmp_path, generated=["generated_tests/test_mod.py"])

    runs = make_decision(tmp_path, repo, storage).decide()["test_runs"]

    assert len(runs) == 1
    assert runs[0]["name"] == "generated_tests"
    assert runs[0]["blocking"] is False


def test_missing_risk_report_fails_safe(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    decision = CIDecision(
        risk_report_path=str(tmp_path / "missing.json"),
        repo_path=str(repo)
    ).decide()

    assert decision["pipeline_status"] == "blocked"
    assert decision["risk_level"] == "critical"
