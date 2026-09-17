"""Regression: _apply_update's own git pull/install.sh subprocess
calls used to run with no timeout at all (unlike every other git call
in this module), and nothing in _apply_update caught a
TimeoutExpired/OSError either - a stalled network or a hung install.sh
would block forever with no way out, and any timeout that did fire
from a helper it calls (_recover_non_fast_forward) would crash
_apply_update outright instead of failing cleanly."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import updater  # noqa: E402


def test_a_timed_out_pull_fails_cleanly_instead_of_crashing():
    original_git = updater._git
    original_read_env = updater._read_env

    def fake_git(src_dir, *args, timeout=6):
        if args and args[0] == "status":
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(cmd="git", timeout=timeout)

    updater._git = fake_git
    updater._read_env = lambda install_dir: {
        "LIBDIR": "/tmp", "BINDIR": "/tmp/bin",
    }
    try:
        result = updater._apply_update("/tmp/src", "/tmp/install")
    finally:
        updater._git = original_git
        updater._read_env = original_read_env
    assert result is False


def test_pull_and_install_calls_carry_an_explicit_timeout():
    """Not a behavior test - a guard against silently dropping the
    timeout again in a future edit. Inspects the actual call the real
    _apply_update makes to subprocess.run for install.sh."""
    original_run = subprocess.run
    original_git = updater._git
    original_read_env = updater._read_env
    calls = []

    def fake_git(src_dir, *args, timeout=6):
        calls.append(("git", args, timeout))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def fake_run(cmd, **kwargs):
        calls.append(("run", cmd, kwargs.get("timeout")))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    updater._git = fake_git
    updater._read_env = lambda install_dir: {
        "LIBDIR": "/tmp", "BINDIR": "/tmp/bin",
    }
    subprocess.run = fake_run
    try:
        assert updater._apply_update("/tmp/src", "/tmp/install") is True
    finally:
        updater._git = original_git
        updater._read_env = original_read_env
        subprocess.run = original_run
    pull_calls = [c for c in calls if c[0] == "git" and "pull" in c[1]]
    install_calls = [c for c in calls if c[0] == "run"]
    assert pull_calls and pull_calls[0][2] is not None
    assert install_calls and install_calls[0][2] is not None


TESTS = [
    test_a_timed_out_pull_fails_cleanly_instead_of_crashing,
    test_pull_and_install_calls_carry_an_explicit_timeout,
]
