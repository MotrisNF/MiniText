"""Raw-terminal handling: entering/leaving the alternate screen in
raw mode, reading keys (including multi-byte escape sequences for
arrows and friends), and the resize/child-output wakeup plumbing the
main loop's `select()` waits on."""

import os
import select
import signal
import sys
import termios
import tty
from contextlib import contextmanager

import theme


ESC = "\x1b"


def _handle_resize(_signum, _frame):
    pass


def _get_terminal_size():
    try:
        return os.get_terminal_size(sys.stdout.fileno())
    except OSError:
        return os.terminal_size((80, 24))


_resize_wakeup_fd = None
_run_output_fd = None
_update_check_fd = None


def _enable_resize_wakeup():
    global _resize_wakeup_fd
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    signal.set_wakeup_fd(write_fd)
    _resize_wakeup_fd = read_fd
    return read_fd, write_fd


def _disable_resize_wakeup(read_fd, write_fd):
    global _resize_wakeup_fd
    signal.set_wakeup_fd(-1)
    _resize_wakeup_fd = None
    os.close(read_fd)
    os.close(write_fd)


@contextmanager
def raw_terminal():
    file_descriptor = sys.stdin.fileno()
    previous_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        sys.stdout.write(f"\x1b[?1049h{theme.BASE_STYLE}\x1b[2J\x1b[H")
        sys.stdout.flush()
        yield
    finally:
        termios.tcsetattr(
            file_descriptor, termios.TCSADRAIN, previous_settings
        )
        sys.stdout.write("\x1b[?25h\x1b[0m\x1b[?1049l")
        sys.stdout.flush()


_pending_byte = None


def _read_stdin_byte(stdin_fd):
    global _pending_byte
    if _pending_byte is not None:
        byte = _pending_byte
        _pending_byte = None
        return byte
    return os.read(stdin_fd, 1)


def _pushback_byte(byte):
    global _pending_byte
    _pending_byte = byte


def read_key():
    stdin_fd = sys.stdin.fileno()
    watch_fds = [stdin_fd]
    if _pending_byte is None and _resize_wakeup_fd is not None:
        watch_fds.append(_resize_wakeup_fd)
    if _pending_byte is None and _run_output_fd is not None:
        watch_fds.append(_run_output_fd)
    if _pending_byte is None and _update_check_fd is not None:
        watch_fds.append(_update_check_fd)
    if _pending_byte is None:
        try:
            ready, _, _ = select.select(watch_fds, [], [])
        except InterruptedError:
            return "RESIZE"
        if _resize_wakeup_fd is not None and _resize_wakeup_fd in ready:
            try:
                os.read(_resize_wakeup_fd, 4096)
            except OSError:
                pass
            return "RESIZE"
        if _run_output_fd is not None and _run_output_fd in ready:
            return "RUN_OUTPUT"
        if _update_check_fd is not None and _update_check_fd in ready:
            try:
                os.read(_update_check_fd, 4096)
            except OSError:
                pass
            return "UPDATE_AVAILABLE"

    first_byte = _read_stdin_byte(stdin_fd)
    if not first_byte:
        return "EOF"

    key = first_byte.decode("utf-8", errors="ignore")
    if key != ESC:
        return key

    try:
        ready, _, _ = select.select([stdin_fd], [], [], 0.05)
    except InterruptedError:
        return "RESIZE"
    if not ready:
        return ESC
    next_byte = _read_stdin_byte(stdin_fd)
    if next_byte != b"[":
        if next_byte:
            _pushback_byte(next_byte)
        return ESC

    final, params = _read_csi_final(stdin_fd)
    if final is None:
        return ESC
    modifier_parts = params.split(";")
    ctrl = len(modifier_parts) >= 2 and modifier_parts[1] in (
        "5", "6", "7", "8"
    )
    if final == "A":
        return "CTRL-UP" if ctrl else "UP"
    if final == "B":
        return "CTRL-DOWN" if ctrl else "DOWN"
    if final == "C":
        return "CTRL-RIGHT" if ctrl else "RIGHT"
    if final == "D":
        return "CTRL-LEFT" if ctrl else "LEFT"
    if final == "~" and modifier_parts[0] == "3":
        return "DELETE"
    if final == "Z":
        return "SHIFT-TAB"
    return ESC


def _read_csi_final(stdin_fd):
    params = ""
    while True:
        try:
            ready, _, _ = select.select([stdin_fd], [], [], 0.05)
        except InterruptedError:
            return None, params
        if not ready:
            return None, params
        raw_byte = os.read(stdin_fd, 1)
        if not raw_byte:
            return None, params
        char = raw_byte.decode("utf-8", errors="ignore")
        if char in "0123456789;":
            params += char
        else:
            return char, params


def set_run_output_fd(fd):
    """Called by run_panel.py so read_key()'s select() loop also wakes
    up when the running :run/:lint/:cmd process has output ready,
    without terminal.py needing to import run_panel.py back."""
    global _run_output_fd
    _run_output_fd = fd


def set_update_check_fd(fd):
    """Called by main.py/text_editor.py so read_key()'s select() loop
    also wakes up when the background update-check thread (see
    updater.py) has found a new version, without terminal.py needing
    to import updater.py back."""
    global _update_check_fd
    _update_check_fd = fd
