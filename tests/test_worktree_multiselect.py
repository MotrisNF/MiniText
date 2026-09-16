"""Covers bugs_conocidos.md: 'El modo mouse enable debe permitir
seleccion multiple de archivos pulsando Ctrl + click'."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import terminal  # noqa: E402
import theme  # noqa: E402
from worktree import WorktreePanelMixin  # noqa: E402


class FakePanel(WorktreePanelMixin):
    def __init__(self, root):
        self.worktree_root = root
        self.worktree_show_hidden = True
        self.worktree_expanded = set()
        self.worktree_cursor = 0
        self.worktree_scroll = 0
        self.worktree_focused = True
        self.worktree_visible = True
        self.worktree_visible_because_of_focus = False
        self.worktree_selected_dir = root
        self.worktree_selected_entries = set()
        self._worktree_entries_cache = None
        self.file_name = None
        self.lines = [""]
        self.modified = False
        self._hovered_worktree_delete = None
        self._hovered_worktree_row = None
        self._hovered_worktree_button = None


def _make_event(code, col, row, final="M"):
    payload = f"{code};{col};{row}{final}"
    data = iter(payload.encode())
    orig_read, orig_select = terminal._read_stdin_byte, terminal.select.select
    terminal._read_stdin_byte = lambda fd: bytes([next(data)])
    terminal.select.select = lambda *a, **k: ([1], [], [])
    try:
        return terminal._read_mouse_event(0)
    finally:
        terminal._read_stdin_byte = orig_read
        terminal.select.select = orig_select


def test_ctrl_bit_only_appended_to_press_events():
    assert _make_event(0, 5, 10) == "MOUSE_PRESS:5:10"
    assert _make_event(16, 5, 10) == "MOUSE_PRESS:5:10:ctrl"
    assert _make_event(48, 5, 10) == "MOUSE_DRAG:5:10"  # ctrl + motion bit
    assert _make_event(0, 5, 10, final="m") == "MOUSE_RELEASE:5:10"


def test_ctrl_click_toggles_selection_without_moving_cursor():
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        open(os.path.join(tmp, "b.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        b_path = os.path.join(tmp, "b.txt")
        fake._handle_worktree_click(2, ctrl_held=True)  # row 2 -> b.txt
        assert fake.worktree_selected_entries == {b_path}
        assert fake.worktree_cursor == 0  # untouched by a ctrl+click
        fake._handle_worktree_click(2, ctrl_held=True)  # toggle off
        assert fake.worktree_selected_entries == set()


def test_plain_click_on_an_unselected_entry_clears_the_multiselection():
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        open(os.path.join(tmp, "b.txt"), "w", encoding="utf-8").close()
        open(os.path.join(tmp, "c.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._handle_worktree_click(2, ctrl_held=True)  # select b.txt
        assert fake.worktree_selected_entries
        fake._handle_worktree_click(3)  # plain click on c.txt (unselected)
        assert fake.worktree_selected_entries == set()


def test_plain_click_on_an_already_selected_entry_preserves_it():
    """Covers bugs_conocidos.md: multi-selecting several entries then
    starting a drag (a plain MOUSE_PRESS on one of them) used to wipe
    the whole selection before the drag could ever use it, making
    "move/delete several at once" effectively impossible."""
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        open(os.path.join(tmp, "b.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._handle_worktree_click(2, ctrl_held=True)  # select b.txt
        selection_before = set(fake.worktree_selected_entries)
        assert selection_before
        fake._handle_worktree_click(2)  # plain click on the same b.txt
        assert fake.worktree_selected_entries == selection_before


def test_rendering_a_multiselected_row_does_not_crash():
    """Regression test: rendering used to crash with AttributeError
    (theme.WORD_MATCH_COLOR doesn't exist - only WORD_MATCH_START/END
    do, since it's a background color) the moment a Ctrl+click
    selection existed on a row that wasn't also the cursor."""
    theme.MOUSE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        b_path = os.path.join(tmp, "b.txt")
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree_selected_entries = {b_path}  # cursor stays on a.txt
        lines = fake._worktree_body_lines(5)  # must not raise
        assert lines[2].startswith(theme.WORD_MATCH_START)
        assert lines[2].endswith(theme.WORD_MATCH_END)


TESTS = [
    test_ctrl_bit_only_appended_to_press_events,
    test_ctrl_click_toggles_selection_without_moving_cursor,
    test_plain_click_on_an_unselected_entry_clears_the_multiselection,
    test_plain_click_on_an_already_selected_entry_preserves_it,
    test_rendering_a_multiselected_row_does_not_crash,
]
