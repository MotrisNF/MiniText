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


# Any-event tracking (1003 - press/release plus *all* motion, held
# button or not - needed for hover highlighting) with SGR extended
# coordinates (1006 - decimal, not limited to 223 columns/rows like
# the older encoding). Only ever sent when MOUSE_ENABLED is on: it
# makes the terminal stop doing its own click-drag text selection
# while Mini has focus, since drags are now handed to Mini instead -
# a real tradeoff, not a free enhancement, which is why it defaults
# to off. 1003 is chattier than plain click tracking (every mouse
# move over the terminal is now a reported event, hover or not), the
# cost of being able to highlight something under the cursor without
# a click.
_MOUSE_ENABLE = "\x1b[?1003h\x1b[?1006h"
_MOUSE_DISABLE = "\x1b[?1006l\x1b[?1003l"


@contextmanager
def raw_terminal():
    file_descriptor = sys.stdin.fileno()
    previous_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        sys.stdout.write(f"\x1b[?1049h{theme.BASE_STYLE}\x1b[2J\x1b[H")
        if theme.MOUSE_ENABLED:
            sys.stdout.write(_MOUSE_ENABLE)
        sys.stdout.flush()
        yield
    finally:
        if theme.MOUSE_ENABLED:
            sys.stdout.write(_MOUSE_DISABLE)
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


def read_key(timeout=None):
    """The next key/event - blocking indefinitely if `timeout` is
    None (the default), or returning "IDLE_TIMEOUT" if `timeout`
    seconds pass with nothing at all happening (no key, no resize, no
    background event) - used to let a transient status message
    expire on its own instead of sitting there until something else
    happens to overwrite it."""
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
            ready, _, _ = select.select(watch_fds, [], [], timeout)
        except InterruptedError:
            return "RESIZE"
        if not ready:
            return "IDLE_TIMEOUT"
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

    try:
        ready, _, _ = select.select([stdin_fd], [], [], 0.05)
    except InterruptedError:
        return "RESIZE"
    if ready:
        peek_byte = _read_stdin_byte(stdin_fd)
        if peek_byte == b"<":
            return _read_mouse_event(stdin_fd)
        if peek_byte:
            _pushback_byte(peek_byte)

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
        # A byte _read_mouse_event's caller already read and pushed
        # back (checking for the mouse prefix "<") sits in
        # _pending_byte, not in the fd's own buffer - select() alone,
        # like read_key()'s own top-level wait, would never see it.
        if _pending_byte is None:
            try:
                ready, _, _ = select.select([stdin_fd], [], [], 0.05)
            except InterruptedError:
                return None, params
            if not ready:
                return None, params
        raw_byte = _read_stdin_byte(stdin_fd)
        if not raw_byte:
            return None, params
        char = raw_byte.decode("utf-8", errors="ignore")
        if char in "0123456789;":
            params += char
        else:
            return char, params


def _read_mouse_event(stdin_fd):
    """An SGR mouse report (`\\x1b[<{code};{column};{row}M` for press/
    motion, `...m` for release) as one of "MOUSE_PRESS:col:row"
    (":ctrl" appended if Ctrl was held - see worktree.py's multi-
    select), "MOUSE_DRAG:col:row" (motion with the button still down),
    "MOUSE_MOVE:col:row" (motion with *no* button down - hover, only
    reported at all because of the 1003 tracking mode),
    "MOUSE_RELEASE:col:row", "MOUSE_WHEEL_UP:col:row",
    "MOUSE_WHEEL_DOWN:col:row", or "MOUSE_IGNORE" for anything Mini
    has no use for (a right/middle click, an unparseable report, ...)
    - never ESC or any other key name, so an unrecognized mouse event
    can't be mistaken for a real keypress and trigger something
    unrelated. `column`/`row` are 1-indexed terminal coordinates,
    matching every cursor-positioning escape sequence Mini itself
    already writes. Every MOUSE_* event's own column/row parser
    tolerates the optional trailing ":ctrl" even where it doesn't
    care about it, so a click held with Ctrl over an unrelated part
    of the screen (a dialog, a button, ...) never gets silently
    dropped for looking unparseable."""
    final, params = _read_csi_final(stdin_fd)
    if final not in ("M", "m"):
        return "MOUSE_IGNORE"
    parts = params.split(";")
    if len(parts) != 3:
        return "MOUSE_IGNORE"
    try:
        code, column, row = (int(part) for part in parts)
    except ValueError:
        return "MOUSE_IGNORE"
    if code in (64, 65):
        direction = "UP" if code == 64 else "DOWN"
        return f"MOUSE_WHEEL_{direction}:{column}:{row}"
    is_motion = bool(code & 32)
    button = code & 3
    if button == 3:
        # No button held: only a real event at all in 1003 mode, and
        # only meaningful to Mini as hover - a bare "3" with no motion
        # bit is an artifact of some terminals' own release encoding
        # in this mode, not something to act on.
        return f"MOUSE_MOVE:{column}:{row}" if is_motion else "MOUSE_IGNORE"
    if button != 0:
        return "MOUSE_IGNORE"
    if final == "m":
        return f"MOUSE_RELEASE:{column}:{row}"
    if is_motion:
        return f"MOUSE_DRAG:{column}:{row}"
    ctrl_suffix = ":ctrl" if code & 16 else ""
    return f"MOUSE_PRESS:{column}:{row}{ctrl_suffix}"


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
