"""Covers bugs_conocidos.md: 'Anadir funcion de autoguardado que se
activa al hacer click en cualquier parte del proyecto estando en modo
mouse, o al realizar cualquier cambio de modo en el modo mouse enable
sin pedir confirmacion. Configurable desde .minirc'."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import theme  # noqa: E402
from commands import CommandMixin  # noqa: E402
from mouse import MouseState  # noqa: E402
from tabs import TabsMixin  # noqa: E402
from worktree import WorktreePanelMixin, WorktreeState  # noqa: E402


class FakeEditor(CommandMixin):
    def __init__(self, file_name):
        self.file_name = file_name
        self.lines = ["x"]
        self.modified = True


def test_autosave_writes_when_mouse_and_autosave_are_both_on():
    theme.MOUSE_ENABLED = True
    theme.AUTOSAVE = True
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "f.txt")
        fake = FakeEditor(path)
        fake._maybe_autosave()
        assert os.path.exists(path)
        assert fake.modified is False


def test_autosave_does_nothing_without_a_file_name():
    theme.MOUSE_ENABLED = True
    theme.AUTOSAVE = True
    fake = FakeEditor(None)
    fake._maybe_autosave()  # must not prompt/crash
    assert fake.file_name is None


def test_autosave_off_by_default_setting_leaves_disk_untouched():
    theme.MOUSE_ENABLED = True
    theme.AUTOSAVE = False
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.txt")
        fake = FakeEditor(path)
        fake._maybe_autosave()
        assert not os.path.exists(path)
    theme.AUTOSAVE = False


def test_autosave_does_nothing_without_mouse_enabled():
    theme.MOUSE_ENABLED = False
    theme.AUTOSAVE = True
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "h.txt")
        fake = FakeEditor(path)
        fake._maybe_autosave()
        assert not os.path.exists(path)
    theme.MOUSE_ENABLED = True
    theme.AUTOSAVE = False


class FakeWorktreeEditor(CommandMixin, TabsMixin, WorktreePanelMixin):
    def __init__(self, root, file_name, lines):
        self.worktree = WorktreeState(root)
        self._worktree_entries_cache = None
        self._mouse_state = MouseState()
        self.file_name = file_name
        self.lines = lines
        self.line = 0
        self.column = 0
        self.selection_anchor = None
        self.viewport_top = 0
        self.undo_stack = []
        self.redo_stack = []
        self.modified = True
        self._comment_state = []
        self._comment_state_language = None
        self.tabs = [self._current_buffer_state()]
        self.active_tab = 0
        self.status = ""

    def _resolve_python_executable(self):
        return None


def test_clicking_a_worktree_entry_autosaves_the_file_being_left():
    """Regression: opening a different file from the worktree panel -
    a mouse click on it, activating it - used to skip AUTOSAVE
    entirely (only a click landing in the code area or on a tab went
    through `_reset_focus_for_click`, which is what actually calls
    `_maybe_autosave`), so the file just left could stay unsaved on
    disk even with AUTOSAVE on."""
    theme.MOUSE_ENABLED = True
    theme.AUTOSAVE = True
    with tempfile.TemporaryDirectory() as tmp:
        old_path = os.path.join(tmp, "old.py")
        open(old_path, "w", encoding="utf-8").close()
        new_path = os.path.join(tmp, "new.py")
        open(new_path, "w", encoding="utf-8").close()
        fake = FakeWorktreeEditor(tmp, old_path, ["unsaved change"])
        entries = fake._worktree_entries()
        fake.worktree.cursor = next(
            i for i, e in enumerate(entries) if e[1] == "new.py"
        )
        fake._worktree_activate(entries)
        with open(old_path, encoding="utf-8") as file:
            assert file.read() == "unsaved change"
    theme.AUTOSAVE = False


TESTS = [
    test_autosave_writes_when_mouse_and_autosave_are_both_on,
    test_autosave_does_nothing_without_a_file_name,
    test_autosave_off_by_default_setting_leaves_disk_untouched,
    test_autosave_does_nothing_without_mouse_enabled,
    test_clicking_a_worktree_entry_autosaves_the_file_being_left,
]
