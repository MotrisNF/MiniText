"""File-extension-to-language detection, and the static keyword/type
vocabularies for C and C++ - shared by highlighting.py (coloring) and
autocomplete.py (the keyword-completion fallback), so both stay in
sync from one source instead of two hand-maintained copies."""

import os

LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
}


def language_for(file_name):
    """"python", "c", "cpp", or None for anything else (or no file
    name at all). A ".h" file is treated as C - there's no reliable
    way to tell a C header from a C++ one by name alone, and C is the
    more common convention for a bare ".h"."""
    if not file_name:
        return None
    _, extension = os.path.splitext(file_name)
    return LANGUAGE_EXTENSIONS.get(extension)


# Not exhaustive of every C11/17/23 addition - a lightweight, mostly-
# complete set, the same spirit as Mini's Python side using
# `keyword.kwlist` (an exact, introspected list) where C has no such
# single source of truth to introspect.
C_KEYWORDS = {
    "auto", "break", "case", "const", "continue", "default", "do",
    "else", "enum", "extern", "for", "goto", "if", "inline", "register",
    "restrict", "return", "sizeof", "static", "struct", "switch",
    "typedef", "union", "volatile", "while",
    "_Alignas", "_Alignof", "_Atomic", "_Bool", "_Complex", "_Generic",
    "_Imaginary", "_Noreturn", "_Static_assert", "_Thread_local",
}
# C++ adds these on top of every C keyword above.
CPP_EXTRA_KEYWORDS = {
    "and", "and_eq", "asm", "bitand", "bitor", "catch", "class",
    "compl", "concept", "consteval", "constexpr", "constinit",
    "const_cast", "co_await", "co_return", "co_yield", "decltype",
    "delete", "dynamic_cast", "explicit", "export", "friend", "mutable",
    "namespace", "new", "noexcept", "not", "not_eq", "operator", "or",
    "or_eq", "override", "private", "protected", "public",
    "reinterpret_cast", "requires", "static_assert", "static_cast",
    "template", "this", "thread_local", "throw", "try", "typeid",
    "typename", "using", "virtual", "xor", "xor_eq",
}
CPP_KEYWORDS = C_KEYWORDS | CPP_EXTRA_KEYWORDS

# Built-in-like type names - kept separate from keywords the same way
# Python's TYPE_NAMES is, so they get their own color.
C_TYPE_NAMES = {
    "char", "double", "float", "int", "long", "short", "signed",
    "unsigned", "void",
    "int8_t", "int16_t", "int32_t", "int64_t",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
    "size_t", "ssize_t", "ptrdiff_t", "intptr_t", "uintptr_t",
    "wchar_t", "FILE",
}
CPP_TYPE_NAMES = C_TYPE_NAMES | {
    "bool", "nullptr_t", "string", "wstring",
}
CPP_LITERALS = {"true", "false", "nullptr"}
