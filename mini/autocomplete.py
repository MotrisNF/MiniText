"""Autocompletion for .py files: word-based suggestions from the
buffer plus Python's own keywords/builtins, module-name completion
after import/from, and type-aware `name.` completion (literals,
locally-defined classes via ast, or classes/modules introspected in
an isolated subprocess). C/C++'s own comment-scanning and #include
machinery lives in c_autocomplete.py, and the subprocess/jedi
introspection engine in python_introspection.py - both split out of
here, since neither has anything to do with the Python-specific
(ast/type-inference) completion that makes up the rest of this
file."""

import ast
import bisect
import builtins
import keyword
import os
import re
import sys

import theme
from c_autocomplete import (
    _INCLUDE_LINE_PATTERN, _INCLUDE_PATTERN, _WORD_PATTERN,
    _compiler_include_dirs, _header_words, _is_inside_c_string_or_comment,
    _resolve_system_header_path, _system_header_names,
)
from languages import (
    C_KEYWORDS, C_TYPE_NAMES, CPP_KEYWORDS, CPP_LITERALS, CPP_TYPE_NAMES,
    language_for,
)
from python_introspection import (
    _check_import_resolves, _introspect_class_members,
    _introspect_module_members, _start_background_jedi_completion,
)

MIN_SUGGESTION_PREFIX = 2
# How long a jedi-backed lookup (see _start_background_jedi_completion)
# is worth waiting for synchronously before falling back to Mini's own
# heuristics for this render - short enough that an already-warm/fast
# jedi call (the common case once a session's been running a while)
# still comes back within the same keystroke with no visible delay,
# long enough that it's not pure theater. Measured cost otherwise:
# ~100-160ms per new completion context, and over a second for the
# very first one of a session (see _prewarm_jedi) - both would
# otherwise block every keystroke on Mini's single-threaded key loop.
_JEDI_SYNC_WAIT_SECONDS = 0.03
_JEDI_PENDING = object()


def _resolve_background_jedi(pending, cache_key):
    """Waits up to `_JEDI_SYNC_WAIT_SECONDS` for the background job
    already registered at `pending[cache_key]` (an (event, box) pair
    from `_start_background_jedi_completion`) - `_JEDI_PENDING` if
    it's not done yet (still running in its own thread; a caller
    should fall back to its own heuristics for now and try again on a
    later render - `_notify_suggestion_ready` wakes the main loop up
    on its own for this even without another keypress), otherwise the
    job's own result (clearing the pending entry either way)."""
    event, box = pending[cache_key]
    if not event.wait(_JEDI_SYNC_WAIT_SECONDS):
        return _JEDI_PENDING
    del pending[cache_key]
    return box[0]


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


def _is_word_char(character):
    return character.isalnum() or character == "_"


def _matches_by_prefix(pool, prefix):
    """Every entry in `pool` that starts with `prefix` but isn't
    exactly `prefix` itself, shortest first - the one ranking/
    filtering rule shared by every suggestion source (buffer words,
    keywords, included headers, ...)."""
    return sorted(
        (
            item for item in pool
            if item != prefix and item.startswith(prefix)
        ),
        key=len,
    )


_LINE_WORD_CACHE_LIMIT = 20000


def _is_inside_string_or_comment(line, column, entry_covers_up_to=0):
    """Whether `column` sits inside a string literal or a comment,
    scanning from `entry_covers_up_to` (0 by default) - so an
    unterminated string being typed still counts, even though it has
    no closing quote yet for a regex to match against.

    `entry_covers_up_to` (see rendering.py's `_comment_state_for`) is
    how much of `line`'s own start is already known to be inside a
    docstring carried over from an earlier line - scanning starts
    fresh from there instead of column 0, so a quote character inside
    that region doesn't get misread as opening/closing a string of its
    own."""
    if column < entry_covers_up_to:
        return True
    quote = None
    index = entry_covers_up_to
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


class SuggestionCaches:
    """Every cache/scratch value autocompletion keeps between renders,
    grouped into its own object (constructed once, in TextEditor's own
    `__init__`) instead of a dozen loose `self._..._cache` attributes.
    `word_pool_*` back `_rebuild_static_word_pool`/`_ensure_word_pool_
    fresh`'s own "only the cursor's line changed" shortcut; the three
    dict caches are each keyed by (directory, module, ...) tuples, one
    per external lookup that's worth not repeating (`_check_import_
    resolves`, module/class introspection, jedi)."""

    def __init__(self):
        self.import_members = {}
        self.import_broken = {}
        self.jedi_attribute = {}
        # In-flight background jedi jobs (see
        # _start_background_jedi_completion/_resolve_background_jedi),
        # keyed the same way as the cache each one is headed for -
        # jedi_pending mirrors jedi_attribute, jedi_module_pending
        # mirrors import_members.
        self.jedi_pending = {}
        self.jedi_module_pending = {}
        self.line_word = {}
        self.word_pool_static = frozenset()
        self.word_pool_static_sorted = []
        self.included_header_words_sorted = []
        self.word_pool_lines_ref = None
        self.word_pool_line_count = -1
        self.word_pool_line_index = -1


class SuggestionMixin:

    def _current_word_prefix(self):
        line = self.lines[self.line]
        start = self.column
        while start > 0 and _is_word_char(line[start - 1]):
            start -= 1
        return line[start:self.column]

    def _file_directory(self):
        """The directory suggestions should resolve module/header
        paths relative to - the current file's own directory, or the
        cwd for a buffer with no file yet (a new, unsaved tab)."""
        return (
            os.path.dirname(self.file_name) if self.file_name else ""
        ) or os.getcwd()

    def _line_words(self, line):
        """The identifier-like words in one line's text, cached by the
        line's own content rather than its position - so it stays
        correct no matter how lines are inserted, deleted, or
        reordered, since the key IS the content."""
        cache = self._suggestion_caches.line_word
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
        directory = self._file_directory()
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
        caches = self._suggestion_caches
        caches.word_pool_static = words
        # Sorted once here, not on every keystroke: lets
        # _buffer_words_matching find a prefix's matches by binary
        # search instead of scanning every unique word in the file.
        caches.word_pool_static_sorted = sorted(words)
        caches.included_header_words_sorted = sorted(include_words)
        caches.word_pool_lines_ref = self.lines
        caches.word_pool_line_count = len(self.lines)
        caches.word_pool_line_index = self.line

    def _ensure_word_pool_fresh(self):
        if (
            self.lines is not self._suggestion_caches.word_pool_lines_ref
            or len(self.lines) != self._suggestion_caches.word_pool_line_count
            or self.line != self._suggestion_caches.word_pool_line_index
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
        sorted_words = self._suggestion_caches.included_header_words_sorted
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
        return (
            self._suggestion_caches.word_pool_static
            | self._line_words(current_line)
        )

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
        sorted_words = self._suggestion_caches.word_pool_static_sorted
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
        directory = self._file_directory()
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
        directory = self._file_directory()
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
            directory = self._file_directory()
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
        directory = self._file_directory()
        cache_key = (python_path, directory, module_name, tuple(names))
        caches = self._suggestion_caches
        if cache_key not in caches.import_broken:
            caches.import_broken[cache_key] = _check_import_resolves(
                directory, module_name, names, python_path
            )
        return bool(caches.import_broken[cache_key])

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
        directory = self._file_directory()
        cache_key = (directory, module_name)
        caches = self._suggestion_caches
        if cache_key in caches.import_members:
            return caches.import_members[cache_key]
        python_path = self._resolve_python_executable()
        if cache_key not in caches.jedi_module_pending:
            caches.jedi_module_pending[cache_key] = (
                _start_background_jedi_completion(
                    "\n".join(self.lines), self.file_name,
                    self.line + 1, self.column, python_path,
                )
            )
        jedi_pool = _resolve_background_jedi(
            caches.jedi_module_pending, cache_key
        )
        if jedi_pool is _JEDI_PENDING:
            # Still running in its own thread - try again next render
            # rather than falling back to the (also blocking, if
            # slower) subprocess introspection below on every single
            # one until it lands.
            return set()
        caches.import_members[cache_key] = jedi_pool or (
            _introspect_module_members(directory, module_name, python_path)
        )
        return caches.import_members[cache_key]

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
        already completed once won't be picked up until Mini restarts.

        The actual jedi call runs in a background thread (see
        `_start_background_jedi_completion`) - `None` here means
        either jedi genuinely found nothing (falls back to
        `_infer_attribute_pool`, same as always) or it just hasn't
        finished yet (a later render, once it has, gets the real
        answer from `jedi_attribute` directly instead)."""
        cache_key = (id(self.lines), self.line, dot_index)
        caches = self._suggestion_caches
        if cache_key in caches.jedi_attribute:
            return caches.jedi_attribute[cache_key]
        if cache_key not in caches.jedi_pending:
            python_path = self._resolve_python_executable()
            caches.jedi_pending[cache_key] = _start_background_jedi_completion(
                "\n".join(self.lines), self.file_name,
                self.line + 1, self.column, python_path,
            )
        result = _resolve_background_jedi(caches.jedi_pending, cache_key)
        if result is _JEDI_PENDING:
            return None
        caches.jedi_attribute[cache_key] = result
        return result

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
        directory = self._file_directory()
        cache_key = (directory, module_name, original_name)
        if cache_key not in self._suggestion_caches.import_members:
            self._suggestion_caches.import_members[cache_key] = (
                _introspect_class_members(
                    directory, module_name, original_name,
                    self._resolve_python_executable(),
                )
            )
        return self._suggestion_caches.import_members[cache_key]

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
        _, entry_covers_up_to, _ = self._comment_state_for(self.line)
        if _is_inside_string_or_comment(line, self.column, entry_covers_up_to):
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
                and _is_inside_string_or_comment(
                    line, dot_index - 1, entry_covers_up_to,
                )
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
            matches = _matches_by_prefix(pool, prefix)
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
            self._suggestion_caches.word_pool_line_index = -1
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
            if opening == "<":
                # A system include searches every one of the
                # compiler's own include directories - easily
                # thousands of header names - so, unlike a local
                # "..." include (few files, right next to the one
                # being edited), it waits for a couple of real
                # characters first, the same as ordinary word
                # completion, instead of filtering the whole list on
                # every keystroke starting from zero.
                if len(already_typed) < MIN_SUGGESTION_PREFIX:
                    return []
                headers = _system_header_names(language == "cpp")
            else:
                headers = self._local_header_names()
            return _matches_by_prefix(headers, already_typed)
        _, entry_covers_up_to, _ = self._comment_state_for(self.line)
        if _is_inside_c_string_or_comment(
            line, self.column, entry_covers_up_to
        ):
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
            matches = _matches_by_prefix(pool, prefix)
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

    def _active_suggestion_prefix(self):
        """The prefix actually consumed by the current suggestion
        list - almost always `_current_word_prefix()` (word
        characters immediately before the cursor), except inside a
        C/C++ `#include "..."`/`<...>` filename: a real header name
        routinely contains a `.` or `/`, neither of which counts as a
        "word" character, so the word-based prefix would stop short
        of what's actually been typed (e.g. only "h" of "foo.h").
        Ghost text and Tab-accept both need the real, full amount
        already there - the same `already_typed` the matches
        themselves were filtered by - or they end up keeping the part
        the word-based prefix missed and inserting the whole matched
        name again on top of it (`foo.` + accepting "foo.h" becoming
        "foo.foo.h")."""
        if language_for(self.file_name) in ("c", "cpp"):
            line = self.lines[self.line]
            include_match = _INCLUDE_PATTERN.match(line[:self.column])
            if include_match:
                return line[include_match.end():self.column]
        return self._current_word_prefix()

    def _ghost_suggestion(self):
        if len(self.suggestion_matches) != 1:
            return ""
        prefix = self._active_suggestion_prefix()
        return self.suggestion_matches[0][len(prefix):]

    def _suggestion_dropdown_output(
        self, cursor_row, cursor_column, terminal_width, terminal_height
    ):
        items = self.suggestion_matches[:MAX_SUGGESTION_DROPDOWN_ITEMS]
        if len(items) < 2:
            return []
        prefix_length = len(self._active_suggestion_prefix())
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
        prefix = self._active_suggestion_prefix()
        word = self.suggestion_matches[self.suggestion_index]
        self._accept_suggestion(word[len(prefix):])
        self.suggestion_matches = []
        self.suggestion_index = 0
