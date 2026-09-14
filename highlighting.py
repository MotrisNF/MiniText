"""Python syntax highlighting: colors one line's tokens (keywords,
dunders, builtin type names, function calls/definitions, strings)
independently - no awareness of multi-line constructs."""

import keyword
import re

import theme


TYPE_NAMES = {
    "int", "float", "str", "bool", "list", "dict", "tuple", "set",
    "frozenset", "bytes", "bytearray", "complex", "object", "type",
}
DECLARATION_KEYWORDS = {"def", "class"}
_TOKEN_PATTERN = re.compile(
    r"'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
    r"|#.*"
    r"|[A-Za-z_][A-Za-z0-9_]*"
)


def _highlight(display_text, lookahead=""):
    """`lookahead` is whatever real text follows `display_text` in the
    actual line but isn't part of it - e.g. bracket-match rendering
    splits a line right before a paren, so the piece ending in a
    function name would otherwise never see the "(" that names it as
    a call, right when it matters most (cursor on that bracket)."""
    def _colorize(match):
        token = match.group()
        if token[0] in ("'", '"'):
            return f"{theme.STRING_COLOR}{token}{theme.COLOR_RESET}"
        if token[0] == "#":
            return token
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
