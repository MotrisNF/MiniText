"""Covers bugs_conocidos.md: 'La multiple seleccion no hace nada en
el worktree ... no permite ... eliminar varios archivos
simultaneamente'."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from worktree import WorktreePanelMixin  # noqa: E402


class FakePanel(WorktreePanelMixin):
    def __init__(self, root):
        self.worktree_root = root
        self.worktree_root_collapsed = False
        self.worktree_show_hidden = True
        self.worktree_expanded = set()
        self.worktree_cursor = 0
        self.worktree_scroll = 0
        self.worktree_selected_entries = set()
        self._worktree_entries_cache = None
        self.file_name = None
        self.confirm_calls = []
        self.confirm_items = []

    def _confirm(self, prompt, items=None):
        self.confirm_calls.append(prompt)
        self.confirm_items.append(items)
        return True


def test_deleting_a_selected_entry_deletes_the_whole_selection():
    with tempfile.TemporaryDirectory() as tmp:
        a_path = os.path.join(tmp, "a.txt")
        b_path = os.path.join(tmp, "b.txt")
        open(a_path, "w", encoding="utf-8").close()
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree_selected_entries = {a_path, b_path}
        entries = fake._worktree_entries()
        fake.worktree_cursor = 1  # entries[0] is the root itself; 1 is a.txt
        fake._worktree_delete(entries)
        assert not os.path.exists(a_path)
        assert not os.path.exists(b_path)
        assert len(fake.confirm_calls) == 1
        assert fake.worktree_selected_entries == set()


def test_deleting_an_unselected_entry_only_deletes_that_one():
    with tempfile.TemporaryDirectory() as tmp:
        a_path = os.path.join(tmp, "a.txt")
        b_path = os.path.join(tmp, "b.txt")
        open(a_path, "w", encoding="utf-8").close()
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree_selected_entries = {b_path}  # a.txt not selected
        entries = fake._worktree_entries()
        fake.worktree_cursor = 1  # entries[0] is the root itself; 1 is a.txt
        fake._worktree_delete(entries)
        assert not os.path.exists(a_path)
        assert os.path.exists(b_path)
        assert fake.worktree_selected_entries == {b_path}


def test_deleting_a_selection_sends_names_as_a_list_not_a_joined_string():
    """Covers bugs_conocidos.md: a comma-joined names string in the
    prompt itself used to truncate once it got long - `_confirm` now
    gets the names as their own `items` list (rendered as a scrollable
    box, see test_confirm_box.py) instead, with just the count in the
    prompt text."""
    with tempfile.TemporaryDirectory() as tmp:
        a_path = os.path.join(tmp, "a.txt")
        b_path = os.path.join(tmp, "b.txt")
        open(a_path, "w", encoding="utf-8").close()
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake.worktree_selected_entries = {a_path, b_path}
        entries = fake._worktree_entries()
        fake.worktree_cursor = 1
        fake._worktree_delete(entries)
        assert fake.confirm_calls == ["Delete 2 items? (y/n)"]
        assert fake.confirm_items == [["a.txt", "b.txt"]]


def test_deleting_a_single_entry_still_uses_the_plain_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        a_path = os.path.join(tmp, "a.txt")
        open(a_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        entries = fake._worktree_entries()
        fake.worktree_cursor = 1
        fake._worktree_delete(entries)
        assert fake.confirm_calls == ["Delete file 'a.txt'? (y/n)"]
        assert fake.confirm_items == [None]


TESTS = [
    test_deleting_a_selected_entry_deletes_the_whole_selection,
    test_deleting_an_unselected_entry_only_deletes_that_one,
    test_deleting_a_selection_sends_names_as_a_list_not_a_joined_string,
    test_deleting_a_single_entry_still_uses_the_plain_prompt,
]
