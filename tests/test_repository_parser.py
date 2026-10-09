from repository_analysis.repository_parser import RepositoryParser


def write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_module_named_test_prefix_is_not_a_test(tmp_path):
    write(tmp_path / "agents" / "test_selection_agent.py", "def run_test_selection():\n    pass\n")
    write(tmp_path / "tests" / "test_agents.py", "def test_x():\n    pass\n")
    write(tmp_path / "test_root.py", "def test_y():\n    pass\n")

    result = RepositoryParser(str(tmp_path)).parse()

    assert "agents/test_selection_agent" in result["file_map"]
    assert set(result["test_file_map"]) == {"tests/test_agents", "test_root"}


def test_excluded_output_folders_are_skipped(tmp_path):
    write(tmp_path / "app.py")
    write(tmp_path / "storage" / "junk.py")
    write(tmp_path / "generated_tests" / "test_app.py", "def test_x():\n    pass\n")

    result = RepositoryParser(
        str(tmp_path),
        exclude_paths=[tmp_path / "storage", tmp_path / "generated_tests"]
    ).parse()

    assert set(result["file_map"]) == {"app"}
    assert result["test_file_map"] == {}


def test_repo_inside_an_excluded_folder_is_still_parsed(tmp_path):
    # Downloaded repos live in datasets/virtual_repo, while "datasets" is excluded
    repo = tmp_path / "datasets" / "virtual_repo"
    write(repo / "app.py")

    result = RepositoryParser(str(repo), exclude_paths=[tmp_path / "datasets"]).parse()

    assert set(result["file_map"]) == {"app"}


def test_repo_inside_skipped_folder_name_is_still_parsed(tmp_path):
    repo = tmp_path / "build" / "repo"
    write(repo / "app.py")

    result = RepositoryParser(str(repo)).parse()

    assert set(result["file_map"]) == {"app"}
