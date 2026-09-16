"""Covers bugs_conocidos.md: 'tras escribir : todos los enter
siguientes generan una tabulacion mas, pasando al siguiente nivel'."""

from _harness import FakeBuffer


def _type_line_then_enter(buf, text):
    buf.lines[buf.line] = (
        buf.lines[buf.line][:buf.column] + text
        + buf.lines[buf.line][buf.column:]
    )
    buf.column += len(text)
    buf._new_line()


def test_comment_lines_ending_in_colon_do_not_cascade():
    buf = FakeBuffer([""], line=0, column=0)
    _type_line_then_enter(buf, "# steps:")
    _type_line_then_enter(buf, "# note:")
    _type_line_then_enter(buf, "# also:")
    assert buf.lines == ["# steps:", "# note:", "# also:", ""], buf.lines


def test_real_block_keyword_still_indents_once():
    buf = FakeBuffer([""], line=0, column=0)
    _type_line_then_enter(buf, "def foo():")
    _type_line_then_enter(buf, "pass")
    assert buf.lines == ["def foo():", "    pass", "    "], buf.lines


def test_docstring_style_colon_line_does_not_indent():
    buf = FakeBuffer(["    "], line=0, column=4)
    _type_line_then_enter(buf, ":param x:")
    assert buf.lines == ["    :param x:", "    "], buf.lines


def test_else_and_case_still_indent():
    buf = FakeBuffer([""], line=0, column=0)
    _type_line_then_enter(buf, "else:")
    assert buf.lines == ["else:", "    "], buf.lines


TESTS = [
    test_comment_lines_ending_in_colon_do_not_cascade,
    test_real_block_keyword_still_indents_once,
    test_docstring_style_colon_line_does_not_indent,
    test_else_and_case_still_indent,
]
