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
    fake._handle_confirm_mouse_event(f"MOUSE_MOVE:{box['yes_col_start'] + 1}:{row}")
    assert fake._confirm_dialog["hovered"] == "yes"
    fake._handle_confirm_mouse_event(f"MOUSE_MOVE:{box['no_col_start'] + 1}:{row}")
    assert fake._confirm_dialog["hovered"] == "no"


TESTS = [
    test_geometry_and_render_stay_aligned,
    test_press_on_yes_and_no_returns_the_right_answer,
    test_hover_tracks_which_button_the_mouse_is_over,
]
