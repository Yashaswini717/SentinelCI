import json

import pytest

from agents.change_impact_agent import ChangeImpactAgent


def run_impact(tmp_path, graph: dict, pr_analysis: dict) -> dict:
    files = {
        "dependency_graph.json": graph,
        "dependency_metrics.json": {},
        "pr_analysis.json": pr_analysis,
        "repo_structure.json": {},
    }
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")

    return ChangeImpactAgent(
        dependency_graph_path=str(tmp_path / "dependency_graph.json"),
        dependency_metrics_path=str(tmp_path / "dependency_metrics.json"),
        pr_analysis_path=str(tmp_path / "pr_analysis.json"),
        repo_structure_path=str(tmp_path / "repo_structure.json"),
        function_index_path=str(tmp_path / "none.json"),
        class_index_path=str(tmp_path / "none.json"),
        test_mapping_path=str(tmp_path / "none.json"),
    ).analyze()


GRAPH = {"main": ["core", "util"], "core": ["util"], "util": []}


@pytest.mark.smoke
def test_changed_modules_are_not_counted_as_affected(tmp_path):
    result = run_impact(tmp_path, GRAPH, {"changed_modules": ["util", "core"]})

    # Only main is impacted beyond the modules changed in the PR
    assert [m["module"] for m in result["affected_modules"]] == ["main"]
    assert result["impact_summary"]["total_affected"] == 1


def test_new_public_function_is_additive_not_breaking(tmp_path):
    result = run_impact(tmp_path, GRAPH, {
        "changed_modules": ["util"],
        "changed_functions": ["new_helper"],
        "modified_definitions": []
    })

    summary = result["impact_summary"]
    assert summary["change_type"] == "additive_change"
    assert summary["public_api_changed"] is False


def test_changed_public_signature_is_breaking(tmp_path):
    result = run_impact(tmp_path, GRAPH, {
        "changed_modules": ["util"],
        "changed_functions": ["helper", "_private"],
        "modified_definitions": ["helper", "_private"]
    })

    summary = result["impact_summary"]
    assert summary["change_type"] == "signature_change"
    assert summary["changed_public_api"] == ["helper"]
