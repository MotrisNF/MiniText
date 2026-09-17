"""Covers bugs_conocidos.md: 'En modo mouse enable, hay que gestionar
modo drag and drop en los archivos del worktree ...'."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from worktree import WorktreePanelMixin  # noqa: E402


class FakePanel(WorktreePanelMixin):
    def __init__(self, root):
        self.worktree_root = root
        self.worktree_show_hidden = True
        self.worktree_expanded = set()
        self.worktree_cursor = 0
        self.worktree_scroll = 0
        self.worktree_selected_entries = set()
        self._worktree_entries_cache = None
        self._worktree_drag_origin = None
        self.status = ""
        self.file_name = None
        self.confirm_calls = []

    def _confirm(self, prompt):
        self.confirm_calls.append(prompt)
        return True

    def _row_for(self, name):
        entries = self._worktree_entries()
        return 1 + next(i for i, e in enumerate(entries) if e[1] == name)


def test_drop_on_directory_moves_inside_it():
    with tempfile.TemporaryDirectory() as tmp:
        os.mkdir(os.path.join(tmp, "sub"))
        a_path = os.path.join(tmp, "a.txt")
        open(a_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._worktree_drag_origin = a_path
        fake._handle_worktree_drop(fake._row_for("sub"))
        assert fake.confirm_calls == ["Move a.txt to 'sub'? (y/n)"]
        assert os.path.exists(os.path.join(tmp, "sub", "a.txt"))
        assert not os.path.exists(a_path)


def test_drop_on_a_file_moves_to_its_parent_directory():
    with tempfile.TemporaryDirectory() as tmp:
        os.mkdir(os.path.join(tmp, "sub"))
        c_path = os.path.join(tmp, "sub", "c.txt")
        open(c_path, "w", encoding="utf-8").close()
        open(os.path.join(tmp, "b.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree_expanded = {os.path.join(tmp, "sub")}
        fake._worktree_drag_origin = c_path
        fake._handle_worktree_drop(fake._row_for("b.txt"))
        assert os.path.exists(os.path.join(tmp, "c.txt"))
        assert not os.path.exists(c_path)


def test_dropping_an_entry_on_itself_is_a_silent_no_op():
    with tempfile.TemporaryDirectory() as tmp:
        b_path = os.path.join(tmp, "b.txt")
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._worktree_drag_origin = b_path
        fake._handle_worktree_drop(fake._row_for("b.txt"))
        assert fake.confirm_calls == []
        assert os.path.exists(b_path)


def test_dropping_a_multiselection_moves_every_selected_entry():
    with tempfile.TemporaryDirectory() as tmp:
        os.mkdir(os.path.join(tmp, "sub"))
        a_path = os.path.join(tmp, "a.txt")
        b_path = os.path.join(tmp, "b.txt")
        open(a_path, "w", encoding="utf-8").close()
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree_selected_entries = {a_path, b_path}
        fake._worktree_drag_origin = a_path  # dragged from within the set
        fake._handle_worktree_drop(fake._row_for("sub"))
        assert os.path.exists(os.path.join(tmp, "sub", "a.txt"))
        assert os.path.exists(os.path.join(tmp, "sub", "b.txt"))
        assert fake.worktree_selected_entries == set()


def test_dragging_over_a_target_sets_status_and_drag_target():
    """Covers bugs_conocidos.md: 'El desplazar un archivo ... no da
    ningun tipo de feedback' - dragging now names the file being moved
    in the status line and marks the hovered row as the drop zone
    (_worktree_drag_target, used by _worktree_body_lines to highlight
    it)."""
    with tempfile.TemporaryDirectory() as tmp:
        os.mkdir(os.path.join(tmp, "sub"))
        a_path = os.path.join(tmp, "a.txt")
        open(a_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._worktree_drag_origin = a_path
        fake._update_worktree_drag_status(fake._row_for("sub"))
        assert "a.txt" in fake.status
        assert "sub" in fake.status
        assert fake._worktree_drag_target == os.path.join(tmp, "sub")
        fake._update_worktree_drag_status(fake._row_for("a.txt"))
        assert fake._worktree_drag_target is None  # hovering the origin itself


TESTS = [
    test_drop_on_directory_moves_inside_it,
    test_drop_on_a_file_moves_to_its_parent_directory,
    test_dropping_an_entry_on_itself_is_a_silent_no_op,
    test_dropping_a_multiselection_moves_every_selected_entry,
    test_dragging_over_a_target_sets_status_and_drag_target,
]
