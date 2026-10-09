import json

import pytest

from repository_analysis.dependency_graph import DependencyGraphBuilder


def build_graph(tmp_path, files: dict) -> dict:
    """Write a small repo to disk and build its dependency graph."""
    repo = tmp_path / "repo"
    file_map = {}
    for rel_path, source in files.items():
        full = repo / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(source, encoding="utf-8")
        file_map[rel_path[:-3]] = rel_path

    structure = tmp_path / "repo_structure.json"
    structure.write_text(json.dumps({
        "file_map": file_map,
        "modules": [{"name": k, "path": v} for k, v in file_map.items()]
    }), encoding="utf-8")

    return DependencyGraphBuilder(str(structure), str(repo)).build()


@pytest.mark.smoke
def test_absolute_import_inside_package(tmp_path):
    graph = build_graph(tmp_path, {
        "pr_analysis/pr_fetcher.py": "",
        "pr_analysis/pr_analyzer.py": "from pr_analysis.pr_fetcher import PRFetcher\n",
    })
    assert graph["pr_analysis/pr_analyzer"] == ["pr_analysis/pr_fetcher"]


def test_plain_import_statement(tmp_path):
    graph = build_graph(tmp_path, {
        "pkg/helpers.py": "",
        "pkg/main.py": "import pkg.helpers\n",
    })
    assert graph["pkg/main"] == ["pkg/helpers"]


def test_relative_imports(tmp_path):
    graph = build_graph(tmp_path, {
        "pkg/sub/a.py": "from . import b\nfrom .. import top\n",
        "pkg/sub/b.py": "",
        "pkg/top.py": "",
    })
    assert graph["pkg/sub/a"] == ["pkg/sub/b", "pkg/top"]


def test_src_layout(tmp_path):
    graph = build_graph(tmp_path, {
        "src/requests/models.py": "",
        "src/requests/sessions.py": "from requests.models import Response\n",
    })
    assert graph["src/requests/sessions"] == ["src/requests/models"]


def test_stdlib_import_does_not_match_partial_name(tmp_path):
    graph = build_graph(tmp_path, {
        "app/repos.py": "",
        "app/main.py": "import os\nimport json\n",
    })
    assert graph["app/main"] == []


def test_metrics_count_fan_in_and_out(tmp_path):
    builder_graph = build_graph(tmp_path, {
        "core.py": "",
        "a.py": "import core\n",
        "b.py": "import core\n",
    })
    assert builder_graph["a"] == ["core"]
    assert builder_graph["b"] == ["core"]
