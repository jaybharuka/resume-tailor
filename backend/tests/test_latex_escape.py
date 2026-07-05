import pytest
from app.services.latex_escape import escape_latex


@pytest.mark.parametrize("raw,expected", [
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
    ("\\", r"\textbackslash{}"),
])
def test_escape_latex_handles_each_special_character_individually(raw, expected):
    assert escape_latex(raw) == expected


def test_escape_latex_handles_a_realistic_composite_string():
    raw = "Improved throughput 40% using C++ & Python, cost $50/mo, see file_name.py"
    expected = r"Improved throughput 40\% using C++ \& Python, cost \$50/mo, see file\_name.py"
    assert escape_latex(raw) == expected


def test_escape_latex_does_not_corrupt_backslash_replacement_with_later_brace_escaping():
    """Regression guard for the single-pass design: escaping backslash first as
    \\textbackslash{} must not have its own braces re-escaped by a later pass
    over {/} - a naive sequential str.replace() approach would corrupt this."""
    assert escape_latex("\\") == r"\textbackslash{}"
    assert escape_latex("a\\b") == r"a\textbackslash{}b"


def test_escape_latex_handles_plain_text_unchanged():
    assert escape_latex("Jane Doe") == "Jane Doe"


def test_escape_latex_handles_none_as_empty_string():
    assert escape_latex(None) == ""
