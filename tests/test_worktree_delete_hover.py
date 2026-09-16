"""Covers bugs_conocidos.md: 'En el modo mouse enabled, los archivos
deben tener un aspa a su derecha al pasar el raton por encima, que al
hacer click sobre ella preguntara si se desea eliminar'."""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import theme  # noqa: E402
from worktree import WorktreePanelMixin, WORKTREE_WIDTH  # noqa: E402


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


class FakePanel(WorktreePanelMixin):
    def __init__(self, root):
        self.worktree_root = root
        self.worktree_show_hidden = True
        self.worktree_expanded = set()
        self.worktree_cursor = 0
        self.worktree_scroll = 0
        self._worktree_entries_cache = None
        self._hovered_worktree_delete = None
        self.worktree_selected_entries = set()
        self._hovered_worktree_button = None


def test_hit_test_only_matches_last_two_columns_of_a_real_entry_row():
    theme.MOUSE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        assert fake._worktree_delete_hit_test(1, WORKTREE_WIDTH - 1) == 0
        assert fake._worktree_delete_hit_test(1, WORKTREE_WIDTH - 2) == 0
        assert fake._worktree_delete_hit_test(1, WORKTREE_WIDTH - 3) is None
        assert fake._worktree_delete_hit_test(0, WORKTREE_WIDTH - 1) is None


def test_hit_test_disabled_without_mouse():
    theme.MOUSE_ENABLED = False
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        assert fake._worktree_delete_hit_test(1, WORKTREE_WIDTH - 1) is None
    theme.MOUSE_ENABLED = True


def test_delete_cross_only_shown_on_the_hovered_row():
    theme.MOUSE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        open(os.path.join(tmp, "b.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._hovered_worktree_delete = 1
        lines = [_strip_ansi(line) for line in fake._worktree_body_lines(10)]
        assert all(len(line) == WORKTREE_WIDTH for line in lines)
        assert "×" not in lines[1]
        assert "×" in lines[2]


TESTS = [
    test_hit_test_only_matches_last_two_columns_of_a_real_entry_row,
    test_hit_test_disabled_without_mouse,
    test_delete_cross_only_shown_on_the_hovered_row,
]
