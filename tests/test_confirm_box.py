"""Covers bugs_conocidos.md: 'Todos los mensajes de y/n en modo mouse,
deben generar un cuadro en el centro con dos botones ... para permitir
la eleccion'."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from commands import CommandMixin  # noqa: E402
from dialogs import (  # noqa: E402
    DialogMixin, _CONFIRM_MAX_VISIBLE_ITEMS,
)


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


class FakeRenderer(DialogMixin):
    pass


class FakeCommands(CommandMixin):
    pass


def test_geometry_and_render_stay_aligned():
    fake = FakeRenderer()
    box = fake._confirm_box_geometry(
        area_left=0, area_width=60, editor_rows=20,
        prompt="Delete file 'test.py'? (y/n)",
    )
    lines = fake._render_confirm_box(box, {"hovered": None})
    buttons_visible = _strip_ansi(lines[2].split("H", 1)[1])
    yes_slice = buttons_visible[
        box["yes_col_start"] - box["left"]:box["yes_col_end"] - box["left"] + 1
    ]
    no_slice = buttons_visible[
        box["no_col_start"] - box["left"]:box["no_col_end"] - box["left"] + 1
    ]
    assert yes_slice == "[ Yes ]", yes_slice
    assert no_slice == "[ No ]", no_slice


def test_press_on_yes_and_no_returns_the_right_answer():
    fake = FakeCommands()
    box = {
        "buttons_row_offset": 2, "yes_col_start": 5, "yes_col_end": 11,
        "no_col_start": 15, "no_col_end": 20,
    }
    fake._mouse_layout = {"confirm_box": box}
    fake._confirm_dialog = {"prompt": "x?", "hovered": None}
    row = box["buttons_row_offset"] + 2
    assert fake._handle_confirm_mouse_event(
        f"MOUSE_PRESS:{box['yes_col_start'] + 1}:{row}"
    ) is True
    assert fake._handle_confirm_mouse_event(
        f"MOUSE_PRESS:{box['no_col_start'] + 1}:{row}"
    ) is False
    assert fake._handle_confirm_mouse_event(f"MOUSE_PRESS:1:{row}") is None


def test_hover_tracks_which_button_the_mouse_is_over():
    fake = FakeCommands()
    box = {
        "buttons_row_offset": 2, "yes_col_start": 5, "yes_col_end": 11,
        "no_col_start": 15, "no_col_end": 20,
    }
    fake._mouse_layout = {"confirm_box": box}
    fake._confirm_dialog = {"prompt": "x?", "hovered": None}
    row = box["buttons_row_offset"] + 2
    yes_col, no_col = box["yes_col_start"] + 1, box["no_col_start"] + 1
    fake._handle_confirm_mouse_event(f"MOUSE_MOVE:{yes_col}:{row}")
    assert fake._confirm_dialog["hovered"] == "yes"
    fake._handle_confirm_mouse_event(f"MOUSE_MOVE:{no_col}:{row}")
    assert fake._confirm_dialog["hovered"] == "no"


def test_long_prompt_clamps_instead_of_disappearing():
    """A drag & drop of several/long file names can produce a prompt
    wider than the available code area - the box used to just vanish
    (geometry returned None) while _confirm kept blocking on
    keyboard input with nothing shown on screen for it."""
    fake = FakeRenderer()
    long_prompt = (
        "Move a_long_file_name_1.py, a_long_file_name_2.py, "
        "a_long_file_name_3.py to 'a_fairly_long_folder_name'? (y/n)"
    )
    area_width = 79  # typical MAX_COLS with the worktree panel open
    assert len(long_prompt) + 4 > area_width
    box = fake._confirm_box_geometry(0, area_width, 20, long_prompt)
    assert box is not None
    assert box["width"] <= area_width
    lines = fake._render_confirm_box(box, {"hovered": None})
    assert len(lines) == 4


def test_terminal_too_narrow_for_buttons_still_returns_none():
    fake = FakeRenderer()
    box = fake._confirm_box_geometry(0, 10, 20, "x? (y/n)")
    assert box is None


def test_long_item_list_scrolls_instead_of_truncating():
    """Covers bugs_conocidos.md: moving/deleting many files used to be
    a single comma-joined prompt line that just got clipped once it
    didn't fit - `items` now paginates instead, capped at
    `_CONFIRM_MAX_VISIBLE_ITEMS` rows visible at once, with every
    name still reachable by scrolling further down."""
    fake = FakeRenderer()
    prompt = "Delete 20 items? (y/n)"
    items = [f"file_{i}.py" for i in range(20)]
    box = fake._confirm_box_geometry(0, 79, 30, prompt, items)
    assert box is not None
    assert box["visible_rows"] == _CONFIRM_MAX_VISIBLE_ITEMS
    assert box["has_more_above"] is False
    assert box["has_more_below"] is True
    lines = fake._render_confirm_box(box, {"hovered": None})
    assert len(lines) == 4 + box["visible_rows"]
    first_list_row = _strip_ansi(lines[2].split("H", 1)[1])
    assert "file_0.py" in first_list_row

    max_scroll = len(items) - box["visible_rows"]
    end_box = fake._confirm_box_geometry(
        0, 79, 30, prompt, items, scroll=max_scroll
    )
    assert end_box["has_more_above"] is True
    assert end_box["has_more_below"] is False
    end_lines = fake._render_confirm_box(end_box, {"hovered": None})
    last_list_row = _strip_ansi(
        end_lines[1 + end_box["visible_rows"]].split("H", 1)[1]
    )
    assert "file_19.py" in last_list_row


def test_scroll_clamps_when_the_terminal_gets_shorter():
    """`scroll` is persisted on `_confirm_dialog` across frames - if
    the terminal shrinks (or the mouse layer just hands back a stale
    value) while scrolled near the end, geometry must clamp it back
    into range itself rather than slicing past the list."""
    fake = FakeRenderer()
    items = [f"file_{i}.py" for i in range(20)]
    box = fake._confirm_box_geometry(
        0, 79, 30, "Delete 20 items? (y/n)", items, scroll=9999,
    )
    assert box["scroll"] == len(items) - box["visible_rows"]


def test_editor_rows_too_short_shrinks_visible_rows_instead_of_failing():
    fake = FakeRenderer()
    items = [f"file_{i}.py" for i in range(20)]
    box = fake._confirm_box_geometry(
        0, 79, 5, "Delete 20 items? (y/n)", items,
    )
    assert box is not None
    assert box["visible_rows"] == 1


def test_short_list_shows_no_scroll_indicator():
    fake = FakeRenderer()
    items = ["a.txt", "b.txt", "c.txt"]
    box = fake._confirm_box_geometry(
        0, 79, 30, "Delete 3 items? (y/n)", items,
    )
    lines = fake._render_confirm_box(box, {"hovered": None})
    list_rows = [
        _strip_ansi(line.split("H", 1)[1])
        for line in lines[2:2 + box["visible_rows"]]
    ]
    assert all("▲" not in row and "▼" not in row for row in list_rows)


def test_scroll_indicator_appears_only_on_the_side_with_more_items():
    fake = FakeRenderer()
    prompt = "Delete 20 items? (y/n)"
    items = [f"file_{i}.py" for i in range(20)]
    top_box = fake._confirm_box_geometry(0, 79, 30, prompt, items)
    top_lines = fake._render_confirm_box(top_box, {"hovered": None})
    top_rows = [
        _strip_ansi(line.split("H", 1)[1])
        for line in top_lines[2:2 + top_box["visible_rows"]]
    ]
    assert "▼" in top_rows[-1]
    assert "▲" not in "".join(top_rows)

    max_scroll = len(items) - top_box["visible_rows"]
    bottom_box = fake._confirm_box_geometry(
        0, 79, 30, prompt, items, scroll=max_scroll,
    )
    bottom_lines = fake._render_confirm_box(bottom_box, {"hovered": None})
    bottom_rows = [
        _strip_ansi(line.split("H", 1)[1])
        for line in bottom_lines[2:2 + bottom_box["visible_rows"]]
    ]
    assert "▲" in bottom_rows[0]
    assert "▼" not in "".join(bottom_rows)


def test_combined_indicator_when_only_one_row_is_visible():
    """A terminal short enough to only fit one visible list row, but
    scrolled to somewhere in the middle, is hiding items on both ends
    at once - one glyph has to stand for both."""
    fake = FakeRenderer()
    items = [f"file_{i}.py" for i in range(20)]
    box = fake._confirm_box_geometry(
        0, 79, 5, "Delete 20 items? (y/n)", items, scroll=10,
    )
    assert box["visible_rows"] == 1
    lines = fake._render_confirm_box(box, {"hovered": None})
    list_row = _strip_ansi(lines[2].split("H", 1)[1])
    assert "↕" in list_row


def test_overlong_item_name_is_ellipsized_not_wrapped():
    fake = FakeRenderer()
    long_name = "a" * 200
    box = fake._confirm_box_geometry(
        0, 79, 30, "Delete 2 items? (y/n)", [long_name, "b.txt"],
    )
    lines = fake._render_confirm_box(box, {"hovered": None})
    first_row = _strip_ansi(lines[2].split("H", 1)[1])
    assert "…" in first_row
    assert len(first_row) == box["width"]


def test_wheel_scrolls_the_item_list_and_clamps_at_both_ends():
    renderer = FakeRenderer()
    items = [f"file_{i}.py" for i in range(20)]
    box = renderer._confirm_box_geometry(
        0, 79, 30, "Delete 20 items? (y/n)", items,
    )
    fake = FakeCommands()
    fake._mouse_layout = {"confirm_box": box}
    fake._confirm_dialog = {
        "prompt": "x", "hovered": None, "items": items, "scroll": 0,
    }
    assert fake._handle_confirm_mouse_event("MOUSE_WHEEL_UP:1:1") is None
    assert fake._confirm_dialog["scroll"] == 0
    max_scroll = len(items) - box["visible_rows"]
    for _ in range(max_scroll + 5):
        fake._handle_confirm_mouse_event("MOUSE_WHEEL_DOWN:1:1")
    assert fake._confirm_dialog["scroll"] == max_scroll
    fake._handle_confirm_mouse_event("MOUSE_WHEEL_UP:1:1")
    assert fake._confirm_dialog["scroll"] == max_scroll - 1


def test_wheel_is_a_no_op_when_the_whole_list_already_fits():
    renderer = FakeRenderer()
    items = ["a.txt", "b.txt"]
    box = renderer._confirm_box_geometry(
        0, 79, 30, "Delete 2 items? (y/n)", items,
    )
    fake = FakeCommands()
    fake._mouse_layout = {"confirm_box": box}
    fake._confirm_dialog = {
        "prompt": "x", "hovered": None, "items": items, "scroll": 0,
    }
    fake._handle_confirm_mouse_event("MOUSE_WHEEL_DOWN:1:1")
    assert fake._confirm_dialog["scroll"] == 0


def test_wheel_without_items_never_touches_scroll():
    """A plain confirm (no `items`, e.g. closing a modified tab) still
    reaches `_handle_confirm_mouse_event` for its Yes/No buttons - a
    stray wheel event over it must stay a no-op instead of crashing on
    the list bookkeeping that isn't there."""
    fake = FakeCommands()
    fake._mouse_layout = {"confirm_box": {
        "buttons_row_offset": 2, "yes_col_start": 5, "yes_col_end": 11,
        "no_col_start": 15, "no_col_end": 20,
    }}
    fake._confirm_dialog = {"prompt": "x?", "hovered": None}
    assert fake._handle_confirm_mouse_event("MOUSE_WHEEL_DOWN:1:1") is None
    assert fake._confirm_dialog.get("scroll") is None


def test_closing_confirm_box_over_the_welcome_screen_forces_a_full_redraw():
    """Covers bugs_conocidos.md: a worktree delete/move confirm on the
    blank/unnamed last-tab screen (where "Close Mini" is also showing)
    used to leave the confirm box's own border/list behind once it
    closed - `render`'s full-redraw check ranked close_box ahead of
    confirm_box, so close_box staying up the whole time hid confirm_
    box's own appearing/disappearing. Needs the real `TextEditor` (not
    the lightweight `FakeRenderer`/`FakeCommands` used elsewhere in
    this file) since the bug is in `render`'s own bookkeeping across
    two full frames, not in any one geometry/dispatch helper."""
    import theme
    import rendering
    from text_editor import TextEditor

    class FakeSize:
        columns, lines = 80, 24

    original_get_size = rendering._get_terminal_size
    original_mouse_enabled = theme.MOUSE_ENABLED
    rendering._get_terminal_size = lambda: FakeSize()
    theme.MOUSE_ENABLED = True

    class FakeStdout:
        def __init__(self):
            self.chunks = []

        def write(self, text):
            self.chunks.append(text)

        def flush(self):
            pass

    fake_stdout = FakeStdout()
    original_stdout = sys.stdout
    sys.stdout = fake_stdout
    try:
        editor = TextEditor(file_name=None)  # blank buffer, one tab
        editor._confirm_dialog = {
            "prompt": "Delete 3 items? (y/n)", "hovered": None,
            "items": ["a.txt", "b.txt", "c.txt"], "scroll": 0,
        }
        editor._render()
        fake_stdout.chunks.clear()
        editor._confirm_dialog = None
        editor._render()
        closing_frame = "".join(fake_stdout.chunks)
    finally:
        sys.stdout = original_stdout
        rendering._get_terminal_size = original_get_size
        theme.MOUSE_ENABLED = original_mouse_enabled
    assert "\x1b[2J" in closing_frame


TESTS = [
    test_geometry_and_render_stay_aligned,
    test_press_on_yes_and_no_returns_the_right_answer,
    test_hover_tracks_which_button_the_mouse_is_over,
    test_long_prompt_clamps_instead_of_disappearing,
    test_terminal_too_narrow_for_buttons_still_returns_none,
    test_long_item_list_scrolls_instead_of_truncating,
    test_scroll_clamps_when_the_terminal_gets_shorter,
    test_editor_rows_too_short_shrinks_visible_rows_instead_of_failing,
    test_short_list_shows_no_scroll_indicator,
    test_scroll_indicator_appears_only_on_the_side_with_more_items,
    test_combined_indicator_when_only_one_row_is_visible,
    test_overlong_item_name_is_ellipsized_not_wrapped,
    test_wheel_scrolls_the_item_list_and_clamps_at_both_ends,
    test_wheel_is_a_no_op_when_the_whole_list_already_fits,
    test_wheel_without_items_never_touches_scroll,
    test_closing_confirm_box_over_the_welcome_screen_forces_a_full_redraw,
]
