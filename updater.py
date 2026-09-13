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
        last_check      <- last date (YYYY-MM-DD) the remote was checked
"""

import datetime
import os
import subprocess
import sys

_GIT_ENV = dict(
    os.environ,
    GIT_TERMINAL_PROMPT="0",
    GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=3",
)


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


def _today():
    return datetime.date.today().isoformat()


def _read_last_check(install_dir):
    try:
        path = os.path.join(install_dir, "last_check")
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _write_last_check(install_dir):
    try:
        with open(
            os.path.join(install_dir, "last_check"), "w", encoding="utf-8"
        ) as f:
            f.write(_today())
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
    from text_editor import raw_terminal, read_key

    with raw_terminal():
        sys.stdout.write(
            "Hay una nueva version de Mini disponible.\r\n"
            "Ejecuta 'mini --update' para instalarla.\r\n"
            "\r\n"
            "Pulsa cualquier tecla para continuar...\r\n"
        )
        sys.stdout.flush()
        read_key()


def check_for_updates_on_open():
    """Called on every normal launch. Silent unless an update exists,
    and never blocks startup on network trouble."""
    if not _is_installed_copy():
        return
    src_dir, install_dir = _paths()
    if _read_last_check(install_dir) == _today():
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


def run_update_command():
    """Handles `mini --update`."""
    if not _is_installed_copy():
        print(
            "'mini --update' solo funciona en una instalacion hecha "
            "con 'make install'."
        )
        return
    src_dir, install_dir = _paths()
    print("Comprobando actualizaciones...")
    try:
        ahead = _remote_is_ahead(src_dir)
    except (subprocess.TimeoutExpired, OSError) as error:
        print(f"No se pudo comprobar si hay actualizaciones: {error}")
        return
    _write_last_check(install_dir)
    if ahead is None:
        print("No se pudo contactar con el repositorio remoto.")
        return
    local_hash = _git(src_dir, "rev-parse", "--short", "HEAD").stdout.strip()
    if not ahead:
        print(f"Ya tienes la ultima version instalada (commit {local_hash}).")
        return
    status = _git(src_dir, "status", "--porcelain")
    if status.stdout.strip():
        print(
            "La instalacion tiene cambios sin confirmar, "
            "se cancela la actualizacion."
        )
        return
    print("Actualizando...")
    pull = subprocess.run(
        ["git", "-C", src_dir, "pull", "--ff-only"], env=_GIT_ENV
    )
    if pull.returncode != 0:
        print("git pull fallo. Actualizacion cancelada.")
        return
    env_values = _read_env(install_dir)
    libdir = env_values.get("LIBDIR", install_dir)
    bindir = env_values.get("BINDIR")
    if not bindir:
        print(
            "No se encontro la configuracion de la instalacion "
            f"({os.path.join(install_dir, 'env')}); reinstala con "
            "'make install'."
        )
        return
    install_result = subprocess.run(
        ["bash", os.path.join(src_dir, "install.sh"), libdir, bindir]
    )
    if install_result.returncode != 0:
        print("La instalacion fallo.")
        return
    new_hash = _git(src_dir, "rev-parse", "--short", "HEAD").stdout.strip()
    print(f"Mini actualizado a la version {new_hash}.")


def run_uninstall_command():
    """Handles `mini --uninstall`."""
    if not _is_installed_copy():
        print(
            "'mini --uninstall' solo funciona en una instalacion hecha "
            "con 'make install'."
        )
        return
    src_dir, install_dir = _paths()
    env_values = _read_env(install_dir)
    libdir = env_values.get("LIBDIR", install_dir)
    bindir = env_values.get("BINDIR")
    if not bindir:
        print(
            "No se encontro la configuracion de la instalacion "
            f"({os.path.join(install_dir, 'env')}); no se puede "
            "desinstalar automaticamente."
        )
        return
    try:
        answer = input(
            f"Esto eliminara {libdir}, {bindir}/mini, ~/.minirc y "
            "~/.minirc.bak. Seguro? (y/n): "
        )
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        return
    if answer.strip().lower() not in ("y", "yes", "s", "si", "sí"):
        print("Cancelado.")
        return
    result = subprocess.run(
        ["bash", os.path.join(src_dir, "install.sh"),
         "--uninstall", libdir, bindir]
    )
    if result.returncode != 0:
        print("La desinstalacion fallo.")
