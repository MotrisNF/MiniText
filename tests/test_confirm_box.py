"""Covers bugs_conocidos.md: 'Todos los mensajes de y/n en modo mouse,
deben generar un cuadro en el centro con dos botones ... para permitir
la eleccion'."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from commands import CommandMixin  # noqa: E402
from rendering import RenderMixin  # noqa: E402


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


class FakeRenderer(RenderMixin):
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


TESTS = [
    test_geometry_and_render_stay_aligned,
    test_press_on_yes_and_no_returns_the_right_answer,
    test_hover_tracks_which_button_the_mouse_is_over,
    test_long_prompt_clamps_instead_of_disappearing,
    test_terminal_too_narrow_for_buttons_still_returns_none,
]
