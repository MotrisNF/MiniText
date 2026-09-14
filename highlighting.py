"""Syntax highlighting for Python and C/C++: colors one line's tokens
(keywords, dunders/preprocessor directives, builtin type names,
function calls/definitions, strings) independently - no awareness of
multi-line constructs (a triple-quoted Python string, or a C `/* */`
comment, spanning several lines won't be colored as one block)."""

import keyword
import re

import theme
from languages import (
    C_KEYWORDS, C_TYPE_NAMES, CPP_KEYWORDS, CPP_LITERALS, CPP_TYPE_NAMES,
)


TYPE_NAMES = {
    "int", "float", "str", "bool", "list", "dict", "tuple", "set",
    "frozenset", "bytes", "bytearray", "complex", "object", "type",
}
DECLARATION_KEYWORDS = {"def", "class"}
_TRIPLE_QUOTE_SOURCE = (
    r'"""(?:[^\\]|\\.)*?"""'
    r"|'''(?:[^\\]|\\.)*?'''"
)
TRIPLE_QUOTE_PATTERN = re.compile(_TRIPLE_QUOTE_SOURCE)
_TOKEN_PATTERN = re.compile(
    _TRIPLE_QUOTE_SOURCE
    + r"|'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
    r"|#.*"
    r"|[A-Za-z_][A-Za-z0-9_]*"
)


def is_in_triple_quoted_string(line, column):
    """Whether `column` falls within a same-line triple-quoted
    string/docstring. Quote-matching (bracket/quote highlighting)
    has no triple-quote awareness of its own - it just treats each
    `'` or `"` as its own single matchable quote character, which
    would otherwise pair up two of a docstring's own delimiter
    characters (or split its highlighting around whichever one the
    cursor happens to land on) instead of leaving the whole thing
    alone as the one block it actually is."""
    for match in TRIPLE_QUOTE_PATTERN.finditer(line):
        if match.start() <= column < match.end():
            return True
    return False


def _highlight(display_text, lookahead=""):
    """`lookahead` is whatever real text follows `display_text` in the
    actual line but isn't part of it - e.g. bracket-match rendering
    splits a line right before a paren, so the piece ending in a
    function name would otherwise never see the "(" that names it as
    a call, right when it matters most (cursor on that bracket)."""
    def _colorize(match):
        token = match.group()
        if token.startswith('"""') or token.startswith("'''"):
            # A docstring/triple-quoted string is treated as a
            # comment, same color and all - same single-line-only
            # reach as everything else here, so only one that both
            # starts and ends on this line is recognized as such.
            return f"{theme.COMMENT_COLOR}{token}{theme.COLOR_RESET}"
        if token[0] in ("'", '"'):
            return f"{theme.STRING_COLOR}{token}{theme.COLOR_RESET}"
        if token[0] == "#":
            return f"{theme.COMMENT_COLOR}{token}{theme.COLOR_RESET}"
        if token in DECLARATION_KEYWORDS:
            return f"{theme.DECLARATION_COLOR}{token}{theme.COLOR_RESET}"
        if token in keyword.kwlist:
            return f"{theme.KEYWORD_COLOR}{token}{theme.COLOR_RESET}"
        if token.startswith("__"):
            return f"{theme.DUNDER_COLOR}{token}{theme.COLOR_RESET}"
        if token in TYPE_NAMES:
            return f"{theme.TYPE_COLOR}{token}{theme.COLOR_RESET}"
        rest = display_text[match.end():] + lookahead
        if rest.lstrip(" ").startswith("("):
            return f"{theme.FUNCTION_COLOR}{token}{theme.COLOR_RESET}"
        return token

    return _TOKEN_PATTERN.sub(_colorize, display_text)


_C_TOKEN_PATTERN = re.compile(
    r"'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
    r"|//.*"
    r"|/\*.*?\*/"
    r"|#\s*[A-Za-z_]+"
    r"|[A-Za-z_][A-Za-z0-9_]*"
)


def _highlight_c(display_text, lookahead="", cpp=False):
    """Same idea as `_highlight`, for C (or C++, with `cpp=True` for
    its extra keywords/types) - a `//` or same-line `/* */` comment
    matches as one token so nothing inside it gets highlighted as
    code, the same way Python's `#.*` does."""
    keywords = CPP_KEYWORDS if cpp else C_KEYWORDS
    type_names = CPP_TYPE_NAMES if cpp else C_TYPE_NAMES
    literals = CPP_LITERALS if cpp else ()

    def _colorize(match):
        token = match.group()
        if token[0] in ("'", '"'):
            return f"{theme.STRING_COLOR}{token}{theme.COLOR_RESET}"
        if token.startswith("//") or token.startswith("/*"):
            return f"{theme.COMMENT_COLOR}{token}{theme.COLOR_RESET}"
        if token.startswith("#"):
            return f"{theme.DECLARATION_COLOR}{token}{theme.COLOR_RESET}"
        if token in keywords or token in literals:
            return f"{theme.KEYWORD_COLOR}{token}{theme.COLOR_RESET}"
        if token in type_names:
            return f"{theme.TYPE_COLOR}{token}{theme.COLOR_RESET}"
        rest = display_text[match.end():] + lookahead
        if rest.lstrip(" ").startswith("("):
            return f"{theme.FUNCTION_COLOR}{token}{theme.COLOR_RESET}"
        return token

    return _C_TOKEN_PATTERN.sub(_colorize, display_text)
