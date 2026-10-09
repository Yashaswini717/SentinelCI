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


def test_body_change_is_attributed_to_enclosing_symbol():
    patch = (
        "@@ -10,3 +10,3 @@ def compute(value):\n"
        "-    return value\n"
        "+    return value * 2\n"
    )

    result = DiffParser().analyze_patch(patch)

    assert result["changed_functions"] == []
    assert result["modified_symbols"] == ["compute"]
