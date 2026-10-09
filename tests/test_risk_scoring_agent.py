import json

import pytest

from agents.risk_scoring_agent import RiskScoringAgent


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def score(tmp_path, pr=None, impact=None, selection=None, metrics=None, repo_files=None):
    """Run the risk agent on hand-made phase outputs."""
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    for path, lines in (repo_files or {}).items():
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text("x\n" * lines, encoding="utf-8")

    write(tmp_path / "pr.json", pr or {})
    write(tmp_path / "impact.json", impact or {})
    write(tmp_path / "selection.json", selection or {"coverage_gaps": []})
    write(tmp_path / "metrics.json", metrics or {})
    write(tmp_path / "structure.json", {"test_file_map": {}})

    return RiskScoringAgent(
        pr_analysis_path=str(tmp_path / "pr.json"),
        impact_analysis_path=str(tmp_path / "impact.json"),
        semantic_impact_path=str(tmp_path / "missing.json"),
        test_selection_path=str(tmp_path / "selection.json"),
        dependency_metrics_path=str(tmp_path / "metrics.json"),
        repo_structure_path=str(tmp_path / "structure.json"),
        repo_path=str(repo)
    ).compute()


def change(lines, status="modified", path="app/core.py"):
    return {"file_stats": {path: {"added": lines, "deleted": 0, "status": status}}}


@pytest.mark.smoke
def test_weights_add_up_to_100():
    assert sum(RiskScoringAgent.WEIGHTS.values()) == 100


@pytest.mark.smoke
def test_no_cliffs_in_size_score(tmp_path):
    a = score(tmp_path, pr=change(99))["components"]["change_size"]
    b = score(tmp_path, pr=change(100))["components"]["change_size"]
    assert abs(a - b) < 0.2


def test_new_files_count_less_than_edits_to_existing_code(tmp_path):
    new_code = score(tmp_path, pr=change(400, status="added"))
    edited = score(tmp_path, pr=change(400, status="modified"))
    assert new_code["components"]["change_size"] < edited["components"]["change_size"]


def test_large_new_feature_alone_is_not_high_risk(tmp_path):
    # A big brand-new module nothing depends on yet, shipped with tests
    result = score(tmp_path, pr={
        "file_stats": {
            "feature/new_module.py": {"added": 1500, "deleted": 0, "status": "added"},
            "tests/test_new_module.py": {"added": 400, "deleted": 0, "status": "added"},
        },
        "changed_functions": ["run_feature"],
        "changed_tests": ["tests/test_new_module.py"],
    })
    assert result["risk_level"] == "low"


def test_test_files_do_not_count_as_change_size(tmp_path):
    result = score(tmp_path, pr=change(500, path="tests/test_core.py"))
    assert result["components"]["change_size"] == 0


def test_relative_churn_uses_file_size(tmp_path):
    small_edit = score(tmp_path, pr=change(10), repo_files={"app/core.py": 1000})
    rewrite = score(tmp_path, pr=change(10), repo_files={"app/core.py": 10})
    assert rewrite["factor_details"]["change_size"]["relative_churn"] == 1.0
    assert rewrite["components"]["change_size"] > small_edit["components"]["change_size"]


def test_api_break_scales_with_dependents(tmp_path):
    pr = {"modified_definitions": ["fetch", "_helper"]}
    unused = score(tmp_path, pr=pr, impact={"affected_modules": []})
    used = score(tmp_path, pr=pr, impact={"affected_modules": [
        {"module": m, "depth": 1} for m in ("a", "b", "c")
    ]})
    assert unused["components"]["api_break"] < used["components"]["api_break"]
    assert used["factor_details"]["api_break"]["breaking_symbols"] == ["fetch"]


def test_new_public_function_is_low_api_risk(tmp_path):
    result = score(tmp_path, pr={"changed_functions": ["new_helper"]})
    assert result["components"]["api_break"] == pytest.approx(0.15 * 20)


def test_blast_radius_is_relative_to_repo_size(tmp_path):
    impact = {
        "changed_modules": ["core"],
        "affected_modules": [{"module": "a", "depth": 1}, {"module": "b", "depth": 2}],
    }
    small_repo = {m: {"fan_out": 1} for m in ("core", "a", "b", "c")}
    big_repo = {f"m{i}": {"fan_out": 1} for i in range(200)}

    small = score(tmp_path, impact=impact, metrics=small_repo)["components"]["blast_radius"]
    big = score(tmp_path, impact=impact, metrics=big_repo)["components"]["blast_radius"]
    assert small > big


def test_updating_tests_reduces_coverage_risk(tmp_path):
    impact = {"changed_modules": ["core"]}
    selection = {"coverage_gaps": ["core"]}
    without = score(tmp_path, impact=impact, selection=selection)
    with_tests = score(tmp_path, pr={"changed_tests": ["tests/test_core.py"]},
                       impact=impact, selection=selection)
    assert with_tests["components"]["test_coverage"] < without["components"]["test_coverage"]


def test_score_never_exceeds_100(tmp_path):
    result = score(
        tmp_path,
        pr={**change(5000), "modified_definitions": [f"f{i}" for i in range(10)]},
        impact={"changed_modules": ["core"],
                "affected_modules": [{"module": f"m{i}", "depth": 1} for i in range(30)]},
        selection={"coverage_gaps": ["core"] + [f"m{i}" for i in range(30)]},
        metrics={"core": {"fan_out": 50}, **{f"m{i}": {"fan_out": 1} for i in range(30)}},
    )
    assert result["risk_score"] <= 100
    assert result["risk_level"] == "critical"


def test_coupling_needs_real_fan_out_not_just_top_rank(tmp_path):
    # In a sparse repo, a module importing only 2 others ranks first
    # but shouldn't score like a genuinely complex module
    metrics = {"core": {"fan_out": 2}, **{f"m{i}": {"fan_out": 0} for i in range(10)}}
    sparse = score(tmp_path, impact={"changed_modules": ["core"]}, metrics=metrics)

    metrics["core"]["fan_out"] = 15
    complex_module = score(tmp_path, impact={"changed_modules": ["core"]}, metrics=metrics)

    assert sparse["components"]["coupling"] < 3
    assert complex_module["components"]["coupling"] > 6
