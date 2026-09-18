"""Multi-line-aware comment/docstring highlighting: a Python triple-
quoted string or a C/C++ `/* */` comment spanning several lines is
now colored as one block, not just the piece that starts and ends on
the same line - both the lines *inside* it and the opening line's own
delimiter. Covers TODO/multiline_highlighting.md."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import theme  # noqa: E402
from highlighting import (  # noqa: E402
    _c_line_exit_state, _highlight_python, _python_line_exit_state,
)
from text_editor import TextEditor  # noqa: E402


def test_python_scanner_tracks_an_unclosed_docstring():
    assert _python_line_exit_state("def f():", None) == (None, 0, None)
    assert _python_line_exit_state('    """docstring', None) == (
        "python_triple_double", 0, 4
    )
    assert _python_line_exit_state("    '''docstring", None) == (
        "python_triple_single", 0, 4
    )


def test_python_scanner_finds_where_a_carryover_closes():
    assert _python_line_exit_state(
        "still open text", "python_triple_double"
    ) == ("python_triple_double", len("still open text"), None)
    assert _python_line_exit_state(
        'closes here."""', "python_triple_double"
    ) == (None, 15, None)
    assert _python_line_exit_state(
        'closes here.""" and code = 1', "python_triple_double"
    ) == (None, 15, None)


def test_python_scanner_ignores_a_same_line_closed_docstring():
    assert _python_line_exit_state('x = """closed"""', None) == (
        None, 0, None
    )


def test_python_scanner_a_comment_after_carryover_closes_still_ends_it():
    assert _python_line_exit_state(
        'closes."""  # comment', "python_triple_double"
    ) == (None, 10, None)


def test_python_scanner_plain_strings_and_comments_dont_trip_it():
    assert _python_line_exit_state("x = \"a\" + 'b'", None) == (None, 0, None)
    assert _python_line_exit_state('# not a """ docstring', None) == (
        None, 0, None
    )


def test_python_scanner_reopening_after_a_carryover_closes():
    """A construct that closes and then a *new* one opens, both on the
    same line - `open_column` must point at the new one, not be
    confused with where the carried-over one closed."""
    assert _python_line_exit_state(
        'end."""  x = """reopened', "python_triple_double"
    ) == ("python_triple_double", 7, 13)


def test_c_scanner_tracks_an_unclosed_block_comment():
    assert _c_line_exit_state("int x = 1;", None) == (None, 0, None)
    assert _c_line_exit_state("/* opens", None) == (
        "c_block_comment", 0, 0
    )
    assert _c_line_exit_state("still open", "c_block_comment") == (
        "c_block_comment", len("still open"), None
    )
    assert _c_line_exit_state(
        "closes here */ int x;", "c_block_comment"
    ) == (None, 14, None)


def test_c_scanner_ignores_resolved_comments():
    assert _c_line_exit_state("/* closed */ int x;", None) == (
        None, 0, None
    )
    assert _c_line_exit_state("// not /* a comment", None) == (
        None, 0, None
    )
    assert _c_line_exit_state(
        "closes here */ // trailing", "c_block_comment"
    ) == (None, 14, None)


def test_highlight_python_colors_a_carryover_prefix_as_comment():
    colored = _highlight_python("still open", carryover=6)
    assert colored.startswith(theme.COMMENT_COLOR + "still ")
    assert theme.COLOR_RESET in colored
    assert "open" in colored.split(theme.COLOR_RESET, 1)[1]


def test_highlight_python_whole_piece_inside_carryover():
    colored = _highlight_python("all comment", carryover=999)
    assert colored == (
        f"{theme.COMMENT_COLOR}all comment{theme.COLOR_RESET}"
    )


def test_highlight_python_colors_a_tail_carryover_suffix_as_comment():
    colored = _highlight_python('x = 1  """', tail_carryover=3)
    assert colored.endswith(f'{theme.COMMENT_COLOR}"""{theme.COLOR_RESET}')
    assert "x" in colored.split(theme.COMMENT_COLOR, 1)[0]


def _editor_with(lines, suffix=".py"):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"f{suffix}")
        with open(path, "w", encoding="utf-8") as file:
            file.write("\n".join(lines))
        editor = TextEditor(path)
        return editor


def test_comment_state_for_extends_lazily_across_lines():
    editor = _editor_with(['x = """', "still inside", 'closes."""', "y = 1"])
    entry_state, close_column, open_column = editor._comment_state_for(2)
    assert entry_state == "python_triple_double"
    assert close_column == len('closes."""')
    assert open_column is None
    entry_state, _, _ = editor._comment_state_for(3)
    assert entry_state is None


def test_edit_invalidates_only_from_the_edited_line_forward():
    editor = _editor_with(['x = """', "still inside", 'closes."""', "y = 1"])
    editor._comment_state_for(3)
    assert len(editor._comment_state) == 4
    editor.line, editor.column = 1, 0
    editor._insert("#")  # edits line 1 - lines before it stay cached
    assert len(editor._comment_state) <= 2
    entry_state, _, _ = editor._comment_state_for(3)
    assert entry_state is None  # recomputed correctly after the edit


def test_render_colors_a_multiline_docstring_as_one_comment_block():
    editor = _editor_with([
        'def f():', '    """', '    multi-line', '    docstring', '    """',
        "    return 1",
    ])
    editor._render()
    entry_state, _, _ = editor._comment_state_for(2)
    assert entry_state == "python_triple_double"
    # Line index 2 ("    multi-line") is entirely inside the docstring.
    row_text = next(
        text for text in editor._last_rendered_rows.values()
        if "multi-line" in text
    )
    assert theme.COMMENT_COLOR in row_text


def test_render_colors_the_opening_lines_own_delimiter_too():
    """The line that opens the docstring used to render through plain
    single-line tokenizing, which has no notion of a lone, unclosed
    triple-quote delimiter - it fell through as an "empty string"
    token plus one stray, uncolored quote character."""
    editor = _editor_with([
        'def f():', '    """', '    body', '    """', "    return 1",
    ])
    editor._render()
    opening_row = next(
        text for text in editor._last_rendered_rows.values()
        if '"""' in text and "def" not in text and "body" not in text
    )
    assert theme.COMMENT_COLOR in opening_row
    # No bare, uncolored quote character left dangling after a reset.
    assert theme.COLOR_RESET + '"' not in opening_row


def test_c_block_comment_spanning_lines_colors_as_one_block():
    editor = _editor_with(
        [
            "int main() {", "  /* start", "  still a comment", "  end */",
            "  return 0;", "}",
        ],
        suffix=".c",
    )
    editor._render()
    entry_state, _, _ = editor._comment_state_for(2)
    assert entry_state == "c_block_comment"


def test_undo_redo_resets_the_cache_without_going_stale():
    """Regression coverage for the invalidation itself, not just the
    scanners: an edit that changes whether a later line is inside a
    carried-over construct must be reflected right away, and undoing
    it back must restore the original answer too - the cache must
    never keep serving a stale value either way."""
    editor = _editor_with(['x = """', "inside", 'end."""'])
    entry_state, _, _ = editor._comment_state_for(2)
    assert entry_state == "python_triple_double"

    editor.line, editor.column = 0, len(editor.lines[0])
    editor._backspace()
    editor._backspace()
    editor._backspace()  # 'x = """' -> 'x = '
    editor._insert('"a"')  # -> 'x = "a"' - closed, nothing carries over
    entry_state, _, _ = editor._comment_state_for(2)
    assert entry_state is None

    for _ in range(4):
        editor._undo()
    assert editor.lines[0] == 'x = """'
    entry_state, _, _ = editor._comment_state_for(2)
    assert entry_state == "python_triple_double"


def test_bracket_matching_ignores_a_carried_over_construct():
    """`_matching_bracket_position` used to only know about a same-
    line triple-quoted string - a bracket-lookalike character sitting
    inside a docstring carried over from an earlier line would still
    get matched as if it were real code."""
    editor = _editor_with(['x = """', "a (fake) bracket", 'end."""'])
    editor.line, editor.column = 1, editor.lines[1].index("(")
    assert editor._matching_bracket_position() is None


TESTS = [
    test_python_scanner_tracks_an_unclosed_docstring,
    test_python_scanner_finds_where_a_carryover_closes,
    test_python_scanner_ignores_a_same_line_closed_docstring,
    test_python_scanner_a_comment_after_carryover_closes_still_ends_it,
    test_python_scanner_plain_strings_and_comments_dont_trip_it,
    test_python_scanner_reopening_after_a_carryover_closes,
    test_c_scanner_tracks_an_unclosed_block_comment,
    test_c_scanner_ignores_resolved_comments,
    test_highlight_python_colors_a_carryover_prefix_as_comment,
    test_highlight_python_whole_piece_inside_carryover,
    test_highlight_python_colors_a_tail_carryover_suffix_as_comment,
    test_comment_state_for_extends_lazily_across_lines,
    test_edit_invalidates_only_from_the_edited_line_forward,
    test_render_colors_a_multiline_docstring_as_one_comment_block,
    test_render_colors_the_opening_lines_own_delimiter_too,
    test_c_block_comment_spanning_lines_colors_as_one_block,
    test_undo_redo_resets_the_cache_without_going_stale,
    test_bracket_matching_ignores_a_carried_over_construct,
]
