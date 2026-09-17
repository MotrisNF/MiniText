"""Covers bugs_conocidos.md: renaming files/directories in the
worktree panel - keyboard `r`, or the row's own hover "✎" in mouse
mode - and the path rewriting a directory rename needs everywhere a
path under it might be cached (open tabs, expanded set, multi-
selection, the "new entries go here" directory)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import theme  # noqa: E402
from worktree import WorktreePanelMixin, WORKTREE_WIDTH  # noqa: E402


class FakePanel(WorktreePanelMixin):
    def __init__(self, root):
        self.worktree_root = root
        self.worktree_root_collapsed = False
        self.worktree_show_hidden = True
        self.worktree_expanded = set()
        self.worktree_cursor = 0
        self.worktree_scroll = 0
        self.worktree_selected_entries = set()
        self.worktree_new_entry_dir = root
        self._worktree_entries_cache = None
        self.file_name = None
        self.tabs = [{"file_name": None}]
        self.active_tab = 0
        self.status = ""
        self._hovered_worktree_row = None
        self._next_name = None

    def _prompt_name_dialog(self, label, initial_value=""):
        self.last_dialog_initial_value = initial_value
        return self._next_name if self._next_name is not None else ""

    def _row_for(self, name):
        # entries[0] is the root itself - the direct index into
        # `entries` already IS the correct panel_row (see
        # _worktree_row_index), no +1 header offset any more.
        entries = self._worktree_entries()
        return next(i for i, e in enumerate(entries) if e[1] == name)


def test_renaming_a_file_updates_it_on_disk():
    with tempfile.TemporaryDirectory() as tmp:
        old_path = os.path.join(tmp, "a.txt")
        open(old_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._next_name = "b.txt"
        entries = fake._worktree_entries()
        fake.worktree_cursor = 1  # entries[0] is the root itself
        fake._worktree_rename(entries)
        assert not os.path.exists(old_path)
        assert os.path.exists(os.path.join(tmp, "b.txt"))
        assert fake.last_dialog_initial_value == "a.txt"


def test_renaming_the_open_file_updates_file_name():
    with tempfile.TemporaryDirectory() as tmp:
        old_path = os.path.join(tmp, "a.txt")
        open(old_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.file_name = old_path
        fake.tabs = [{"file_name": old_path}]
        fake._next_name = "b.txt"
        fake.worktree_cursor = 1
        fake._worktree_rename(fake._worktree_entries())
        assert fake.file_name == os.path.join(tmp, "b.txt")


def test_renaming_a_directory_rewrites_nested_paths():
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = os.path.join(tmp, "sub")
        os.mkdir(old_dir)
        nested_file = os.path.join(old_dir, "child.txt")
        open(nested_file, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree_expanded = {old_dir}
        fake.worktree_selected_entries = {nested_file}
        fake.worktree_new_entry_dir = old_dir
        # A background (non-active) tab, so its own rewrite path
        # (through fake.tabs[i]["file_name"], not fake.file_name) gets
        # exercised too - the active tab's is covered by
        # test_renaming_the_open_file_updates_file_name already.
        fake.tabs = [
            {"file_name": None}, {"file_name": nested_file},
        ]
        fake.active_tab = 0
        fake._next_name = "renamed"
        fake.worktree_cursor = 1  # entries[0] is the root; 1 is "sub"
        fake._worktree_rename(fake._worktree_entries())
        new_dir = os.path.join(tmp, "renamed")
        new_nested = os.path.join(new_dir, "child.txt")
        assert fake.worktree_expanded == {new_dir}
        assert fake.worktree_selected_entries == {new_nested}
        assert fake.worktree_new_entry_dir == new_dir
        assert fake.tabs[1]["file_name"] == new_nested
        assert os.path.isfile(new_nested)


def test_renaming_to_the_same_name_is_a_no_op():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "a.txt")
        open(path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._next_name = "a.txt"
        fake.worktree_cursor = 1
        fake._worktree_rename(fake._worktree_entries())
        assert fake.status == "Cancelled"
        assert os.path.exists(path)


def test_cancelling_the_dialog_is_a_no_op():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "a.txt")
        open(path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._next_name = ""
        fake.worktree_cursor = 1
        fake._worktree_rename(fake._worktree_entries())
        assert fake.status == "Cancelled"
        assert os.path.exists(path)


def test_rename_hit_test_and_delete_hit_test_zones_do_not_overlap():
    theme.MOUSE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        rename_hit = [
            fake._worktree_rename_hit_test(1, col)
            for col in range(WORKTREE_WIDTH)
        ]
        delete_hit = [
            fake._worktree_delete_hit_test(1, col)
            for col in range(WORKTREE_WIDTH)
        ]
        assert rename_hit.count(1) == 2  # entries[0] is the root; 1 is a.txt
        assert delete_hit.count(1) == 2
        overlap = [
            col for col in range(WORKTREE_WIDTH)
            if rename_hit[col] is not None and delete_hit[col] is not None
        ]
        assert overlap == []


def test_rename_by_index_targets_the_hovered_row_not_the_cursor():
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        open(os.path.join(tmp, "b.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree_cursor = 0  # a.txt
        fake._next_name = "renamed_b.txt"
        fake._worktree_rename_by_index(fake._row_for("b.txt"))
        assert os.path.exists(os.path.join(tmp, "a.txt"))
        assert os.path.exists(os.path.join(tmp, "renamed_b.txt"))


TESTS = [
    test_renaming_a_file_updates_it_on_disk,
    test_renaming_the_open_file_updates_file_name,
    test_renaming_a_directory_rewrites_nested_paths,
    test_renaming_to_the_same_name_is_a_no_op,
    test_cancelling_the_dialog_is_a_no_op,
    test_rename_hit_test_and_delete_hit_test_zones_do_not_overlap,
    test_rename_by_index_targets_the_hovered_row_not_the_cursor,
]
