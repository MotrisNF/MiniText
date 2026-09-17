"""Virtualenv detection for :run/:lint/:cmd: prefers an
already-activated VIRTUAL_ENV, otherwise looks for a .venv/venv/env/
.env directory from a starting point up to the worktree root."""

import os


_VENV_DIR_NAMES = (".venv", "venv", "env", ".env")


def _venv_python_path(venv_directory):
    """The interpreter inside `venv_directory`, if it looks like a real
    virtualenv (has a bin/python3 or bin/python) - else None."""
    for name in ("python3", "python"):
        candidate = os.path.join(venv_directory, "bin", name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _active_venv_python():
    """The interpreter of an already-activated virtualenv - VIRTUAL_ENV
    is set by `source .../bin/activate`, so this is what the user
    explicitly chose in the shell Mini was launched from, and it takes
    priority over anything Mini finds on its own."""
    virtual_env = os.environ.get("VIRTUAL_ENV")
    return _venv_python_path(virtual_env) if virtual_env else None


def _find_project_venv_python(start_directory, root_directory):
    """Walks from `start_directory` up to (and including)
    `root_directory`, looking for one of _VENV_DIR_NAMES with a real
    interpreter inside - stopping at the project root instead of
    climbing arbitrarily far up the filesystem."""
    current = os.path.abspath(start_directory)
    root = os.path.abspath(root_directory)
    while True:
        for name in _VENV_DIR_NAMES:
            python_path = _venv_python_path(os.path.join(current, name))
            if python_path:
                return python_path
        if current == root:
            return None
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
