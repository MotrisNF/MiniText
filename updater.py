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


def _show_update_banner():
    from terminal import raw_terminal, read_key

    with raw_terminal():
        sys.stdout.write(
            "A new version of Mini is available.\r\n"
            "Run 'mini --update' to install it.\r\n"
            "\r\n"
            "Press any key to continue...\r\n"
        )
        sys.stdout.flush()
        read_key()


def check_for_updates_on_open():
    """Called on every normal launch. Silent unless an update exists,
    and never blocks startup on network trouble."""
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
    if ahead:
        _show_update_banner()


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
    local_hash = _git(src_dir, "rev-parse", "--short", "HEAD").stdout.strip()
    if not ahead:
        print(f"Already up to date (commit {local_hash}).")
        return
    status = _git(src_dir, "status", "--porcelain")
    if status.stdout.strip():
        print(
            "The install has uncommitted changes, "
            "cancelling the update."
        )
        return
    print("Updating...")
    pull = subprocess.run(
        ["git", "-C", src_dir, "pull", "--ff-only"], env=_GIT_ENV
    )
    if pull.returncode != 0:
        print("git pull failed. Update cancelled.")
        return
    env_values = _read_env(install_dir)
    libdir = env_values.get("LIBDIR", install_dir)
    bindir = env_values.get("BINDIR")
    if not bindir:
        print(
            "Could not find the install's configuration "
            f"({os.path.join(install_dir, 'env')}); reinstall with "
            "'make install'."
        )
        return
    install_result = subprocess.run(
        ["bash", os.path.join(src_dir, "install.sh"), libdir, bindir]
    )
    if install_result.returncode != 0:
        print("The install failed.")
        return
    new_hash = _git(src_dir, "rev-parse", "--short", "HEAD").stdout.strip()
    print(f"Mini updated to version {new_hash}.")


def run_uninstall_command():
    """Handles `mini --uninstall`."""
    if not _is_installed_copy():
        print(
            "'mini --uninstall' only works on an install made with "
            "'make install'."
        )
        return
    src_dir, install_dir = _paths()
    env_values = _read_env(install_dir)
    libdir = env_values.get("LIBDIR", install_dir)
    bindir = env_values.get("BINDIR")
    if not bindir:
        print(
            "Could not find the install's configuration "
            f"({os.path.join(install_dir, 'env')}); can't "
            "uninstall automatically."
        )
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
