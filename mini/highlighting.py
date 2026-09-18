"""Syntax highlighting for Python and C/C++: colors one line's tokens
(keywords, dunders/preprocessor directives, builtin type names,
function calls/definitions, strings) at a time. A multi-line construct
(a triple-quoted Python string, or a C `/* */` comment, spanning
several lines) is colored as one block too, but only with help from
outside this module: `_python_line_exit_state`/`_c_line_exit_state`
below are pure, single-line functions with no memory of their own - a
per-buffer cache of what's still open *entering* each line
(rendering.py's `_comment_state_for`) is what actually threads that
state from one line to the next, and `carryover` (accepted by
`_highlight_python`/`_highlight_c` below) is how the render pipeline
tells them how much of what they're about to color starts out already
inside a still-open construct."""

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


_PY_LINE_SCAN_PATTERN = re.compile(
    _TRIPLE_QUOTE_SOURCE  # closes on this line - resolved, skip over it
    + r'|"""|\'\'\''  # doesn't close - carries over into the next line
    r"|'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
    r"|#.*"
)


def _python_line_exit_state(line, entry_state):
    """(exit_state, close_column, open_column) for `line`, given
    `entry_state` - whatever multi-line construct (None,
    "python_triple_double", or "python_triple_single") was already
    open *entering* it. A pure, single-line function - the per-buffer
    cache that threads exit_state from one line into the next line's
    own entry_state lives in rendering.py's `_comment_state_for`
    instead.

    `close_column` is only meaningful when `entry_state` isn't None:
    the raw column right after the carried-over construct's own
    closing delimiter on this line - or `len(line)` if it doesn't
    close here at all, in which case `exit_state` equals `entry_state`
    unchanged (the whole line stays inside it, and `open_column` is
    irrelevant). `open_column` is only meaningful when `exit_state` is
    not None *and* different from `entry_state`: the raw column where
    a brand new construct opens on this line without closing - the
    opening line's own delimiter needs this too (see rendering.py's
    `_apply_highlight`), not just the lines after it."""
    close_column = 0
    index = 0
    if entry_state is not None:
        closer = '"""' if entry_state == "python_triple_double" else "'''"
        found = line.find(closer)
        if found == -1:
            return entry_state, len(line), None
        close_column = found + len(closer)
        index = close_column
    for match in _PY_LINE_SCAN_PATTERN.finditer(line, index):
        token = match.group()
        if token.startswith("#"):
            return None, close_column, None
        if token == '"""':
            return "python_triple_double", close_column, match.start()
        if token == "'''":
            return "python_triple_single", close_column, match.start()
    return None, close_column, None


_C_LINE_SCAN_PATTERN = re.compile(
    r"/\*.*?\*/"  # closes on this line - resolved, skip over it
    r"|/\*"  # doesn't close - carries over into the next line
    r"|//.*"
    r"|'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
)


def _c_line_exit_state(line, entry_state):
    """Same idea as `_python_line_exit_state`, for C/C++'s `/* */`
    block comments - the only multi-line construct either language
    has (a `//` line comment always ends at EOL, same as Python's
    `#`)."""
    close_column = 0
    index = 0
    if entry_state is not None:
        found = line.find("*/")
        if found == -1:
            return entry_state, len(line), None
        close_column = found + 2
        index = close_column
    for match in _C_LINE_SCAN_PATTERN.finditer(line, index):
        token = match.group()
        if token == "/*":
            return "c_block_comment", close_column, match.start()
        if token.startswith("//"):
            return None, close_column, None
    return None, close_column, None


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


def _is_function_call(token_end, display_text, lookahead):
    """Whether the position right after a not-otherwise-special token
    is immediately followed (skipping spaces) by "(" - i.e. whether
    it's a function/method call or definition rather than a bare name.
    The one check shared, unchanged, between `_highlight_python`'s and
    `_highlight_c`'s own `_colorize`."""
    rest = display_text[token_end:] + lookahead
    return rest.lstrip(" ").startswith("(")


_CLASS_NAME_CONTEXT = re.compile(r"\bclass\s+$")
_DEF_PARAMS_START = re.compile(r"\bdef\s+[A-Za-z_][A-Za-z0-9_]*\s*\(")


def _def_param_role(display_text, token_start):
    """None if `token_start` isn't inside a `def name(...)` parameter
    list still open at that point (this only ever looks at
    `display_text` itself - a signature split across a wrapped/
    multi-line display, like every other single-line-only check in
    this module, isn't recognized past the piece it started on);
    otherwise "name" for a parameter's own name (the first identifier
    in its comma-separated segment, `*`/`**` prefixes included since
    those aren't matched as part of the identifier token at all) or
    "annotation" for anything in that segment after a top-level ":"
    (nested brackets - `Dict[str, int]` - don't count as top-level,
    so their own comma doesn't end the segment early). A top-level
    "=" (a default value) returns None either way - a default's own
    literal/expression is already colored however it normally would
    be, not specially."""
    last_open = None
    for match in _DEF_PARAMS_START.finditer(display_text[:token_start]):
        last_open = match.end() - 1  # index of the "("
    if last_open is None:
        return None
    depth = 0
    segment_start = last_open + 1
    saw_colon = saw_equals = False
    for index in range(last_open, token_start):
        character = display_text[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
            if depth == 0:
                return None  # this def's own parameter list already closed
        elif depth == 1:
            if character == ",":
                segment_start = index + 1
                saw_colon = saw_equals = False
            elif character == ":":
                saw_colon = True
            elif character == "=":
                saw_equals = True
    if saw_equals:
        return None
    if saw_colon:
        return "annotation"
    if display_text[segment_start:token_start].strip(" *"):
        return None  # not actually this segment's own first identifier
    return "name"


def _highlight_python(
    display_text, lookahead="", carryover=0, tail_carryover=0,
):
    """`lookahead` is whatever real text follows `display_text` in the
    actual line but isn't part of it - e.g. bracket-match rendering
    splits a line right before a paren, so the piece ending in a
    function name would otherwise never see the "(" that names it as
    a call, right when it matters most (cursor on that bracket).

    `carryover` (display-text characters, from `display_text`'s own
    start) is how many of them are already known to be inside a
    multi-line construct carried over from an earlier line (see this
    module's own docstring) - colored as a comment outright, with
    normal tokenizing resuming only after it. `tail_carryover` is the
    mirror image, counted from `display_text`'s own end: a brand new
    construct that opens somewhere in this same piece and doesn't
    close - needed for the *opening* line's own delimiter, which
    `_TOKEN_PATTERN` alone can't recognize as "the start of one" (it
    only ever matches a triple-quote that both opens *and* closes
    within the same text)."""
    if carryover > 0 or tail_carryover > 0:
        carryover = min(carryover, len(display_text))
        tail_carryover = min(tail_carryover, len(display_text) - carryover)
        split = len(display_text) - tail_carryover
        prefix, middle, suffix = (
            display_text[:carryover], display_text[carryover:split],
            display_text[split:],
        )
        colored_prefix = (
            f"{theme.COMMENT_COLOR}{prefix}{theme.COLOR_RESET}"
            if prefix else ""
        )
        colored_suffix = (
            f"{theme.COMMENT_COLOR}{suffix}{theme.COLOR_RESET}"
            if suffix else ""
        )
        middle_colored = _highlight_python(middle, lookahead) if middle else ""
        return colored_prefix + middle_colored + colored_suffix

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
        if _CLASS_NAME_CONTEXT.search(display_text[:match.start()]):
            return f"{theme.TYPE_COLOR}{token}{theme.COLOR_RESET}"
        param_role = _def_param_role(display_text, match.start())
        if param_role == "name":
            return f"{theme.PARAMETER_COLOR}{token}{theme.COLOR_RESET}"
        if param_role == "annotation":
            return f"{theme.TYPE_COLOR}{token}{theme.COLOR_RESET}"
        if token in TYPE_NAMES:
            return f"{theme.TYPE_COLOR}{token}{theme.COLOR_RESET}"
        if _is_function_call(match.end(), display_text, lookahead):
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


def _highlight_c(
    display_text, lookahead="", cpp=False, carryover=0, tail_carryover=0,
):
    """Same idea as `_highlight_python`, for C (or C++, with
    `cpp=True` for its extra keywords/types) - a `//` or same-line
    `/* */` comment matches as one token so nothing inside it gets
    highlighted as code, the same way Python's `#.*` does. `carryover`/
    `tail_carryover` are the same prefix/suffix `_highlight_python`
    accepts."""
    if carryover > 0 or tail_carryover > 0:
        carryover = min(carryover, len(display_text))
        tail_carryover = min(tail_carryover, len(display_text) - carryover)
        split = len(display_text) - tail_carryover
        prefix, middle, suffix = (
            display_text[:carryover], display_text[carryover:split],
            display_text[split:],
        )
        colored_prefix = (
            f"{theme.COMMENT_COLOR}{prefix}{theme.COLOR_RESET}"
            if prefix else ""
        )
        colored_suffix = (
            f"{theme.COMMENT_COLOR}{suffix}{theme.COLOR_RESET}"
            if suffix else ""
        )
        middle_colored = (
            _highlight_c(middle, lookahead, cpp) if middle else ""
        )
        return colored_prefix + middle_colored + colored_suffix

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
        if _is_function_call(match.end(), display_text, lookahead):
            return f"{theme.FUNCTION_COLOR}{token}{theme.COLOR_RESET}"
        return token

    return _C_TOKEN_PATTERN.sub(_colorize, display_text)
