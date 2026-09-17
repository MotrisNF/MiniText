"""Self-update support for an installed Mini.

Only does anything when this file is running from an installed copy -
that is, from `$LIBDIR/src/main.py` where `$LIBDIR/src` is a git clone
(created by install.sh). Running `python3 main.py` straight from a dev
checkout is not "installed" and every function here becomes a no-op
(or, for `mini --update`, prints a clear explanation instead of
guessing at paths).

Layout on disk, once installed::

    $LIBDIR/
        src/            <- git clone, origin points at the real remote
        env             <- LIBDIR=... / BINDIR=... used to reinstall
        last_check      <- unix timestamp the remote was last checked

Mini never checks the remote more than once every CHECK_INTERVAL_SECONDS
(4 hours): once at most per launch (`check_for_updates_on_open`), and -
for however long a single session stays open past that - a background
thread (`start_background_update_watcher`) keeps checking on the same
schedule, so a long-running Mini still notices an update without
needing to be restarted. Neither ever calls GitHub's REST API or comes
close to any rate limit that matters - both just run plain git
(ls-remote/fetch), the same operation any git client makes on its own
schedule, at a small fraction of the frequency a typical CI job or
package manager already polls at.
"""

import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

_GIT_ENV = dict(
    os.environ,
    GIT_TERMINAL_PROMPT="0",
    GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=3",
)
CHECK_INTERVAL_SECONDS = 4 * 60 * 60


def _paths():
    src_dir = os.path.dirname(os.path.abspath(__file__))
    install_dir = os.path.dirname(src_dir)
    return src_dir, install_dir


def _is_installed_copy():
    """True only for the copy install.sh created at `$LIBDIR/src`, not
    for a dev checkout run directly with `python3 main.py` - both are
    git repos with main.py at their root, so `.git` alone can't tell
    them apart. The `env` file next to `src/` is written only by
    install.sh, so its presence is the real signal."""
    src_dir, install_dir = _paths()
    return os.path.isfile(
        os.path.join(install_dir, "env")
    ) and os.path.isdir(os.path.join(src_dir, ".git"))


def _git(src_dir, *args, timeout=6):
    return subprocess.run(
        ["git", "-C", src_dir, *args],
        capture_output=True, text=True, timeout=timeout, env=_GIT_ENV,
    )


def _remote_is_ahead(src_dir):
    """True/False, or None if the remote couldn't be reached.

    A plain hash comparison against `ls-remote` can't tell "the remote
    has new commits" apart from "we're diverged/ahead" - both just
    look "different". So a difference there only means "worth a
    closer look": a real (but still quick) `git fetch` plus an
    ancestry check confirms we're strictly behind, not just different,
    before ever reporting an update."""
    local = _git(src_dir, "rev-parse", "HEAD")
    if local.returncode != 0:
        return None
    remote = _git(src_dir, "ls-remote", "origin", "HEAD")
    if remote.returncode != 0 or not remote.stdout.strip():
        return None
    local_hash = local.stdout.strip()
    remote_hash = remote.stdout.split()[0]
    if remote_hash == local_hash:
        return False
    branch = _git(src_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if branch.returncode != 0:
        return None
    fetch = _git(
        src_dir, "fetch", "--quiet", "origin", branch.stdout.strip(),
        timeout=15,
    )
    if fetch.returncode != 0:
        return None
    ancestor = _git(
        src_dir, "merge-base", "--is-ancestor", "HEAD",
        f"origin/{branch.stdout.strip()}",
    )
    return ancestor.returncode == 0


def _seconds_since_last_check(install_dir):
    """Seconds since the remote was last checked, or None if it never
    has been (or the timestamp is unreadable - including an older
    Mini's "YYYY-MM-DD" format, which just fails the float() parse) -
    both treated the same way by callers: check now."""
    try:
        path = os.path.join(install_dir, "last_check")
        with open(path, encoding="utf-8") as f:
            return time.time() - float(f.read().strip())
    except (OSError, ValueError):
        return None


def _write_last_check(install_dir):
    try:
        with open(
            os.path.join(install_dir, "last_check"), "w", encoding="utf-8"
        ) as f:
            f.write(str(time.time()))
    except OSError:
        pass


def _read_version(src_dir):
    """The installed copy's own VERSION file, read from `src_dir`
    directly rather than importing main.py for it - called both
    before and after a pull, so it always reflects whichever commit
    is actually checked out at the time it's called."""
    try:
        with open(
            os.path.join(src_dir, "VERSION"), encoding="utf-8"
        ) as f:
            return f.read().strip()
    except OSError:
        return "unknown"


_SPINNER_FRAMES = "|/-\\"


@contextmanager
def _spinner(label):
    """Shows `label` followed by a classic spinning-bar animation
    (cycling |, /, -, \\) on the current line for as long as the
    `with` block runs, in place of dumping git/install.sh's own raw
    output onto the screen for what's normally a silent, successful
    wait - a failure still gets real diagnostic output printed
    afterward (see `_apply_update`), this only replaces the *live*
    stream while things are working."""
    stop = threading.Event()

    def animate():
        frame = 0
        while not stop.is_set():
            sys.stdout.write(f"\r{label} {_SPINNER_FRAMES[frame % 4]}")
            sys.stdout.flush()
            frame += 1
            stop.wait(0.1)
        sys.stdout.write("\r" + " " * (len(label) + 2) + "\r")
        sys.stdout.flush()

    thread = threading.Thread(target=animate, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def _print_subprocess_output(result):
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print(result.stderr.rstrip())


def _read_env(install_dir):
    values = {}
    try:
        with open(
            os.path.join(install_dir, "env"), encoding="utf-8"
        ) as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key:
                    values[key] = value
    except OSError:
        pass
    return values


def _prompt_update_now():
    """A single blocking y/n keypress, asked before the editor itself
    ever opens (so there's no unsaved buffer at risk yet - this is
    the one moment updating in place is entirely safe). Anything but
    'y'/'Y' answers no, including Enter or Esc - never trap the user
    in a loop over an unrecognized key."""
    from terminal import raw_terminal, read_key

    with raw_terminal():
        sys.stdout.write(
            "A new version of Mini is available. Update now? (y/n): "
        )
        sys.stdout.flush()
        key = read_key()
        sys.stdout.write("\r\n")
        sys.stdout.flush()
    return key in ("y", "Y")


def _wait_key(message):
    from terminal import raw_terminal, read_key

    with raw_terminal():
        sys.stdout.write(message.replace("\n", "\r\n") + "\r\n")
        sys.stdout.flush()
        read_key()


def _recover_non_fast_forward(src_dir):
    """Resyncs `src_dir` to the remote branch tip when `git pull
    --ff-only` fails because local HEAD is no longer an ancestor of
    the remote - a remote history rewrite (force-push after a
    mistaken commit, say), rather than a genuine conflict. Before this
    existed, that state was permanent: every future `git pull
    --ff-only` (here and in install.sh) would keep failing the exact
    same way forever, and the only way out was uninstalling and
    reinstalling by hand. `_apply_update` already confirmed the
    working tree has no uncommitted changes before this ever runs, so
    a `reset --hard` to the remote tip can't lose anything real - at
    worst it replays commits this exact checkout made on top of
    history the remote has already abandoned, which a fresh `git
    clone` (what install.sh would do if this directory didn't already
    exist at all) would discard just the same."""
    branch = _git(src_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if branch.returncode != 0:
        return branch
    branch_name = branch.stdout.strip()
    fetch = _git(src_dir, "fetch", "origin", branch_name, timeout=15)
    if fetch.returncode != 0:
        return fetch
    return _git(src_dir, "reset", "--hard", f"origin/{branch_name}")


def _require_bindir(install_dir, failure_detail):
    """LIBDIR/BINDIR from `install_dir`'s own env file (see
    `_read_env`) - `_apply_update`/`run_uninstall_command`'s shared
    guard, since both need a working install to do anything at all.
    Prints why and returns (None, None) if BINDIR is missing (a
    broken/tampered env file) - `failure_detail` is the specific
    remedy each caller's own message ends with."""
    env_values = _read_env(install_dir)
    libdir = env_values.get("LIBDIR", install_dir)
    bindir = env_values.get("BINDIR")
    if not bindir:
        print(
            "Could not find the install's configuration "
            f"({os.path.join(install_dir, 'env')}); {failure_detail}"
        )
        return None, None
    return libdir, bindir


def _apply_update(src_dir, install_dir):
    """Pulls and reinstalls in place - the shared core of `mini
    --update` and the startup update prompt below. Prints why, and
    returns False, on any failure (uncommitted changes, a failed
    pull, a failed reinstall, or a broken `env` file); True on
    success. Reinstalling always goes through install.sh, so this
    also carries forward whatever it does on every install - notably
    keeping Mini's own jedi-completion virtualenv up to date. Both
    subprocesses run behind one continuous "Updating... <spinner>" -
    their own output is only actually printed if one of them fails,
    so a normal, successful update stays quiet instead of scrolling
    git/pip/install.sh's own chatter past."""
    status = _git(src_dir, "status", "--porcelain")
    if status.stdout.strip():
        print("The install has uncommitted changes, cancelling the update.")
        return False
    libdir, bindir = _require_bindir(
        install_dir, "reinstall with 'make install'."
    )
    if bindir is None:
        return False
    try:
        with _spinner("Updating..."):
            pull = _git(src_dir, "pull", "--ff-only", timeout=30)
            if pull.returncode != 0:
                pull = _recover_non_fast_forward(src_dir)
            install_result = None
            if pull.returncode == 0:
                install_result = subprocess.run(
                    ["bash", os.path.join(src_dir, "install.sh"), libdir,
                     bindir],
                    capture_output=True, text=True, timeout=300,
                )
    except (subprocess.TimeoutExpired, OSError) as error:
        print(f"Update timed out or failed to run: {error}")
        return False
    if pull.returncode != 0:
        print("git pull failed. Update cancelled.")
        _print_subprocess_output(pull)
        return False
    if install_result.returncode != 0:
        print("Reinstall failed.")
        _print_subprocess_output(install_result)
        return False
    return True


def _relaunch(install_dir):
    """Re-executes the freshly (re)installed `mini` launcher in this
    same process, with the same arguments Mini itself was started
    with - so an update applied at startup takes effect immediately,
    instead of only on the next separate launch. This matters beyond
    just picking up new source: install.sh may have just created (or
    fixed) Mini's own virtualenv, changing which interpreter `mini`
    itself now runs on - re-execing the launcher script (not just
    re-importing modules in place) is what actually picks that up.
    Never returns on success; falls through (letting the caller carry
    on with the old code) if the launcher can't be found."""
    env_values = _read_env(install_dir)
    bindir = env_values.get("BINDIR")
    mini_path = os.path.join(bindir, "mini") if bindir else None
    if not mini_path or not os.path.isfile(mini_path):
        return
    sys.stdout.flush()
    os.execv(mini_path, [mini_path] + sys.argv[1:])


def check_for_updates_on_open():
    """Called on every normal launch. Silent unless an update exists,
    and never blocks startup on network trouble. An available update
    is offered right there (y/n) - accepting pulls, reinstalls, and
    relaunches into the new version before the editor ever opens;
    declining (or a failed update) falls through to opening the
    editor normally, on whatever version is already installed."""
    if not _is_installed_copy():
        return
    src_dir, install_dir = _paths()
    elapsed = _seconds_since_last_check(install_dir)
    if elapsed is not None and elapsed < CHECK_INTERVAL_SECONDS:
        return
    try:
        ahead = _remote_is_ahead(src_dir)
    except (subprocess.TimeoutExpired, OSError):
        return
    if ahead is None:
        return
    _write_last_check(install_dir)
    if not ahead or not _prompt_update_now():
        return
    if _apply_update(src_dir, install_dir):
        _relaunch(install_dir)
        # Only reached if _relaunch itself couldn't find the launcher.
        _wait_key("Updated, but couldn't restart Mini automatically.")
    else:
        _wait_key("Update failed - continuing on the current version.")


def start_background_update_watcher():
    """For a session that stays open past CHECK_INTERVAL_SECONDS: a
    daemon thread that keeps checking on the same schedule
    check_for_updates_on_open uses (so opening/closing Mini
    repeatedly never resets the clock - only however long a check is
    actually overdue by is ever waited out), for as long as the
    process lives. Returns a read fd to watch with select() - written
    to exactly when an update is found - or None for a non-installed
    copy, where this is a no-op."""
    if not _is_installed_copy():
        return None
    src_dir, install_dir = _paths()
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)

    def watch():
        while True:
            elapsed = _seconds_since_last_check(install_dir)
            wait = (
                0 if elapsed is None
                else max(0, CHECK_INTERVAL_SECONDS - elapsed)
            )
            time.sleep(wait)
            try:
                ahead = _remote_is_ahead(src_dir)
            except (subprocess.TimeoutExpired, OSError):
                ahead = None
            if ahead is not None:
                _write_last_check(install_dir)
                if ahead:
                    try:
                        os.write(write_fd, b"1")
                    except OSError:
                        return
            time.sleep(CHECK_INTERVAL_SECONDS)

    threading.Thread(target=watch, daemon=True).start()
    return read_fd


def run_update_command():
    """Handles `mini --update`."""
    if not _is_installed_copy():
        print(
            "'mini --update' only works on an install made with "
            "'make install'."
        )
        return
    src_dir, install_dir = _paths()
    print("Checking for updates...")
    try:
        ahead = _remote_is_ahead(src_dir)
    except (subprocess.TimeoutExpired, OSError) as error:
        print(f"Could not check for updates: {error}")
        return
    _write_last_check(install_dir)
    if ahead is None:
        print("Could not reach the remote repository.")
        return
    if not ahead:
        print(f"Already up to date (version {_read_version(src_dir)}).")
        return
    if not _apply_update(src_dir, install_dir):
        return
    print(f"Mini updated to version {_read_version(src_dir)}.")


def run_uninstall_command():
    """Handles `mini --uninstall`."""
    if not _is_installed_copy():
        print(
            "'mini --uninstall' only works on an install made with "
            "'make install'."
        )
        return
    src_dir, install_dir = _paths()
    libdir, bindir = _require_bindir(
        install_dir, "can't uninstall automatically."
    )
    if bindir is None:
        return
    try:
        answer = input(
            f"This will remove {libdir}, {bindir}/mini, ~/.minirc and "
            "~/.minirc.bak. Are you sure? (y/n): "
        )
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return
    if answer.strip().lower() not in ("y", "yes"):
        print("Cancelled.")
        return
    result = subprocess.run(
        ["bash", os.path.join(src_dir, "install.sh"),
         "--uninstall", libdir, bindir]
    )
    if result.returncode != 0:
        print("Uninstall failed.")
