"""Autocomplete's "ask a real interpreter" engine for Python: checking
whether an import actually resolves, listing a module's or a class's
real members, and jedi-backed completions when Mini's own bundled copy
is available - all run in an isolated subprocess (or through jedi's
own environment abstraction) using the project's own resolved
interpreter, never Mini's, so a module only installed in the
project's virtualenv isn't wrongly treated as unavailable, and a slow
or broken one can't freeze the editor.

jedi itself runs in-process rather than in a subprocess, and its own
first-time warm-up plus a genuine parse/inference pass over a real
file measured anywhere from ~100ms to over a second - clearly
noticeable run synchronously on Mini's single-threaded key-reading
loop. `_start_background_jedi_completion`/`_prewarm_jedi` below move
that work to a daemon thread instead: a caller waits only a short,
bounded moment for it (still instant when jedi's already warm/fast),
falls back to Mini's own heuristics otherwise, and picks the real
answer up on a later render once the thread finishes - woken up on
its own via `_notify_suggestion_ready` even if the user's gone idle
waiting for it, rather than only ever refreshing on the next keypress."""

import os
import subprocess
import threading

_IMPORT_CHECK_SCRIPT = (
    "import sys, importlib\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "try:\n"
    "    module = importlib.import_module(sys.argv[2])\n"
    "except Exception:\n"
    "    print('BROKEN')\n"
    "else:\n"
    "    missing = [n for n in sys.argv[3:] if not hasattr(module, n)]\n"
    "    print('BROKEN' if missing else 'OK')\n"
)
_MODULE_INTROSPECTION_SCRIPT = (
    "import sys, importlib, os\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "module = importlib.import_module(sys.argv[2])\n"
    "names = {\n"
    "    n for n in dir(module)\n"
    "    if not (n.startswith('__') and n.endswith('__'))\n"
    "}\n"
    # A package (regular or namespace - both have __path__) can be
    # imported from with its submodules/subpackages too, and those
    # aren't in dir() unless something already imported them - so
    # its directory is scanned directly for candidates as well.
    "for path in getattr(module, '__path__', []):\n"
    "    try:\n"
    "        entries = os.scandir(path)\n"
    "    except OSError:\n"
    "        continue\n"
    "    for entry in entries:\n"
    "        if entry.name in ('__init__.py', '__pycache__'):\n"
    "            continue\n"
    "        if entry.is_file() and entry.name.endswith('.py'):\n"
    "            names.add(entry.name[:-3])\n"
    "        elif entry.is_dir() and not entry.name.startswith('.'):\n"
    "            names.add(entry.name)\n"
    "print('\\n'.join(names))\n"
)
_CLASS_INTROSPECTION_SCRIPT = (
    "import sys, importlib\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "module = importlib.import_module(sys.argv[2])\n"
    "obj = getattr(module, sys.argv[3])\n"
    "names = [\n"
    "    n for n in dir(obj)\n"
    "    if not (n.startswith('__') and n.endswith('__'))\n"
    "]\n"
    "print('\\n'.join(names))\n"
)


def _check_import_resolves(directory, module_name, names, python_path):
    """True if this import is broken - the module itself fails to
    import, or (for `from module_name import a, b`) any of `names`
    isn't actually an attribute of it once imported - checked for
    real, by actually trying it in an isolated subprocess using
    `python_path` (normally the project's own resolved virtualenv,
    the same interpreter :run/:lint would use for this file - not
    necessarily Mini's own). False if it resolves; None if it
    couldn't even be checked (a `python_path` that doesn't work)."""
    try:
        result = subprocess.run(
            [python_path, "-c", _IMPORT_CHECK_SCRIPT, directory,
             module_name, *names],
            capture_output=True, text=True, timeout=3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout.strip() == "BROKEN"


def _introspect_module_members(directory, module_name, python_path):
    """Names `from module_name import <TAB>` could offer, found by
    actually importing the module in a throwaway subprocess (with
    `directory` on its sys.path, so local project files resolve too),
    using `python_path` - normally the project's own resolved
    virtualenv, the same interpreter :run/:lint would use for this
    file - not necessarily Mini's own, so a module only installed in
    the project's virtualenv isn't wrongly treated as having no
    members.

    A subprocess - not an in-process import - because this runs
    whatever top-level code the module has, including local files
    still being edited; a timeout and total isolation from Mini itself
    keep a slow or broken module from freezing the editor."""
    try:
        result = subprocess.run(
            [
                python_path, "-c", _MODULE_INTROSPECTION_SCRIPT,
                directory, module_name,
            ],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()
    if result.returncode != 0:
        return set()
    return set(result.stdout.split())


def _introspect_class_members(directory, module_name, class_name, python_path):
    """Like `_introspect_module_members`, but for one class imported
    from a module (`from module_name import ClassName`), so `thing.`
    can offer that class's own methods instead of every builtin type's
    methods mixed together. Same `python_path` reasoning as above."""
    try:
        result = subprocess.run(
            [
                python_path, "-c", _CLASS_INTROSPECTION_SCRIPT,
                directory, module_name, class_name,
            ],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()
    if result.returncode != 0:
        return set()
    return set(result.stdout.split())


_jedi_module = None
_jedi_import_attempted = False
_jedi_environment_cache = {}


def _get_jedi():
    """Mini's own bundled `jedi`, if this install has one (a private
    venv `make install` creates and manages - see install.sh) - else
    None, imported at most once per session. Never a hard dependency:
    every caller below treats None (or any failure past this point)
    as "fall back to Mini's own heuristics", exactly as if jedi had
    never been tried - so a dev checkout run straight with `python3
    main.py`, with no such venv, still works exactly as before."""
    global _jedi_module, _jedi_import_attempted
    if not _jedi_import_attempted:
        _jedi_import_attempted = True
        try:
            import jedi  # type: ignore[import-not-found]
        except ImportError:
            jedi = None
        _jedi_module = jedi
    return _jedi_module


def _jedi_environment(python_path):
    """A cached `jedi.Environment` for `python_path` (the project's
    own resolved interpreter, same as everywhere else here) - or None
    if jedi isn't available or can't be pointed at it, in which case
    callers fall back to Mini's own heuristics."""
    jedi = _get_jedi()
    if jedi is None:
        return None
    if python_path not in _jedi_environment_cache:
        environment = None
        try:
            environment = jedi.create_environment(python_path, safe=False)
        except Exception:
            try:
                environment = jedi.get_default_environment()
            except Exception:
                environment = None
        _jedi_environment_cache[python_path] = environment
    return _jedi_environment_cache[python_path]


def _jedi_completions(source_text, file_name, line, column, python_path):
    """Completion name strings from jedi at (1-indexed `line`,
    0-indexed `column`) in `source_text`, resolving imports with
    `python_path` the same way :run/:lint would - or None if jedi
    isn't installed, or the call fails for any reason (an
    unsupported jedi version, a still-invalid buffer, a slow/broken
    environment probe, ...), so callers can fall back to Mini's own
    heuristics exactly as if jedi had never been tried. Deliberately
    catches every exception, not just expected ones: jedi is a large
    third-party parser/inference engine, and the entire point of
    trying it here is best-effort - it must never be able to break or
    freeze suggestions, only improve them when it works."""
    jedi = _get_jedi()
    if jedi is None:
        return None
    environment = _jedi_environment(python_path)
    try:
        script = jedi.Script(
            code=source_text, path=file_name, environment=environment,
        )
        completions = script.complete(line, column)
        return {
            completion.name for completion in completions
            if not completion.name.startswith("__")
        }
    except Exception:
        return None


_suggestion_wakeup_write_fd = None


def set_suggestion_wakeup_fd(fd):
    """Called by text_editor.py's `run()` so a background jedi job
    (below) can wake the main loop's `read_key()` up on its own once
    it finishes, the same way run_panel.py/updater.py already do for
    their own background work."""
    global _suggestion_wakeup_write_fd
    _suggestion_wakeup_write_fd = fd


def _notify_suggestion_ready():
    if _suggestion_wakeup_write_fd is not None:
        try:
            os.write(_suggestion_wakeup_write_fd, b"x")
        except OSError:
            pass


def _start_background_jedi_completion(
    source_text, file_name, line, column, python_path,
):
    """Runs `_jedi_completions` on a daemon thread instead of blocking
    the caller. Returns (event, box): `event` is set once `box[0]`
    holds the result - a caller waits on it with a short timeout to
    still get the answer immediately when jedi's fast enough, or moves
    on (falling back to Mini's own heuristics) and checks back later
    otherwise, picking the real answer up on whatever render happens
    next - `_notify_suggestion_ready` wakes the main loop up on its
    own for this even if the user's gone idle waiting for it."""
    event = threading.Event()
    box = [None]

    def worker():
        box[0] = _jedi_completions(
            source_text, file_name, line, column, python_path,
        )
        event.set()
        _notify_suggestion_ready()

    threading.Thread(target=worker, daemon=True).start()
    return event, box


_jedi_prewarmed = False


def _prewarm_jedi(python_path):
    """Best-effort background warm-up for jedi's own first-use cost -
    importing it, creating its Environment, and priming whatever
    internal caches make its *first* completion of a session run
    roughly 10x slower than every later one (measured: over a second,
    against ~100ms once warm). Kicked off right when a `.py` file is
    opened, so that one-time hit lands while the user is still reading
    the file instead of the first time they actually try to complete
    something. A daemon thread, same as the real completions above -
    never touches editor state, and any failure is silently ignored,
    exactly as if jedi had never been tried."""
    def worker():
        global _jedi_prewarmed
        environment = _jedi_environment(python_path)
        if environment is None or _jedi_prewarmed:
            return
        _jedi_prewarmed = True
        try:
            jedi = _get_jedi()
            jedi.Script(
                code="import os\nos.", environment=environment,
            ).complete(2, 3)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()
