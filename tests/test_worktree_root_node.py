"""The worktree root is now entries[0] itself - a real, collapsible
directory row like any other, except it can't be deleted or renamed,
and collapsing it hides the whole tree at once while resetting "new
entries go here" back to the top level."""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import theme  # noqa: E402
from mouse import MouseState  # noqa: E402
from worktree import WorktreePanelMixin, WorktreeState  # noqa: E402


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


class FakePanel(WorktreePanelMixin):
    def __init__(self, root):
        self.worktree = WorktreeState(root)
        self.worktree.show_hidden = True
        self._worktree_entries_cache = None
        self.file_name = None
        self.status = ""
        self.confirm_calls = []
        self._mouse_state = MouseState()

    def _confirm(self, prompt, items=None):
        self.confirm_calls.append(prompt)
        return True

    def _maybe_autosave(self):
        pass


def test_root_is_the_first_entry():
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        entries = fake._worktree_entries()
        assert entries[0] == (tmp, os.path.basename(tmp), True, 0)
        assert entries[1][1] == "a.txt"
        assert entries[1][3] == 1  # one level deeper than the root


def test_collapsing_the_root_hides_the_whole_tree():
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree.cursor = 0  # the root
        entries = fake._worktree_entries()
        fake._worktree_collapse(entries)
        assert fake.worktree.root_collapsed is True
        collapsed_entries = fake._worktree_entries()
        assert len(collapsed_entries) == 1
        assert collapsed_entries[0][0] == tmp


def test_expanding_the_root_again_restores_the_tree():
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree.root_collapsed = True
        fake.worktree.cursor = 0
        fake._worktree_expand(fake._worktree_entries())
        assert fake.worktree.root_collapsed is False
        entries = fake._worktree_entries()
        assert len(entries) == 2


def test_collapsing_the_root_resets_new_entry_dir_to_the_top():
    with tempfile.TemporaryDirectory() as tmp:
        sub = os.path.join(tmp, "sub")
        os.mkdir(sub)
        fake = FakePanel(tmp)
        fake.worktree.expanded = {sub}
        fake.worktree.new_entry_dir = sub  # navigated deep into "sub"
        fake.worktree.cursor = 0  # move back to the root row
        fake._worktree_collapse(fake._worktree_entries())
        assert fake.worktree.new_entry_dir == tmp


def test_activating_the_root_toggles_collapse():
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree.cursor = 0
        fake._worktree_activate(fake._worktree_entries())
        assert fake.worktree.root_collapsed is True
        fake._worktree_activate(fake._worktree_entries())
        assert fake.worktree.root_collapsed is False


def test_root_cannot_be_deleted():
    with tempfile.TemporaryDirectory() as tmp:
        fake = FakePanel(tmp)
        fake.worktree.cursor = 0
        fake._worktree_delete(fake._worktree_entries())
        assert fake.confirm_calls == []
        assert os.path.isdir(tmp)
        assert "root" in fake.status.lower()


def test_root_cannot_be_renamed():
    with tempfile.TemporaryDirectory() as tmp:
        fake = FakePanel(tmp)
        fake._prompt_name_dialog = lambda label, initial_value="": "renamed"
        fake.worktree.cursor = 0
        fake._worktree_rename(fake._worktree_entries())
        assert os.path.isdir(tmp)
        assert not os.path.isdir(os.path.join(os.path.dirname(tmp), "renamed"))
        assert "root" in fake.status.lower()


def test_root_cannot_join_the_multiselection():
    with tempfile.TemporaryDirectory() as tmp:
        fake = FakePanel(tmp)
        fake.worktree.focused = True
        fake.worktree.visible = True
        fake.worktree.visible_because_of_focus = False
        fake._handle_worktree_click(0, ctrl_held=True)
        assert fake.worktree.selected_entries == set()


def test_root_marker_reflects_collapsed_state():
    theme.MOUSE_ENABLED = False
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        expanded_lines = fake._worktree_body_lines(10)
        assert _strip_ansi(expanded_lines[0]).startswith("v ")
        fake.worktree.root_collapsed = True
        fake._invalidate_worktree_cache()
        collapsed_lines = fake._worktree_body_lines(10)
        assert _strip_ansi(collapsed_lines[0]).startswith("> ")


TESTS = [
    test_root_is_the_first_entry,
    test_collapsing_the_root_hides_the_whole_tree,
    test_expanding_the_root_again_restores_the_tree,
    test_collapsing_the_root_resets_new_entry_dir_to_the_top,
    test_activating_the_root_toggles_collapse,
    test_root_cannot_be_deleted,
    test_root_cannot_be_renamed,
    test_root_cannot_join_the_multiselection,
    test_root_marker_reflects_collapsed_state,
]
