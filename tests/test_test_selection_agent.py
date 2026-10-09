import json

from agents.test_selection_agent import is_valid_test_file, run_test_selection


def test_is_valid_test_file():
    assert is_valid_test_file("tests/test_api.py")
    assert is_valid_test_file("test_root.py")
    assert is_valid_test_file("pkg/api_test.py")
    assert not is_valid_test_file("tests/conftest.py")
    assert not is_valid_test_file("tests/test_data.json")


def test_tests_changed_in_pr_run_first(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "impact_analysis.json").write_text(json.dumps({
        "changed_modules": ["app"],
        "affected_modules": []
    }), encoding="utf-8")
    (storage / "test_mapping.json").write_text(json.dumps({
        "tests/test_app.py": ["app"],
        "tests/test_other.py": ["other"]
    }), encoding="utf-8")
    (storage / "pr_analysis.json").write_text(json.dumps({
        "changed_tests": ["tests/test_other.py"]
    }), encoding="utf-8")

    result = run_test_selection(str(storage / "test_selection.json"))

    # The PR's own test file first, then tests for the changed module
    assert result["tests_to_run"] == ["tests/test_other.py", "tests/test_app.py"]
    assert result["selection_summary"]["changed_tests"] == 1
    assert result["selection_summary"]["static_tests"] == 1
