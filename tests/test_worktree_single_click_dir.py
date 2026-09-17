"""Covers bugs_conocidos.md: 'Un solo clic sobre un directorio en el
worktree lo colapsa/expande'."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
from worktree import WorktreePanelMixin  # noqa: E402


class FakePanel(WorktreePanelMixin):
    def __init__(self, root):
        self.worktree_root = root
        self.worktree_root_collapsed = False
        self.worktree_show_hidden = True
        self.worktree_expanded = set()
        self.worktree_cursor = 0
        self.worktree_scroll = 0
        self.worktree_focused = False
        self.worktree_visible = False
        self.worktree_visible_because_of_focus = False
        self.worktree_new_entry_dir = root
        self.worktree_selected_entries = set()
        self._worktree_entries_cache = None
        self.file_name = None
        self.lines = [""]
        self.modified = False


def test_single_click_on_directory_expands_it_once_panel_is_focused():
    with tempfile.TemporaryDirectory() as tmp:
        os.mkdir(os.path.join(tmp, "sub"))
        fake = FakePanel(tmp)
        # A click that also focuses the panel never activates anything
        # (see _handle_worktree_click), so clicking the root itself
        # (row 0) here is just "focus the panel" - same as clicking
        # any other row would have been.
        fake._handle_worktree_click(0)
        assert fake.worktree_focused is True
        entries = fake._worktree_entries()
        # entries[0] is the root; the direct index into `entries`
        # already is the correct panel_row for everything else.
        dir_row = next(i for i, e in enumerate(entries) if e[1] == "sub")
        assert not fake.worktree_expanded
        fake._handle_worktree_click(dir_row)  # single click on the dir
        sub_path = os.path.join(tmp, "sub")
        assert sub_path in fake.worktree_expanded


def test_single_click_on_file_still_only_selects():
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        open(os.path.join(tmp, "b.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._handle_worktree_click(0)  # focuses the panel (row 0 = root)
        fake._handle_worktree_click(2)  # single click on the 2nd file (b.txt)
        assert fake.file_name is None  # not opened yet - needs a 2nd click
        assert fake.worktree_cursor == 2


TESTS = [
    test_single_click_on_directory_expands_it_once_panel_is_focused,
    test_single_click_on_file_still_only_selects,
]
