"""C/C++-specific pieces of autocomplete.py's suggestion engine: its
own comment/string scanning (C's `//`/`/* */` instead of Python's
`#`), and everything to do with `#include` - finding the compiler's
own real system include directories, listing the header names under
them, and reading the identifier-like words out of one a buffer
`#include`s, so a project's own headers contribute completions the
same way the buffer itself does."""

import os
import re
import shutil
import subprocess

_WORD_PATTERN = re.compile(r"\w+")

_INCLUDE_PATTERN = re.compile(r'^\s*#\s*include\s+([<"])')
_INCLUDE_LINE_PATTERN = re.compile(r'^\s*#\s*include\s+([<"])([^>"]+)[>"]')


def _is_inside_c_string_or_comment(line, column):
    """Like autocomplete.py's own `_is_inside_string_or_comment`, for
    C/C++'s comment styles instead of Python's `#`: `//` runs to the
    end of the line; a same-line `/* ... */` is skipped over entirely
    (scanning resumes right after it); one that doesn't close by
    `column` on this line counts as "inside" - same single-line-only
    limitation as a block comment actually spanning multiple lines,
    which this can't see across."""
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
