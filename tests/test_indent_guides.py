"""Vertical indentation guides: a "│" at each indentation level,
running down every line of a block - including blank lines inside one,
which borrow the next non-blank line's own depth (VS Code-style)
rather than showing nothing. Purely cosmetic, computed fresh (well,
lazily cached) per render - never touches the buffer itself."""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import rendering  # noqa: E402
import theme  # noqa: E402
from text_editor import TextEditor  # noqa: E402


class FakeSize:
    columns, lines = 80, 24


class FakeStdout:
    def __init__(self):
        self.chunks = []

    def write(self, text):
        self.chunks.append(text)

    def flush(self):
        pass


def _render_rows(editor):
    """{row_number: plain_text_with_ansi_removed} for every editor row
    a real `_render()` pass writes to, plus a parallel dict of the raw
    (still-colored) text for callers that need to check ANSI codes."""
    original_get_size = rendering._get_terminal_size
    rendering._get_terminal_size = lambda: FakeSize()
    fake_stdout = FakeStdout()
    original_stdout = sys.stdout
    sys.stdout = fake_stdout
    try:
        editor._render()
    finally:
        sys.stdout = original_stdout
        rendering._get_terminal_size = original_get_size
    frame = "".join(fake_stdout.chunks)
    raw_rows = {}
    for match in re.finditer(
        r'\x1b\[(\d+);1H\x1b\[K(.*?)(?=\x1b\[\d+;1H|\Z)', frame, re.S,
    ):
        raw_rows[int(match.group(1))] = match.group(2)
    plain_rows = {
        row: re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
        for row, text in raw_rows.items()
    }
    return plain_rows, raw_rows


def _editor_for(code, suffix=".py"):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, f"f{suffix}")
    with open(path, "w", encoding="utf-8") as file:
        file.write(code)
    editor = TextEditor(path)
    editor._force_full_redraw = True
    return editor


def test_guides_appear_at_each_nesting_level():
    editor = _editor_for(
        "def outer():\n"
        "    if x:\n"
        "        return 1\n"
    )
    plain, _ = _render_rows(editor)
    assert "│" not in plain[2]  # def outer(): - top level, no guide
    assert plain[3].count("│") == 1  # if x: - one level deep
    assert plain[4].count("│") == 2  # return 1 - two levels deep


def test_blank_line_borrows_the_next_non_blank_lines_depth():
    editor = _editor_for(
        "def outer():\n"
        "    if x:\n"
        "        do_a()\n"
        "\n"
        "        do_b()\n"
    )
    plain, _ = _render_rows(editor)
    assert plain[4].count("│") == 2  # do_a()
    assert plain[5].count("│") == 2  # the blank line - borrows do_b()'s
    assert plain[6].count("│") == 2  # do_b()


def test_trailing_blank_lines_at_eof_show_no_guide():
    editor = _editor_for(
        "def outer():\n"
        "    return 1\n"
        "\n"
    )
    plain, _ = _render_rows(editor)
    assert "│" not in plain.get(4, "")


def test_guides_are_colored_and_dont_disturb_syntax_highlighting():
    editor = _editor_for("def outer():\n    if x:\n        return 1\n")
    _, raw = _render_rows(editor)
    assert theme.INDENT_GUIDE_COLOR in raw[3]
    assert theme.KEYWORD_COLOR in raw[3]  # "if" is still highlighted
    assert theme.DECLARATION_COLOR in raw[2]  # "def" is still highlighted


def test_toggle_off_shows_no_guides_at_all():
    editor = _editor_for("def outer():\n    if x:\n        return 1\n")
    original = theme.SHOW_INDENT_GUIDES
    theme.SHOW_INDENT_GUIDES = False
    try:
        plain, _ = _render_rows(editor)
    finally:
        theme.SHOW_INDENT_GUIDES = original
    assert all("│" not in text for text in plain.values())


def test_guides_are_suppressed_inside_a_multiline_docstring():
    """Whitespace that merely *looks* like indentation inside a
    docstring's own content isn't real code structure - the opening
    and closing lines (their own entry_state is None - nothing is
    carried *into* them) still get guides from their real leading
    indentation, same as any other line."""
    editor = _editor_for(
        'def f():\n'
        '    """\n'
        '    docstring text\n'
        '    """\n'
        '    return 1\n'
    )
    plain, _ = _render_rows(editor)
    assert "│" in plain[3]  # the opening \"\"\" line - real indentation
    assert "│" not in plain[4]  # inside the docstring - suppressed
    assert "│" not in plain[5]  # the closing \"\"\" line - suppressed
    assert "│" in plain[6]  # back to real code


def test_guides_work_with_tab_indentation():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "f.py")
    with open(path, "wb") as file:
        file.write(b"def f():\n\tif x:\n\t\treturn 1\n")
    editor = TextEditor(path)
    editor._force_full_redraw = True
    plain, _ = _render_rows(editor)
    assert plain[3].count("│") == 1
    assert plain[4].count("│") == 2


def test_uneven_indentation_gets_no_partial_guide():
    """3 spaces with TAB_SIZE=4 doesn't reach a full level - no guide
    drawn for a position that wouldn't line up with the real grid."""
    editor = _editor_for("def f():\n   x = 1\n")
    plain, _ = _render_rows(editor)
    assert "│" not in plain[3]


TESTS = [
    test_guides_appear_at_each_nesting_level,
    test_blank_line_borrows_the_next_non_blank_lines_depth,
    test_trailing_blank_lines_at_eof_show_no_guide,
    test_guides_are_colored_and_dont_disturb_syntax_highlighting,
    test_toggle_off_shows_no_guides_at_all,
    test_guides_are_suppressed_inside_a_multiline_docstring,
    test_guides_work_with_tab_indentation,
    test_uneven_indentation_gets_no_partial_guide,
]
