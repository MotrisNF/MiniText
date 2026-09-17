"""Covers bugs_conocidos.md: the banner/'Open a file to start'
presentation screen above the "Close Mini" button, shown regardless
of MOUSE_ENABLED."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dialogs import (  # noqa: E402
    DialogMixin, _BANNER_LINES, _WELCOME_SUBTITLE,
)


class FakeRenderer(DialogMixin):
    pass


def test_geometry_stacks_banner_above_the_close_button():
    fake = FakeRenderer()
    close_box = fake._centered_box_geometry(
        area_left=0, area_width=90, editor_rows=30, box_width=14,
        box_height=3,
    )
    assert close_box is not None
    banner = fake._welcome_banner_geometry(close_box, 0, 90)
    assert banner is not None
    banner_bottom = (
        banner["banner_top_row_offset"] + len(_BANNER_LINES) - 1
    )
    assert banner_bottom < banner["subtitle_row_offset"]
    assert banner["subtitle_row_offset"] < close_box["top_row_offset"]


def test_geometry_is_none_without_enough_height_above_the_button():
    fake = FakeRenderer()
    # A close_box sitting right at the very top - no room for the
    # banner/subtitle above it.
    close_box = {"top_row_offset": 0}
    assert fake._welcome_banner_geometry(close_box, 0, 60) is None


def test_render_positions_every_line_and_the_subtitle():
    fake = FakeRenderer()
    close_box = fake._centered_box_geometry(
        area_left=0, area_width=90, editor_rows=30, box_width=14,
        box_height=3,
    )
    banner = fake._welcome_banner_geometry(close_box, 0, 90)
    lines = fake._render_welcome_banner(banner)
    assert len(lines) == len(_BANNER_LINES) + 1
    stripped_last = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", lines[-1])
    assert _WELCOME_SUBTITLE in stripped_last


TESTS = [
    test_geometry_stacks_banner_above_the_close_button,
    test_geometry_is_none_without_enough_height_above_the_button,
    test_render_positions_every_line_and_the_subtitle,
]
