""""Highlight every other occurrence" used to be derived purely from
the active text selection (`_current_selection_word`) - elegant, but
anything that cleared the selection (the mouse wheel, deliberately,
since 1.8.3) wiped the highlight right along with it, even though
scrolling to look for more matches is exactly when you'd want it to
stay. `_highlight_query`/`_highlight_whole_word` now persist
independently of the selection/search that first set them."""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import theme  # noqa: E402
from text_editor import TextEditor  # noqa: E402


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def _editor_for(code, suffix=".py"):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, f"f{suffix}")
    with open(path, "w", encoding="utf-8") as file:
        file.write(code)
    return TextEditor(path)


def test_double_click_highlights_other_occurrences():
    theme.MOUSE_ENABLED = True
    editor = _editor_for("foo = 1\nbar = foo + 1\n")
    editor._render()
    editor._handle_mouse_event("MOUSE_PRESS:1:2")
    editor._handle_mouse_event("MOUSE_PRESS:1:2")  # double-click "foo"
    editor._render()
    assert editor._highlight_query == "foo"
    assert editor._highlight_whole_word is True


def test_wheel_scroll_no_longer_clears_the_highlight():
    """The actual bug: scrolling with the mouse wheel used to erase
    the highlight along with the selection it came from - the
    selection itself still clears (unrelated 1.8.3 fix, must keep
    working), but the highlight now survives past it."""
    theme.MOUSE_ENABLED = True
    editor = _editor_for("foo = 1\nbar = foo + 1\nbaz = foo + 2\n")
    editor._render()
    editor._handle_mouse_event("MOUSE_PRESS:1:2")
    editor._handle_mouse_event("MOUSE_PRESS:1:2")
    editor._render()
    assert editor._highlight_query == "foo"
    assert editor.selection_anchor is not None

    editor._handle_mouse_event("MOUSE_WHEEL_DOWN:1:2")
    editor._render()
    assert editor._highlight_query == "foo"
    assert editor.selection_anchor is None


def test_live_search_highlights_as_a_substring_while_typing():
    """Unlike double-click's whole-word matching, a search for "urn"
    must find it inside "return" too - no word-boundary requirement."""
    editor = _editor_for("return_value = 1\n")
    editor.mode = "visual"
    editor.search_query = ""
    for character in "urn":
        editor._handle_search_mode_key(character)
    assert editor._highlight_query == "urn"
    assert editor._highlight_whole_word is False
    editor._render()
    row_text = next(
        text for text in editor._last_rendered_rows.values()
        if "return_value" in _strip_ansi(text)
    )
    assert theme.WORD_MATCH_START in row_text


def test_highlight_survives_executing_the_search():
    editor = _editor_for("return_value = 1\n")
    editor.mode = "visual"
    editor.search_query = ""
    for character in "value":
        editor._handle_search_mode_key(character)
    editor._handle_search_mode_key("\r")
    assert editor._highlight_query == "value"
    assert editor.status == "Found 'value'"


def test_cancelling_the_search_with_escape_clears_the_highlight():
    editor = _editor_for("return_value = 1\n")
    editor.mode = "visual"
    editor.search_query = ""
    editor._handle_search_mode_key("v")
    assert editor._highlight_query == "v"
    editor._handle_search_mode_key("\x1b")
    assert editor._highlight_query is None


def test_escape_in_visual_mode_clears_the_highlight():
    editor = _editor_for("foo = 1\n")
    editor.selection_anchor = (0, 0)
    editor.column = 3
    editor._render()
    assert editor._highlight_query == "foo"
    editor.mode = "visual"
    editor._handle_editing_key("\x1b")
    assert editor._highlight_query is None


def test_clicking_anywhere_in_mouse_mode_clears_the_highlight():
    theme.MOUSE_ENABLED = True
    editor = _editor_for("foo = 1\nbar = foo + 1\n")
    editor._render()
    editor._handle_mouse_event("MOUSE_PRESS:1:2")
    editor._handle_mouse_event("MOUSE_PRESS:1:2")
    editor._render()
    assert editor._highlight_query == "foo"

    editor._handle_mouse_event("MOUSE_PRESS:1:3")  # a later, plain click
    assert editor._highlight_query is None


TESTS = [
    test_double_click_highlights_other_occurrences,
    test_wheel_scroll_no_longer_clears_the_highlight,
    test_live_search_highlights_as_a_substring_while_typing,
    test_highlight_survives_executing_the_search,
    test_cancelling_the_search_with_escape_clears_the_highlight,
    test_escape_in_visual_mode_clears_the_highlight,
    test_clicking_anywhere_in_mouse_mode_clears_the_highlight,
]
