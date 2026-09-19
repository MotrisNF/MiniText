"""Without bracketed paste, a real paste (the terminal's own native
one - not Mini's internal `:v`/`v`) arrived as a plain stream of keys
indistinguishable from typing: every newline inside it ran through
`_new_line`'s own auto-indent, compounding whatever indentation the
pasted text already had, line after line. `\\x1b[?2004h` makes the
terminal wrap a real paste in `\\x1b[200~`...`\\x1b[201~` instead, so
it can be read as one piece and hand it straight to `_paste()` -
exactly how `:v` already avoids the same problem for Mini's own
internal clipboard."""

import base64
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import terminal  # noqa: E402
from commands import CommandMixin  # noqa: E402
from editing import BufferEditMixin  # noqa: E402
from text_editor import TextEditor  # noqa: E402


def _feed_bracketed_paste(text):
    """Reads `text` back out of `terminal.read_key()` as if a real
    terminal had just sent it as one bracketed paste - patches
    `os.read` rather than `_read_stdin_byte` directly, since a
    "\\x1b[200~" (unlike "\\x1b[<..." for a mouse event) doesn't match
    on its very next byte and has to be peeked then pushed back onto
    `_pending_byte` first; replacing `_read_stdin_byte` outright (the
    simpler pattern other terminal.py tests use, safe only when they
    never hit that pushback path) would silently swallow it instead."""
    payload = ("\x1b[200~" + text + "\x1b[201~").encode("utf-8")
    data = iter(payload)

    def fake_os_read(fd, count):
        try:
            return bytes([next(data)])
        except StopIteration:
            return b""

    original_read, original_select = os.read, terminal.select.select
    os.read = fake_os_read
    terminal.select.select = lambda *a, **k: ([1], [], [])
    try:
        return terminal.read_key()
    finally:
        os.read = original_read
        terminal.select.select = original_select


def test_bracketed_paste_is_read_as_one_atomic_event():
    pasted = "if True:\n    x = 1\n    y = 2\n"
    assert _feed_bracketed_paste(pasted) == "PASTE:" + pasted


def test_bracketed_paste_preserves_special_characters_verbatim():
    pasted = "  tabs\tand \"quotes\" and 'apostrophes'"
    assert _feed_bracketed_paste(pasted) == "PASTE:" + pasted


def test_bracketed_paste_end_marker_is_not_left_in_the_content():
    assert "\x1b[201~" not in _feed_bracketed_paste("just some text")


def _editor_for(code=""):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "f.py")
    with open(path, "w", encoding="utf-8") as file:
        file.write(code)
    return TextEditor(path)


def test_pasting_multiline_indented_text_does_not_compound_indentation():
    """The actual bug: pasting text that's already indented used to
    get every one of its own lines re-indented on top of what it
    already had, via `_new_line`'s auto-indent, once per line."""
    editor = _editor_for()
    editor.mode = "insert"
    editor._handle_paste_event("if True:\n    x = 1\n    y = 2\n")
    assert editor.lines == ["if True:", "    x = 1", "    y = 2", ""]


def test_paste_replaces_an_active_selection():
    editor = _editor_for("hello world")
    editor.mode = "insert"
    editor.line, editor.column = 0, 0
    editor.selection_anchor = (0, 0)
    editor.column = 5  # selects "hello"
    editor._handle_paste_event("goodbye")
    assert editor.lines == ["goodbye world"]


def test_paste_is_ignored_outside_insert_mode():
    editor = _editor_for("original")
    editor.mode = "visual"
    editor._handle_paste_event("should not appear")
    assert editor.lines == ["original"]


def test_paste_forwards_to_the_run_panel_when_focused():
    editor = _editor_for()
    editor.run_panel.focused = True
    read_fd, write_fd = os.pipe()
    editor.run_panel.master_fd = write_fd
    try:
        editor._handle_paste_event("ls -la\n")
    finally:
        os.close(write_fd)
    with os.fdopen(read_fd, "rb") as file:
        assert file.read() == b"ls -la\n"


def test_copy_to_system_clipboard_sends_osc52():
    captured = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = captured
    try:
        terminal.copy_to_system_clipboard("hello world")
    finally:
        sys.stdout = original_stdout
    expected = base64.b64encode(b"hello world").decode("ascii")
    assert captured.getvalue() == f"\x1b]52;c;{expected}\x07"


class FakeEditor(CommandMixin, BufferEditMixin):
    def __init__(self, lines):
        self.lines = lines
        self.line = 0
        self.column = 0
        self.selection_anchor = None
        self.clipboard = None
        self.status = ""


def test_copying_a_line_also_reaches_the_system_clipboard():
    captured = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = captured
    try:
        fake = FakeEditor(["some line"])
        fake._copy_selection_or_line()
    finally:
        sys.stdout = original_stdout
    expected = base64.b64encode(b"some line").decode("ascii")
    assert f"\x1b]52;c;{expected}\x07" in captured.getvalue()


TESTS = [
    test_bracketed_paste_is_read_as_one_atomic_event,
    test_bracketed_paste_preserves_special_characters_verbatim,
    test_bracketed_paste_end_marker_is_not_left_in_the_content,
    test_pasting_multiline_indented_text_does_not_compound_indentation,
    test_paste_replaces_an_active_selection,
    test_paste_is_ignored_outside_insert_mode,
    test_paste_forwards_to_the_run_panel_when_focused,
    test_copy_to_system_clipboard_sends_osc52,
    test_copying_a_line_also_reaches_the_system_clipboard,
]
