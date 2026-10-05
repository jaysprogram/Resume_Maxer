import pytest

from resume_maxer.latex import latex_escape


def test_tilde_before_number_stays_visible():
    # P1: a raw ~ is a non-breaking space in LaTeX, so "~10" printed as "10"
    # and silently dropped the estimate marker the metric policy requires.
    assert latex_escape("~10 field testers") == r"\textasciitilde{}10 field testers"


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("C#", r"C\#"),
        ("R&D", r"R\&D"),
        ("cut setup 50% in Q3", r"cut setup 50\% in Q3"),
        ("$5K", r"\$5K"),
        ("snake_case", r"snake\_case"),
        ("{x}", r"\{x\}"),
        ("2^10", r"2\textasciicircum{}10"),
        ("a\\b", r"a\textbackslash{}b"),
    ],
)
def test_special_characters_are_escaped(raw, escaped):
    assert latex_escape(raw) == escaped


def test_backslash_escape_is_not_escaped_again():
    # Chained str.replace() calls would turn the braces of \textbackslash{}
    # into \{\} on a later pass.
    assert latex_escape("\\") == r"\textbackslash{}"


def test_input_is_treated_as_plain_text_not_latex():
    # Text from a JD or the model is never trusted as LaTeX: a literal "\%"
    # must print as backslash-percent, not collapse to "%".
    assert latex_escape(r"\%") == r"\textbackslash{}\%"


def test_all_special_characters_together():
    assert latex_escape("&%$#_{}~^\\") == (
        r"\&\%\$\#\_\{\}\textasciitilde{}\textasciicircum{}\textbackslash{}"
    )


def test_ordinary_text_passes_through_unchanged():
    text = "Built a weather dashboard with React and Go (REST/gRPC) -- 3-person team."
    assert latex_escape(text) == text
