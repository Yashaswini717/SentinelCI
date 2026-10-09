import pytest

from pr_analysis.diff_parser import DiffParser


@pytest.mark.smoke
def test_detects_changed_function_and_line_counts():
    patch = (
        "@@ -1,3 +1,4 @@ class Service:\n"
        " import os\n"
        "-def old_name(x):\n"
        "+def new_name(x, y):\n"
        "+    return x + y\n"
    )

    result = DiffParser().analyze_patch(patch)

    assert result["changed_functions"] == ["new_name", "old_name"]
    assert result["lines_added"] == 2
    assert result["lines_deleted"] == 1


def test_only_removed_definitions_count_as_modified():
    patch = (
        "@@ -1,2 +1,4 @@\n"
        "-def edited(a):\n"
        "+def edited(a, b):\n"
        "+def brand_new():\n"
        "+    pass\n"
    )

    result = DiffParser().analyze_patch(patch)

    assert result["changed_functions"] == ["brand_new", "edited"]
    assert result["modified_definitions"] == ["edited"]


def test_body_change_is_attributed_to_enclosing_symbol():
    patch = (
        "@@ -10,3 +10,3 @@ def compute(value):\n"
        "-    return value\n"
        "+    return value * 2\n"
    )

    result = DiffParser().analyze_patch(patch)

    assert result["changed_functions"] == []
    assert result["modified_symbols"] == ["compute"]


def test_moved_definition_is_not_a_signature_change():
    patch = (
        "@@ -1,4 +1,6 @@\n"
        "-    def fetch(self) -> list:\n"
        "+    def fetch_info(self) -> dict:\n"
        "+        pass\n"
        "+    def fetch(self) -> list:\n"
    )

    result = DiffParser().analyze_patch(patch)

    assert result["modified_definitions"] == []
