"""Covers bugs_conocidos.md: 'Al borrar un tabulador, se detecta como
un espacio' / 'Borrar un tab no te devuelve al indice anterior'."""

from _harness import FakeBuffer


def test_soft_tab_backspace_removes_whole_block():
    buf = FakeBuffer(["        x"], line=0, column=8)  # 8 spaces, INDENT_WITH_TABS=False, TAB_SIZE=4
    buf._backspace()
    assert buf.lines[0] == "    x", buf.lines[0]
    assert buf.column == 4, buf.column


def test_soft_tab_backspace_one_more_removes_remaining_block():
    buf = FakeBuffer(["    x"], line=0, column=4)
    buf._backspace()
    assert buf.lines[0] == "x", buf.lines[0]
    assert buf.column == 0, buf.column


def test_backspace_on_real_tab_char_still_removes_one_tab():
    buf = FakeBuffer(["\tx"], line=0, column=1, file_name="file.txt")
    buf._backspace()
    assert buf.lines[0] == "x", buf.lines[0]
    assert buf.column == 0, buf.column


def test_backspace_mid_line_alignment_spaces_unaffected():
    # Not leading indentation - "x   " before the cursor isn't
    # whitespace-only, so this must fall back to deleting 1 space.
    buf = FakeBuffer(["x    y"], line=0, column=5)
    buf._backspace()
    assert buf.lines[0] == "x   y", buf.lines[0]
    assert buf.column == 4, buf.column


def test_backspace_unaligned_column_falls_back_to_one_space():
    buf = FakeBuffer(["     x"], line=0, column=5)  # 5 spaces, not a multiple of 4
    buf._backspace()
    assert buf.lines[0] == "    x", buf.lines[0]
    assert buf.column == 4, buf.column


TESTS = [
    test_soft_tab_backspace_removes_whole_block,
    test_soft_tab_backspace_one_more_removes_remaining_block,
    test_backspace_on_real_tab_char_still_removes_one_tab,
    test_backspace_mid_line_alignment_spaces_unaffected,
    test_backspace_unaligned_column_falls_back_to_one_space,
]
