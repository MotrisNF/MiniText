"""The blank/unnamed/unmodified "MiniText" placeholder tab (see
tabs.py's own `_is_blank_buffer`) isn't a real file being edited -
entering Insert on it is refused outright, so a blinking terminal
cursor sitting in the empty editing area just looked like there was
something there to type into. Purely cosmetic: the cursor is now
hidden while that placeholder is showing, and shown normally as soon
as there's an actual file (or typed content) to point at."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import rendering  # noqa: E402
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


def _render_frame(editor):
    fake_stdout = FakeStdout()
    original_stdout = sys.stdout
    original_get_size = rendering._get_terminal_size
    rendering._get_terminal_size = lambda: FakeSize()
    sys.stdout = fake_stdout
    try:
        editor._render()
    finally:
        sys.stdout = original_stdout
        rendering._get_terminal_size = original_get_size
    return "".join(fake_stdout.chunks)


def test_cursor_is_hidden_on_the_blank_placeholder_buffer():
    editor = TextEditor(file_name=None)
    frame = _render_frame(editor)
    assert "\x1b[?25l" in frame
    assert "\x1b[?25h" not in frame


def test_cursor_shows_normally_once_a_real_file_is_open():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "a.py")
        with open(path, "w", encoding="utf-8") as file:
            file.write("x = 1\n")
        editor = TextEditor(file_name=path)
        frame = _render_frame(editor)
        assert "\x1b[?25h" in frame


def test_cursor_shows_again_once_the_blank_buffer_has_typed_content():
    editor = TextEditor(file_name=None)
    editor.mode = "insert"
    editor.lines = ["typed"]
    editor.modified = True
    frame = _render_frame(editor)
    assert "\x1b[?25h" in frame


TESTS = [
    test_cursor_is_hidden_on_the_blank_placeholder_buffer,
    test_cursor_shows_normally_once_a_real_file_is_open,
    test_cursor_shows_again_once_the_blank_buffer_has_typed_content,
]
