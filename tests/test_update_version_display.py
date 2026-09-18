"""The user-facing "an update is available" moments - the startup y/n
prompt, `mini --update`, and the in-session notice tab a long-running
session's own background watcher opens - used to just say an update
existed with no indication of which version was already installed or
which one it would become. All three now show both."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import updater  # noqa: E402
from tabs import TabsMixin  # noqa: E402


def _fake_git_show(version_text):
    def fake_git(src_dir, *args, timeout=6):
        if args[:1] == ("rev-parse",):
            return subprocess.CompletedProcess(args, 0, stdout="main\n")
        if args[:1] == ("show",):
            return subprocess.CompletedProcess(
                args, 0, stdout=f"{version_text}\n",
            )
        raise AssertionError(f"unexpected git call: {args}")
    return fake_git


def test_remote_version_reads_version_off_the_fetched_branch_tip():
    original = updater._git
    updater._git = _fake_git_show("1.12.0")
    try:
        assert updater._remote_version("/tmp/src") == "1.12.0"
    finally:
        updater._git = original


def test_remote_version_is_unknown_when_the_branch_name_cant_be_read():
    original = updater._git

    def fake_git(src_dir, *args, timeout=6):
        return subprocess.CompletedProcess(args, 1, stdout="")

    updater._git = fake_git
    try:
        assert updater._remote_version("/tmp/src") == "unknown"
    finally:
        updater._git = original


def test_remote_version_is_unknown_when_show_fails():
    original = updater._git

    def fake_git(src_dir, *args, timeout=6):
        if args[:1] == ("rev-parse",):
            return subprocess.CompletedProcess(args, 0, stdout="main\n")
        return subprocess.CompletedProcess(args, 1, stdout="")

    updater._git = fake_git
    try:
        assert updater._remote_version("/tmp/src") == "unknown"
    finally:
        updater._git = original


def test_get_available_update_reflects_whatever_the_watcher_last_found():
    original = updater._last_known_update
    updater._last_known_update = ("1.11.5", "1.12.0")
    try:
        assert updater.get_available_update() == ("1.11.5", "1.12.0")
    finally:
        updater._last_known_update = original


def test_get_available_update_is_none_before_anything_is_found():
    original = updater._last_known_update
    updater._last_known_update = None
    try:
        assert updater.get_available_update() is None
    finally:
        updater._last_known_update = original


class FakeEditor(TabsMixin):
    def __init__(self):
        self.file_name = "f.py"
        self.lines = ["x"]
        self.line = 0
        self.column = 0
        self.selection_anchor = None
        self.viewport_top = 0
        self.undo_stack = []
        self.redo_stack = []
        self.modified = False
        self._comment_state = []
        self._comment_state_language = None
        self.tabs = [self._current_buffer_state()]
        self.active_tab = 0
        self.status = ""


def test_notice_tab_shows_both_versions_when_known():
    original = updater._last_known_update
    updater._last_known_update = ("1.11.5", "1.12.0")
    try:
        fake = FakeEditor()
        fake._open_update_notice_tab()
        text = "\n".join(fake.lines)
        assert "1.11.5" in text
        assert "1.12.0" in text
    finally:
        updater._last_known_update = original


def test_notice_tab_falls_back_gracefully_when_versions_are_unknown():
    original = updater._last_known_update
    updater._last_known_update = None
    try:
        fake = FakeEditor()
        fake._open_update_notice_tab()
        assert "A new version of Mini is available." in fake.lines
        assert not any("->" in line for line in fake.lines)
    finally:
        updater._last_known_update = original


TESTS = [
    test_remote_version_reads_version_off_the_fetched_branch_tip,
    test_remote_version_is_unknown_when_the_branch_name_cant_be_read,
    test_remote_version_is_unknown_when_show_fails,
    test_get_available_update_reflects_whatever_the_watcher_last_found,
    test_get_available_update_is_none_before_anything_is_found,
    test_notice_tab_shows_both_versions_when_known,
    test_notice_tab_falls_back_gracefully_when_versions_are_unknown,
]
