_LATEX_ESCAPE_MAP = {
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


def escape_latex(text: str | None) -> str:
    """Escape a plain string for safe insertion into LaTeX source.

    Builds the result in a SINGLE pass over the original characters (not
    sequential global str.replace() calls), since a naive multi-pass approach
    would re-scan and corrupt characters introduced by an earlier replacement
    - e.g. escaping "\\" first as "\\textbackslash{}" and THEN escaping "{"/"}"
    in a later pass would also escape the braces just introduced, corrupting
    the output into "\\textbackslash\\{\\}". Iterating once over the original
    characters and mapping each to its replacement (or itself) avoids this
    entirely, since replacement text is never re-scanned.
    """
    if text is None:
        return ""
    return "".join(_LATEX_ESCAPE_MAP.get(char, char) for char in text)
