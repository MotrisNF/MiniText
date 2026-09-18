"""Covers bugs_conocidos.md: 'Cualquier cambio de estado real en el
programa debe de hacer refresh, permitiendo que el programa recargue
el worktree' - specifically :w on a brand-new, unnamed buffer, and
:refresh itself."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
from commands import CommandMixin  # noqa: E402
from worktree import WorktreePanelMixin, WorktreeState  # noqa: E402


class FakeEditor(CommandMixin, WorktreePanelMixin):
    def __init__(self, lines, worktree_root):
        self.lines = list(lines)
        self.file_name = None
        self.modified = False
        self._worktree_entries_cache = "stale"
        self.worktree = WorktreeState(worktree_root)
        self.worktree.show_hidden = True

    def _render(self):
        pass

    def _read_command_line(self):
        return self._next_name


def test_saving_a_brand_new_file_invalidates_worktree_cache():
    with tempfile.TemporaryDirectory() as tmp:
        editor = FakeEditor(["hello"], worktree_root=tmp)
        editor._next_name = os.path.join(tmp, "new_file.txt")
        assert editor._save() is True
        assert editor._worktree_entries_cache is None
        assert os.path.exists(editor._next_name)


def test_saving_an_already_existing_file_leaves_cache_alone():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "existing.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("old")
        editor = FakeEditor(["new content"], worktree_root=tmp)
        editor.file_name = path  # already named - no prompt needed
        assert editor._save() is True
        assert editor._worktree_entries_cache == "stale"


TESTS = [
    test_saving_a_brand_new_file_invalidates_worktree_cache,
    test_saving_an_already_existing_file_leaves_cache_alone,
]
