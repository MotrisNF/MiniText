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


TESTS = [
    test_autosave_writes_when_mouse_and_autosave_are_both_on,
    test_autosave_does_nothing_without_a_file_name,
    test_autosave_off_by_default_setting_leaves_disk_untouched,
    test_autosave_does_nothing_without_mouse_enabled,
]
