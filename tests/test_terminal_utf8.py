"""Regression: read_key() used to decode stdin one byte at a time,
silently dropping every accented/non-ASCII character (a lead byte
alone always fails to decode with errors="ignore")."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import terminal  # noqa: E402


def _feed(text):
    data = iter(text.encode("utf-8"))
    orig_read, orig_select = terminal._read_stdin_byte, terminal.select.select
    terminal._read_stdin_byte = lambda fd: bytes([next(data)])
    terminal.select.select = lambda *a, **k: ([1], [], [])
    try:
        return terminal.read_key()
    finally:
        terminal._read_stdin_byte = orig_read
        terminal.select.select = orig_select


def test_two_byte_utf8_character_decodes_whole():
    assert _feed("ñ") == "ñ"


def test_three_byte_utf8_character_decodes_whole():
    assert _feed("€") == "€"


def test_plain_ascii_is_unaffected():
    assert _feed("a") == "a"


def test_utf8_sequence_length_table():
    assert terminal._utf8_sequence_length(ord("a")) == 1
    assert terminal._utf8_sequence_length("ñ".encode("utf-8")[0]) == 2
    assert terminal._utf8_sequence_length("€".encode("utf-8")[0]) == 3
    assert terminal._utf8_sequence_length("𝄞".encode("utf-8")[0]) == 4
    assert terminal._utf8_sequence_length(0x80) == 1  # stray continuation byte


TESTS = [
    test_two_byte_utf8_character_decodes_whole,
    test_three_byte_utf8_character_decodes_whole,
    test_plain_ascii_is_unaffected,
    test_utf8_sequence_length_table,
]
