"""Regression: `_save()` used to commit `self._read_command_line()`'s
return value straight into `self.file_name` before checking whether the
user had actually entered anything. Cancelling (or just hitting Enter)
on the "Name of the file:" prompt permanently left `self.file_name` set
to "" - not None - so every later save skipped the "ask for a name"
branch entirely and crashed trying to `open("", "w")`."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
from commands import CommandMixin  # noqa: E402


class FakeEditor(CommandMixin):
    def __init__(self, file_name, next_name=""):
        self.file_name = file_name
        self.lines = ["x"]
        self.modified = True
        self.status = ""
        self._next_name = next_name

    def _render(self):
        pass

    def _read_command_line(self):
        return self._next_name

    def _invalidate_worktree_cache(self):
        pass


def test_cancelling_the_name_prompt_leaves_file_name_none():
    fake = FakeEditor(None, next_name="")
    assert fake._save() is False
    assert fake.status == "Not saved"
    assert fake.file_name is None


def test_saving_again_after_a_cancelled_prompt_still_asks_for_a_name():
    """The actual crash: a second `_save()` call must still see
    `file_name is None` and prompt again, instead of trying to
    `open("", "w")`."""
    fake = FakeEditor(None, next_name="")
    fake._save()
    with tempfile.TemporaryDirectory() as tmp:
        fake._next_name = os.path.join(tmp, "f.txt")
        assert fake._save() is True
        assert os.path.exists(fake._next_name)


def test_providing_a_name_saves_the_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "f.txt")
        fake = FakeEditor(None, next_name=path)
        assert fake._save() is True
        assert os.path.exists(path)
        assert fake.file_name == path
        assert fake.modified is False


TESTS = [
    test_cancelling_the_name_prompt_leaves_file_name_none,
    test_saving_again_after_a_cancelled_prompt_still_asks_for_a_name,
    test_providing_a_name_saves_the_file,
]
