"""Autocompletion for .py files: word-based suggestions from the
buffer plus Python's own keywords/builtins, module-name completion
after import/from, and type-aware `name.` completion (literals,
locally-defined classes via ast, or classes/modules introspected in
an isolated subprocess)."""

import ast
import bisect
import builtins
import keyword
import os
import re
import shutil
import subprocess
import sys

import theme
from languages import (
    C_KEYWORDS, C_TYPE_NAMES, CPP_KEYWORDS, CPP_LITERALS, CPP_TYPE_NAMES,
    language_for,
)

MIN_SUGGESTION_PREFIX = 2
PYTHON_VOCABULARY = sorted(
    set(keyword.kwlist)
    | {name for name in dir(builtins) if not name.startswith("_")}
)
_ATTRIBUTE_TYPES = (
    str, list, dict, set, tuple, frozenset, bytes, bytearray, int, float,
)
ATTRIBUTE_VOCABULARY = sorted({
    name
    for type_object in _ATTRIBUTE_TYPES
    for name in dir(type_object)
    if not name.startswith("_")
})
TYPE_ATTRIBUTE_VOCABULARY = {
    type_object.__name__: sorted(
        name for name in dir(type_object) if not name.startswith("_")
    )
    for type_object in _ATTRIBUTE_TYPES
}
# Checked in order against the text of a `name = <here>` assignment to
# guess `name`'s type; first match wins, so more specific patterns
# (dict-with-colon before a bare `{`, which is otherwise a set) come
# first. Only single-line, literal-or-constructor assignments are
# recognized - no control flow or cross-function tracking.
_TYPE_INFERENCE_RULES = (
    (re.compile(r"^\{\}"), "dict"),
    (re.compile(r"^dict\("), "dict"),
    (re.compile(r"^\{[^{}]*:"), "dict"),
    (re.compile(r"^\{"), "set"),
    (re.compile(r"^set\("), "set"),
    (re.compile(r"^frozenset\("), "frozenset"),
    (re.compile(r"^\["), "list"),
    (re.compile(r"^list\("), "list"),
    (re.compile(r"^\(.*,\)$"), "tuple"),
    (re.compile(r"^\(\)$"), "tuple"),
    (re.compile(r"^tuple\("), "tuple"),
    (re.compile(r"^b[\"']"), "bytes"),
    (re.compile(r"^bytes\("), "bytes"),
    (re.compile(r"^bytearray\("), "bytearray"),
    (re.compile(r"^f?r?[\"']"), "str"),
    (re.compile(r"^str\("), "str"),
    (re.compile(r"^-?\d+\.\d*$"), "float"),
    (re.compile(r"^float\("), "float"),
    (re.compile(r"^-?\d+$"), "int"),
    (re.compile(r"^int\("), "int"),
)
_CALL_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(")
_CLASS_DEF_PATTERN = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)")
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
MODULE_VOCABULARY = sorted(
    name for name in sys.stdlib_module_names if not name.startswith("_")
)
IMPORT_CONTEXT_PATTERN = re.compile(r"^\s*(?:from|import)\s+$")
FROM_IMPORT_NAMES_PATTERN = re.compile(
    r"^\s*from\s+(\S+)\s+import\s+"
    r"(?:[A-Za-z_][A-Za-z0-9_]*(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*,\s*)*$"
)
FROM_IMPORT_LINE_PATTERN = re.compile(r"^\s*from\s+(\S+)\s+import\s+(.+)$")
_BARE_IMPORT_LINE_PATTERN = re.compile(r"^\s*import\s+(.+)$")
MAX_SUGGESTION_DROPDOWN_ITEMS = 8
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


def _is_word_char(character):
    return character.isalnum() or character == "_"


_WORD_PATTERN = re.compile(r"\w+")
_LINE_WORD_CACHE_LIMIT = 20000


def _is_inside_string_or_comment(line, column):
    """Whether `column` sits inside a string literal or a comment,
    scanning from the start of `line` - so an unterminated string
    being typed still counts, even though it has no closing quote
    yet for a regex to match against."""
    quote = None
    index = 0
    while index < column and index < len(line):
        character = line[index]
        if quote:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
        elif character == "#":
            return True
        elif character in ("'", '"'):
            quote = character
        index += 1
    return quote is not None


def _is_inside_c_string_or_comment(line, column):
    """Like `_is_inside_string_or_comment`, for C/C++'s comment
    styles instead of Python's `#`: `//` runs to the end of the line;
    a same-line `/* ... */` is skipped over entirely (scanning
    resumes right after it); one that doesn't close by `column` on
    this line counts as "inside" - same single-line-only limitation
    as a block comment actually spanning multiple lines, which this
    can't see across."""
    quote = None
    index = 0
    while index < column and index < len(line):
        character = line[index]
        if quote:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character == "/" and line[index:index + 2] == "//":
            return True
        if character == "/" and line[index:index + 2] == "/*":
            end = line.find("*/", index + 2)
            if end == -1 or end + 2 > column:
                return True
            index = end + 2
            continue
        if character in ("'", '"'):
            quote = character
        index += 1
    return quote is not None


_INCLUDE_PATTERN = re.compile(r'^\s*#\s*include\s+([<"])')
_INCLUDE_LINE_PATTERN = re.compile(r'^\s*#\s*include\s+([<"])([^>"]+)[>"]')

_compiler_include_dirs_cache = {}


def _compiler_include_dirs(cpp):
    """The real system include search path of whatever C/C++
    compiler is actually installed, found by asking it directly (the
    same `-Wp,-v` trick `gcc`/`clang` themselves document) instead of
    guessing a fixed path - the same "introspect the real thing"
    philosophy as Python's module completion, one layer down (the
    compiler instead of the interpreter). This never changes
    mid-session, so the actual subprocess call only ever happens
    once per c/c++ distinction."""
    if cpp not in _compiler_include_dirs_cache:
        compiler = (
            shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
        )
        directories = []
        if compiler:
            try:
                lang = "c++" if cpp else "c"
                result = subprocess.run(
                    [compiler, "-E", "-Wp,-v", "-x", lang, "-"],
                    input="", capture_output=True, text=True, timeout=3,
                )
            except (subprocess.TimeoutExpired, OSError):
                result = None
            if result is not None:
                capturing = False
                for line in result.stderr.split("\n"):
                    if "search starts here" in line:
                        capturing = True
                    elif line.startswith("End of search list"):
                        break
                    elif capturing:
                        directories.append(line.strip())
        _compiler_include_dirs_cache[cpp] = [
            d for d in directories if os.path.isdir(d)
        ]
    return _compiler_include_dirs_cache[cpp]


def _resolve_system_header_path(header_name, cpp):
    """The real file path `#include <header_name>` would pull in, or
    None if it can't be found in the compiler's own include
    directories (no compiler on PATH, or a header name that isn't
    actually one of its real headers)."""
    for directory in _compiler_include_dirs(cpp):
        candidate = os.path.join(directory, header_name)
        if os.path.isfile(candidate):
            return candidate
    return None


_header_word_cache = {}


def _header_words(path):
    """Identifier-like words found anywhere in the header at `path` -
    the same word-based idea as everything else in C/C++ completion
    here, just reaching into a file named by #include instead of
    only the buffer being edited. A header's content never changes
    mid-session (from Mini's own perspective - nothing here ever
    writes to it), so each one is only ever read and scanned once."""
    if path not in _header_word_cache:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as file:
                text = file.read()
        except OSError:
            _header_word_cache[path] = frozenset()
        else:
            _header_word_cache[path] = frozenset(_WORD_PATTERN.findall(text))
    return _header_word_cache[path]


_system_header_cache = {}


def _system_header_names(cpp):
    """Every header name offered by `#include <...>` - walking each
    of the compiler's own include directories and collecting file
    names relative to it (so `sys/types.h` and similar
    subdirectory-qualified names come out right), including
    extensionless files since C++'s own standard headers
    (`<vector>`, `<string>`, ...) have no extension at all. The
    compiler's own include paths never change mid-session, so this
    only actually walks them once."""
    if cpp not in _system_header_cache:
        names = set()
        for directory in _compiler_include_dirs(cpp):
            for root, _dirs, files in os.walk(directory):
                for file_name in files:
                    if "." in file_name and not file_name.endswith(
                        (".h", ".hpp", ".hh", ".hxx")
                    ):
                        continue
                    full_path = os.path.join(root, file_name)
                    names.add(os.path.relpath(full_path, directory))
        _system_header_cache[cpp] = names
    return _system_header_cache[cpp]


def _parse_imported_names(context_before):
    """Names already typed before the cursor in a `from X import a, b, `
    line, so they aren't offered again."""
    import_part = context_before.split("import", 1)[1]
    names = set()
    for chunk in import_part.split(","):
        name = chunk.strip().split(" as ")[0].strip()
        if name:
            names.add(name)
    return names


def _parse_import_check_names(names_part):
    """The concrete names in a *complete* `from X import a, b as c` -
    a `*` doesn't name anything checkable, so it's skipped rather
    than ever counting as "missing"."""
    names_part = names_part.split("#", 1)[0]
    names = []
    for chunk in names_part.split(","):
        name = chunk.strip().split(" as ")[0].strip()
        if name and name != "*":
            names.append(name)
    return names


def _parse_bare_import_modules(rest):
    """The module name(s) in a *complete* `import a, b as c, d.e` -
    one line can name more than one, each optionally aliased."""
    rest = rest.split("#", 1)[0]
    modules = []
    for chunk in rest.split(","):
        module = chunk.strip().split(" as ")[0].strip()
        if module:
            modules.append(module)
    return modules


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


def _local_class_methods(source_text, class_name):
    """Method names of a `class ClassName:` defined in this same
    buffer, found by parsing the buffer's source with `ast` - never
    executed, so a class still being written can't run broken or
    unfinished code. Returns None (not just an empty set) when the
    buffer doesn't parse or has no such class, so callers can tell
    "not found here" apart from "found, but no methods"."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not (
                    item.name.startswith("__")
                    and item.name.endswith("__")
                )
            }
    return None


def _enclosing_class_members(source_text, line_index):
    """For `self.<TAB>`: the innermost `class ...:` whose body contains
    line `line_index` (0-indexed), read the same way as
    `_local_class_methods` - plus every `self.attr = ...` found
    anywhere in that class, since those instance attributes are just
    as much a part of `self.`'s real API as its methods are."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None
    target_line = line_index + 1
    enclosing = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        # +1 tolerance: blanking the current line for the parse can
        # shrink a class's reported end_lineno by exactly that one
        # line whenever it was the class's last line - the common
        # case of typing "self." right after the previous statement.
        if start <= target_line <= end + 1:
            if enclosing is None or start > enclosing.lineno:
                enclosing = node
    if enclosing is None:
        return None
    names = set()
    for item in ast.walk(enclosing):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not (item.name.startswith("__") and item.name.endswith("__")):
                names.add(item.name)
        elif (
            isinstance(item, ast.Attribute)
            and isinstance(item.ctx, ast.Store)
            and isinstance(item.value, ast.Name)
            and item.value.id == "self"
        ):
            names.add(item.attr)
    return names


class SuggestionMixin:

    def _current_word_prefix(self):
        line = self.lines[self.line]
        start = self.column
        while start > 0 and _is_word_char(line[start - 1]):
            start -= 1
        return line[start:self.column]

    def _line_words(self, line):
        """The identifier-like words in one line's text, cached by the
        line's own content rather than its position - so it stays
        correct no matter how lines are inserted, deleted, or
        reordered, since the key IS the content."""
        cache = self._line_word_cache
        words = cache.get(line)
        if words is None:
            words = frozenset(_WORD_PATTERN.findall(line))
            if len(cache) < _LINE_WORD_CACHE_LIMIT:
                cache[line] = words
        return words

    def _rebuild_static_word_pool(self):
        words = set()
        language = language_for(self.file_name)
        collect_includes = language in ("c", "cpp")
        include_words = set()
        directory = (
            os.path.dirname(self.file_name) if self.file_name else ""
        ) or os.getcwd()
        for index, line in enumerate(self.lines):
            if index != self.line:
                words |= self._line_words(line)
            if collect_includes:
                match = _INCLUDE_LINE_PATTERN.match(line)
                if match:
                    opening, header_name = match.group(1), match.group(2)
                    if opening == '"':
                        path = os.path.join(directory, header_name)
                        if os.path.isfile(path):
                            include_words |= _header_words(path)
                    else:
                        path = _resolve_system_header_path(
                            header_name, language == "cpp"
                        )
                        if path:
                            include_words |= _header_words(path)
        self._word_pool_static = words
        # Sorted once here, not on every keystroke: lets
        # _buffer_words_matching find a prefix's matches by binary
        # search instead of scanning every unique word in the file.
        self._word_pool_static_sorted = sorted(words)
        self._included_header_words_sorted = sorted(include_words)
        self._word_pool_lines_ref = self.lines
        self._word_pool_line_count = len(self.lines)
        self._word_pool_line_index = self.line

    def _ensure_word_pool_fresh(self):
        if (
            self.lines is not self._word_pool_lines_ref
            or len(self.lines) != self._word_pool_line_count
            or self.line != self._word_pool_line_index
        ):
            self._rebuild_static_word_pool()

    def _included_header_words_matching(self, prefix):
        """Words found in every header this buffer's own #include
        directives name (both local "..." ones and real system <...>
        ones, resolved the same way #include completion itself
        finds them), starting with `prefix` - refreshed on the same
        schedule as the buffer's own word pool, via the same binary
        search over a cached sorted list."""
        self._ensure_word_pool_fresh()
        sorted_words = self._included_header_words_sorted
        low = bisect.bisect_left(sorted_words, prefix)
        high = bisect.bisect_left(sorted_words, prefix + "\uffff")
        return set(sorted_words[low:high])

    def _collect_buffer_words(self):
        """Every identifier-like word used anywhere in the buffer, for
        autocompletion. Every *other* line's contribution is cached as
        one "static" union, rebuilt only when the buffer's identity
        (a different tab/undo snapshot/file), its line count, or which
        line the cursor is on changes - so typing fast on one line,
        the common case this exists for, no longer re-scans the whole
        file on every keystroke: only the cursor's own line (cheap -
        it's the one thing actually changing) is re-scanned fresh.

        Only used for the (rare) import-context pool, which needs the
        *whole* set - see _buffer_words_matching for the hot path."""
        self._ensure_word_pool_fresh()
        current_line = (
            self.lines[self.line] if 0 <= self.line < len(self.lines) else ""
        )
        return self._word_pool_static | self._line_words(current_line)

    def _buffer_words_matching(self, prefix):
        """Buffer words starting with `prefix` - the hot path for
        ordinary typing. Finds them by binary search over the cached,
        sorted static pool instead of scanning (and startswith-testing)
        every unique word in the file on every keystroke, the same way
        _collect_buffer_words itself avoids re-scanning every *line*:
        a file can easily have thousands of unique words, so filtering
        all of them by prefix every keystroke doesn't scale any better
        than not caching the word set in the first place."""
        self._ensure_word_pool_fresh()
        sorted_words = self._word_pool_static_sorted
        low = bisect.bisect_left(sorted_words, prefix)
        high = bisect.bisect_left(sorted_words, prefix + "\uffff")
        matches = set(sorted_words[low:high])
        current_line = (
            self.lines[self.line] if 0 <= self.line < len(self.lines) else ""
        )
        matches |= {
            word for word in self._line_words(current_line)
            if word.startswith(prefix)
        }
        return matches

    def _local_module_names(self):
        directory = (
            os.path.dirname(self.file_name) if self.file_name else ""
        ) or os.getcwd()
        names = set()
        try:
            entries = os.scandir(directory)
        except OSError:
            return names
        for entry in entries:
            if entry.name in ("__init__.py", "__pycache__"):
                continue
            if entry.is_file() and entry.name.endswith(".py"):
                name = entry.name[:-len(".py")]
            elif entry.is_dir() and not entry.name.startswith("."):
                # A directory counts whether or not it has an
                # __init__.py: Python 3.3+ can import a plain
                # directory as a namespace package too.
                name = entry.name
            else:
                continue
            if name.isidentifier():
                names.add(name)
        return names

    def _local_header_names(self):
        """Header files next to the one being edited, for
        `#include "..."` - the C/C++ equivalent of
        `_local_module_names`'s local `.py` files."""
        directory = (
            os.path.dirname(self.file_name) if self.file_name else ""
        ) or os.getcwd()
        names = set()
        try:
            entries = os.scandir(directory)
        except OSError:
            return names
        for entry in entries:
            if entry.is_file() and entry.name.endswith(
                (".h", ".hpp", ".hh", ".hxx")
            ):
                names.add(entry.name)
        return names

    def _include_target_missing(self, opening, header_name, language):
        """Whether a #include names something that doesn't actually
        resolve - a local header not found next to the file, or (only
        when a compiler is actually available to ask) a system header
        not found in its own include directories. With no compiler on
        PATH at all, a <...> include is never flagged - there's no
        way to tell "doesn't exist" apart from "just can't check"
        then, and flagging every one would be worse than flagging
        none, the same reasoning `#include <...>` completion itself
        already follows."""
        if opening == '"':
            directory = (
                os.path.dirname(self.file_name) if self.file_name else ""
            ) or os.getcwd()
            return not os.path.isfile(os.path.join(directory, header_name))
        cpp = language == "cpp"
        if not _compiler_include_dirs(cpp):
            return False
        return _resolve_system_header_path(header_name, cpp) is None

    def _module_import_broken(self, module_name, names, python_path):
        """Whether `import module_name` (or `from module_name import
        *names`) would actually fail - a plain top-level stdlib
        import (nothing to import by name, no dotted submodule) is
        trusted outright, without spawning anything, since it will
        as good as always resolve; everything else is actually
        checked, once per (interpreter, module, names) combination
        for the rest of the session."""
        if (
            not names and "." not in module_name
            and module_name in MODULE_VOCABULARY
        ):
            return False
        directory = (
            os.path.dirname(self.file_name) if self.file_name else ""
        ) or os.getcwd()
        cache_key = (python_path, directory, module_name, tuple(names))
        if cache_key not in self._import_broken_cache:
            self._import_broken_cache[cache_key] = _check_import_resolves(
                directory, module_name, names, python_path
            )
        return bool(self._import_broken_cache[cache_key])

    def _import_line_broken(self, line, python_path):
        """Whether this line's import(s) would actually fail to
        resolve - see _module_import_broken. A bare `import a, b`
        checks every named module; the first broken one is enough to
        flag the whole line."""
        if python_path is None:
            return False
        from_match = FROM_IMPORT_LINE_PATTERN.match(line)
        if from_match:
            module_name, names_part = from_match.groups()
            names = _parse_import_check_names(names_part)
            return self._module_import_broken(module_name, names, python_path)
        bare_match = _BARE_IMPORT_LINE_PATTERN.match(line)
        if bare_match:
            for module_name in _parse_bare_import_modules(
                bare_match.group(1)
            ):
                if self._module_import_broken(module_name, [], python_path):
                    return True
        return False

    def _module_member_names(self, module_name):
        directory = (
            os.path.dirname(self.file_name) if self.file_name else ""
        ) or os.getcwd()
        cache_key = (directory, module_name)
        if cache_key not in self._import_members_cache:
            python_path = self._resolve_python_executable()
            jedi_pool = _jedi_completions(
                "\n".join(self.lines), self.file_name,
                self.line + 1, self.column, python_path,
            )
            self._import_members_cache[cache_key] = jedi_pool or (
                _introspect_module_members(
                    directory, module_name, python_path
                )
            )
        return self._import_members_cache[cache_key]

    def _preceding_identifier(self, dot_index):
        """The bare name right before `line[dot_index]` (a '.'), e.g.
        "patata" in "patata.app" - or None when what's there isn't a
        simple name (a call, a literal, another `.attr`, ...), so type
        inference is skipped rather than guessing wrong."""
        line = self.lines[self.line]
        start = dot_index
        while start > 0 and _is_word_char(line[start - 1]):
            start -= 1
        name = line[start:dot_index]
        return name if name.isidentifier() else None

    def _find_assignment_expr(self, name):
        """Text to the right of the nearest `name = <here>` at or
        before the cursor's line, searching upward - or None. Only
        whole-line, single-line assignments count: no control flow,
        no multi-line expressions, no tracking across a reassignment
        happening later in the file than the completion itself."""
        pattern = re.compile(rf"^\s*{re.escape(name)}\s*=\s*(.+?)\s*$")
        start_line = min(self.line, len(self.lines) - 1)
        for index in range(start_line, -1, -1):
            match = pattern.match(self.lines[index])
            if match:
                return match.group(1)
        return None

    def _imported_from_module(self, name):
        """(module, original_name) if `name` reached local scope via
        `from module import original_name [as name]` somewhere in the
        buffer, else None."""
        for line in self.lines:
            match = FROM_IMPORT_LINE_PATTERN.match(line)
            if not match:
                continue
            module_name, names_part = match.groups()
            names_part = names_part.split("#", 1)[0]
            for chunk in names_part.split(","):
                parts = chunk.strip().split(" as ")
                original_name = parts[0].strip()
                local_name = parts[-1].strip()
                if local_name == name:
                    return module_name, original_name
        return None

    def _blanked_source_text(self):
        """The whole buffer, joined into one string, with the line
        being typed replaced by an empty one. Used before any `ast`
        parse triggered by attribute completion: right at the moment
        that fires (e.g. immediately after typing the "." itself),
        the current line is guaranteed to be invalid Python on its
        own, which would otherwise make the whole buffer fail to
        parse every single time."""
        source_lines = list(self.lines)
        source_lines[self.line] = ""
        return "\n".join(source_lines)

    def _jedi_attribute_completions(self, dot_index):
        """Like `_infer_attribute_pool`, but backed by jedi (when this
        install has it - see `_get_jedi`) instead of Mini's own
        regex/`ast` heuristics: since jedi actually parses and
        resolves the whole buffer, this also covers cases the
        heuristics below give up on outright - a chained call
        (`foo().bar`), a subscript (`foo[0].bar`), or a name imported
        from a module that isn't on Mini's own interpreter (the exact
        bug this was added for: an imported class whose package only
        lives in the project's virtualenv). Cached per (buffer
        identity, line, dot position) - not per keystroke past the
        dot - since jedi's own analysis of "what does the thing before
        this dot resolve to" doesn't change as more of the attribute
        name is typed after it; like every other cache here, it's
        never invalidated mid-session, so an edit far above a `name.`
        already completed once won't be picked up until Mini restarts."""
        cache_key = (id(self.lines), self.line, dot_index)
        if cache_key not in self._jedi_attribute_cache:
            python_path = self._resolve_python_executable()
            self._jedi_attribute_cache[cache_key] = _jedi_completions(
                "\n".join(self.lines), self.file_name,
                self.line + 1, self.column, python_path,
            )
        return self._jedi_attribute_cache[cache_key]

    def _infer_attribute_pool(self, name):
        """Names to offer for `name.<TAB>`, narrowed to name's actual
        type/class when it can be worked out from the buffer - or
        None to fall back to the generic mixed-type vocabulary. Only
        reached when `_jedi_attribute_completions` couldn't answer
        (no jedi installed, or it genuinely found nothing) - see
        `_compute_python_suggestion_matches`."""
        if name == "self":
            return _enclosing_class_members(
                self._blanked_source_text(), self.line
            )
        expr = self._find_assignment_expr(name)
        if expr is None:
            return None
        for pattern, type_name in _TYPE_INFERENCE_RULES:
            if pattern.match(expr):
                return set(TYPE_ATTRIBUTE_VOCABULARY[type_name])
        call_match = _CALL_PATTERN.match(expr)
        if not call_match:
            return None
        class_name = call_match.group(1)
        local_methods = _local_class_methods(
            self._blanked_source_text(), class_name
        )
        if local_methods is not None:
            return local_methods
        found = self._imported_from_module(class_name)
        if found is None:
            return None
        module_name, original_name = found
        directory = (
            os.path.dirname(self.file_name) if self.file_name else ""
        ) or os.getcwd()
        cache_key = (directory, module_name, original_name)
        if cache_key not in self._import_members_cache:
            self._import_members_cache[cache_key] = (
                _introspect_class_members(
                    directory, module_name, original_name,
                    self._resolve_python_executable(),
                )
            )
        return self._import_members_cache[cache_key]

    def _suggestion_pools(self, prefix_start, line, prefix):
        context_before = line[:prefix_start]
        from_import_match = FROM_IMPORT_NAMES_PATTERN.match(context_before)
        if from_import_match:
            already_imported = _parse_imported_names(context_before)
            members = self._module_member_names(
                from_import_match.group(1)
            ) - already_imported
            return (members,)
        if IMPORT_CONTEXT_PATTERN.match(context_before):
            # Rare/brief context (right after "import "/"from ") - not
            # hot enough to need _buffer_words_matching's shortcut.
            return (
                self._local_module_names(),
                MODULE_VOCABULARY,
                self._collect_buffer_words(),
            )
        return (self._buffer_words_matching(prefix), PYTHON_VOCABULARY)

    def _compute_suggestion_matches(self):
        if self.mode != "insert":
            return []
        language = language_for(self.file_name)
        if language == "python":
            return self._compute_python_suggestion_matches()
        if language in ("c", "cpp"):
            return self._compute_c_suggestion_matches(language)
        return []

    def _compute_python_suggestion_matches(self):
        line = self.lines[self.line]
        if _is_inside_string_or_comment(line, self.column):
            return []
        if self.column < len(line) and _is_word_char(line[self.column]):
            return []
        prefix = self._current_word_prefix()
        prefix_start = self.column - len(prefix)
        is_attribute = (
            prefix_start > 0 and line[prefix_start - 1] == "."
        )
        if is_attribute:
            dot_index = prefix_start - 1
            jedi_inferred = self._jedi_attribute_completions(dot_index)
            if jedi_inferred:
                inferred = jedi_inferred
            elif (
                dot_index > 0
                and line[dot_index - 1] in ("'", '"')
                and _is_inside_string_or_comment(line, dot_index - 1)
            ):
                # The dot follows a complete string literal directly
                # (e.g. "".foo or 'x'.foo), not a named variable -
                # str's own type is already fully known here.
                inferred = set(TYPE_ATTRIBUTE_VOCABULARY["str"])
            else:
                name = self._preceding_identifier(dot_index)
                inferred = self._infer_attribute_pool(name) if name else None
            if inferred is not None:
                # The type/class is known, so "." alone (an empty
                # prefix) already starts the suggestion - no need to
                # type anything first.
                pools = (inferred,)
            elif len(prefix) < MIN_SUGGESTION_PREFIX:
                return []
            else:
                pools = (
                    self._buffer_words_matching(prefix), ATTRIBUTE_VOCABULARY,
                )
        else:
            if len(prefix) < MIN_SUGGESTION_PREFIX:
                return []
            pools = self._suggestion_pools(prefix_start, line, prefix)
        for pool in pools:
            matches = sorted(
                (
                    word for word in pool
                    if word != prefix and word.startswith(prefix)
                ),
                key=len,
            )
            if matches:
                return matches
        return []

    def _compute_c_suggestion_matches(self, language):
        """C/C++'s much simpler counterpart to
        _compute_python_suggestion_matches: word completion from the
        buffer *and* from every header this file's own #include
        directives name, plus C/C++'s own keyword vocabulary as a
        final fallback; `#include <...>`/`#include "..."` themselves
        offer real header names instead - no type inference, no
        `self.`/`->` awareness, no macro expansion."""
        line = self.lines[self.line]
        if _INCLUDE_LINE_PATTERN.match(line):
            # Every branch below that can trigger while sitting on a
            # complete #include line returns before ever reaching the
            # word-pool machinery - so editing one never rebuilds it
            # on its own. Force a rebuild next time it's actually
            # needed (however much later that ends up being, even
            # back on this exact same line index), in case what this
            # line names just changed.
            self._word_pool_line_index = -1
        if self.column < len(line) and _is_word_char(line[self.column]):
            return []
        # Checked before the generic inside-a-string test below: the
        # quote (or angle bracket) that opens #include "..."/<...>
        # is, structurally, an unterminated string - exactly what
        # that test exists to detect - so it has to be recognized as
        # an include first, or it would never get past that check.
        include_match = _INCLUDE_PATTERN.match(line[:self.column])
        if include_match:
            opening = include_match.group(1)
            closing = ">" if opening == "<" else '"'
            already_typed = line[include_match.end():self.column]
            if closing in already_typed:
                return []
            headers = (
                _system_header_names(language == "cpp") if opening == "<"
                else self._local_header_names()
            )
            return sorted(
                (name for name in headers if name.startswith(already_typed)),
                key=len,
            )
        if _is_inside_c_string_or_comment(line, self.column):
            return []
        prefix = self._current_word_prefix()
        if len(prefix) < MIN_SUGGESTION_PREFIX:
            return []
        vocabulary = CPP_KEYWORDS if language == "cpp" else C_KEYWORDS
        type_names = CPP_TYPE_NAMES if language == "cpp" else C_TYPE_NAMES
        literals = CPP_LITERALS if language == "cpp" else set()
        # Buffer words and included-header words are equally real
        # identifiers - neither should hide the other just because it
        # happens to be tried first, so they're merged into one pool
        # before falling back to the keyword vocabulary.
        for pool in (
            self._buffer_words_matching(prefix)
            | self._included_header_words_matching(prefix),
            vocabulary | type_names | literals,
        ):
            matches = sorted(
                (
                    word for word in pool
                    if word != prefix and word.startswith(prefix)
                ),
                key=len,
            )
            if matches:
                return matches
        return []

    def _refresh_suggestion_matches(self):
        if self._suggestion_dismissed_at == (self.line, self.column):
            self.suggestion_matches = []
            return
        self._suggestion_dismissed_at = None
        matches = self._compute_suggestion_matches()
        if matches != self.suggestion_matches:
            self.suggestion_index = 0
        self.suggestion_matches = matches

    def _ghost_suggestion(self):
        if len(self.suggestion_matches) != 1:
            return ""
        prefix = self._current_word_prefix()
        return self.suggestion_matches[0][len(prefix):]

    def _suggestion_dropdown_output(
        self, cursor_row, cursor_column, terminal_width, terminal_height
    ):
        items = self.suggestion_matches[:MAX_SUGGESTION_DROPDOWN_ITEMS]
        if len(items) < 2:
            return []
        prefix_length = len(self._current_word_prefix())
        box_width = min(
            max(len(word) for word in items) + 2,
            max(1, terminal_width - 1),
        )
        max_column = terminal_width - box_width + 1
        box_column = max(1, min(cursor_column - prefix_length, max_column))
        box_row_start = cursor_row + 1
        if box_row_start + len(items) - 1 > terminal_height - 1:
            box_row_start = max(2, cursor_row - len(items))
        rows = []
        for offset, word in enumerate(items):
            row = box_row_start + offset
            if not 1 <= row <= terminal_height:
                continue
            text = f" {word} ".ljust(box_width)[:box_width]
            if offset == self.suggestion_index:
                style = theme.BRACKET_MATCH_START + theme.TEXT_COLOR
            else:
                style = theme.BASE_STYLE + theme.SUGGESTION_COLOR
            rows.append(
                f"\x1b[{row};{box_column}H{style}{text}{theme.BASE_STYLE}"
            )
        return rows

    def _accept_suggestion(self, suggestion):
        self._snapshot()
        current_line = self.lines[self.line]
        self.lines[self.line] = (
            current_line[:self.column]
            + suggestion
            + current_line[self.column:]
        )
        self.column += len(suggestion)

    def _accept_highlighted_suggestion(self):
        prefix = self._current_word_prefix()
        word = self.suggestion_matches[self.suggestion_index]
        self._accept_suggestion(word[len(prefix):])
        self.suggestion_matches = []
        self.suggestion_index = 0
