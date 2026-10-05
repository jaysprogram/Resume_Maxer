"""LaTeX escaping: the single place untrusted text becomes safe template input."""

# Each special character maps to the LaTeX that prints it literally.
# ~ needs \textasciitilde{} rather than \~{}: \~ is an accent command, and a
# raw ~ is a non-breaking space that silently erased estimate markers (P1).
_ESCAPES = str.maketrans(
    {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
)


def latex_escape(text: str) -> str:
    """Return `text` with every LaTeX special character printed literally.

    Uses one str.translate pass, not chained str.replace calls: replacing
    one character at a time would re-escape the braces that an earlier
    replacement (\\textbackslash{}) had just inserted.
    """
    return text.translate(_ESCAPES)
