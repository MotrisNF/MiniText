"""Covers bugs_conocidos.md: 'En modo mouse enable, hay que gestionar
modo drag and drop en los archivos del worktree ...'."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
from mouse import MouseState  # noqa: E402
from worktree import WorktreePanelMixin, WorktreeState  # noqa: E402


class FakePanel(WorktreePanelMixin):
    def __init__(self, root):
        self.worktree = WorktreeState(root)
        self.worktree.show_hidden = True
        self._worktree_entries_cache = None
        self._mouse_state = MouseState()
        self.status = ""
        self.file_name = None
        self.confirm_calls = []
        self.confirm_items = []

    def _confirm(self, prompt, items=None):
        self.confirm_calls.append(prompt)
        self.confirm_items.append(items)
        return True

    def _row_for(self, name):
        # entries[0] is the root itself - the direct index into
        # `entries` already IS the correct panel_row (see
        # _worktree_row_index), no +1 header offset any more.
        entries = self._worktree_entries()
        return next(i for i, e in enumerate(entries) if e[1] == name)


def test_drop_on_directory_moves_inside_it():
    with tempfile.TemporaryDirectory() as tmp:
        os.mkdir(os.path.join(tmp, "sub"))
        a_path = os.path.join(tmp, "a.txt")
        open(a_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._mouse_state.drag_origin = a_path
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
        fake.worktree.expanded = {os.path.join(tmp, "sub")}
        fake._mouse_state.drag_origin = c_path
        fake._handle_worktree_drop(fake._row_for("b.txt"))
        assert os.path.exists(os.path.join(tmp, "c.txt"))
        assert not os.path.exists(c_path)


def test_dropping_an_entry_on_itself_is_a_silent_no_op():
    with tempfile.TemporaryDirectory() as tmp:
        b_path = os.path.join(tmp, "b.txt")
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._mouse_state.drag_origin = b_path
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
        fake.worktree.selected_entries = {a_path, b_path}
        fake._mouse_state.drag_origin = a_path  # dragged from within the set
        fake._handle_worktree_drop(fake._row_for("sub"))
        assert os.path.exists(os.path.join(tmp, "sub", "a.txt"))
        assert os.path.exists(os.path.join(tmp, "sub", "b.txt"))
        assert fake.worktree.selected_entries == set()


def test_dropping_a_multiselection_sends_names_as_a_list():
    """Covers bugs_conocidos.md: a comma-joined names string in the
    prompt itself used to truncate once it got long - `_confirm` now
    gets the names as their own `items` list instead, with just the
    count in the prompt text."""
    with tempfile.TemporaryDirectory() as tmp:
        os.mkdir(os.path.join(tmp, "sub"))
        a_path = os.path.join(tmp, "a.txt")
        b_path = os.path.join(tmp, "b.txt")
        open(a_path, "w", encoding="utf-8").close()
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree.selected_entries = {a_path, b_path}
        fake._mouse_state.drag_origin = a_path
        fake._handle_worktree_drop(fake._row_for("sub"))
        assert fake.confirm_calls == ["Move 2 items to 'sub'? (y/n)"]
        assert fake.confirm_items == [["a.txt", "b.txt"]]


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
        fake._mouse_state.drag_origin = a_path
        fake._update_worktree_drag_status(fake._row_for("sub"))
        assert "a.txt" in fake.status
        assert "sub" in fake.status
        assert fake._mouse_state.drag_target == os.path.join(tmp, "sub")
        fake._update_worktree_drag_status(fake._row_for("a.txt"))
        # hovering the origin itself
        assert fake._mouse_state.drag_target is None


TESTS = [
    test_drop_on_directory_moves_inside_it,
    test_drop_on_a_file_moves_to_its_parent_directory,
    test_dropping_an_entry_on_itself_is_a_silent_no_op,
    test_dropping_a_multiselection_moves_every_selected_entry,
    test_dropping_a_multiselection_sends_names_as_a_list,
    test_dragging_over_a_target_sets_status_and_drag_target,
]
