"""Regression: a plain mouse click arms `selection_anchor` at the
cursor (see mouse.py's MOUSE_PRESS handling) so a *drag* right after
it can select text - but nothing cleared it if the user typed instead
of dragging. The anchor stayed fixed at the click point while the
cursor moved ahead with every character typed, turning the newly
typed text itself into what looked like a growing selection."""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
from _harness import FakeBuffer  # noqa: E402


def _armed(line=0, column=0):
    """A buffer with `selection_anchor` armed at the cursor - the same
    state a plain mouse click (with no drag) leaves behind."""
    fake = FakeBuffer(["hello world"], line=line, column=column)
    fake.selection_anchor = (line, column)
    return fake


def test_typing_after_a_click_does_not_grow_a_selection():
    fake = _armed()
    for character in "XYZ":
        fake._insert(character)
    assert fake.selection_anchor is None
    assert fake._selection_bounds() is None
    assert fake._selected_text() is None


def test_skipping_over_an_auto_closed_character_also_clears_it():
    """`_insert`'s own early-return path (typing a closing bracket/
    quote that's already there, so it just steps over it) mutates
    nothing and never reaches `_snapshot()` - it still needs to drop
    the anchor, since the cursor still moves."""
    fake = FakeBuffer(['(")"'], line=0, column=1)
    fake.selection_anchor = (0, 1)
    fake._insert(")")
    assert fake.selection_anchor is None


def test_backspace_after_a_click_clears_it():
    fake = _armed(column=5)
    fake._backspace()
    assert fake.selection_anchor is None


def test_delete_forward_after_a_click_clears_it():
    fake = _armed(column=5)
    fake._delete_forward()
    assert fake.selection_anchor is None


def test_new_line_after_a_click_clears_it():
    fake = _armed(column=5)
    fake._new_line()
    assert fake.selection_anchor is None


def test_paste_after_a_click_clears_it():
    fake = _armed(column=5)
    fake._paste("pasted")
    assert fake.selection_anchor is None


def test_moving_a_selected_line_still_preserves_its_own_anchor():
    """The one deliberate exception: `_move_current_line_or_selection`
    is meant to carry a *real* selection along with the line(s) it
    moves - this must keep working, not be swept up by the fix
    above."""
    fake = FakeBuffer(["a", "b", "c"], line=0, column=0)
    fake.selection_anchor = (0, 0)
    fake.column = 1  # a real, non-empty selection: (0,0) to (0,1)
    fake._move_current_line_or_selection(1)
    assert fake.selection_anchor == (1, 0)


TESTS = [
    test_typing_after_a_click_does_not_grow_a_selection,
    test_skipping_over_an_auto_closed_character_also_clears_it,
    test_backspace_after_a_click_clears_it,
    test_delete_forward_after_a_click_clears_it,
    test_new_line_after_a_click_clears_it,
    test_paste_after_a_click_clears_it,
    test_moving_a_selected_line_still_preserves_its_own_anchor,
]
