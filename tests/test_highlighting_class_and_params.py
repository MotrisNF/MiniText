"""Class names color like types (theme.TYPE_COLOR), and a function/
method definition's own parameter names color on their own
(theme.PARAMETER_COLOR) - with a typed parameter's annotation itself
still colored as a type, not as a parameter."""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import theme  # noqa: E402
from highlighting import _highlight_python  # noqa: E402


def _color_of(line, token):
    """The color escape code immediately preceding `token`'s first
    occurrence in `line` once highlighted - None if it isn't colored
    at all (COLOR_RESET, the plain/no-color case, doesn't count)."""
    colored = _highlight_python(line)
    index = 0
    plain_index = 0
    while plain_index < len(line):
        if colored[index:index + 2] == "\x1b[":
            end = colored.index("m", index) + 1
            index = end
            continue
        if line[plain_index:plain_index + len(token)] == token and (
            plain_index == 0 or not line[plain_index - 1].isalnum()
        ) and colored[index:index + len(token)] == token:
            start = colored.rfind("\x1b[", 0, index)
            code = colored[start:colored.index("m", start) + 1]
            return None if code == theme.COLOR_RESET else code
        index += 1
        plain_index += 1
    raise AssertionError(f"{token!r} not found in {line!r}")


def test_class_definition_name_is_type_colored():
    assert _color_of("class Foo:", "Foo") == theme.TYPE_COLOR


def test_class_name_with_base_class_is_still_type_colored():
    """A base class in parens used to make the highlighter mistake the
    class's own name for a function call (FUNCTION_COLOR) instead."""
    assert _color_of("class Foo(Base):", "Foo") == theme.TYPE_COLOR


def test_def_parameter_names_are_parameter_colored():
    line = "def foo(a, b, *args, **kwargs):"
    for name in ("a", "b", "args", "kwargs"):
        assert _color_of(line, name) == theme.PARAMETER_COLOR, name


def test_call_site_arguments_are_not_parameter_colored():
    """Only a *definition*'s own parameter names get PARAMETER_COLOR -
    not the arguments at a call site, which happen to sit in the exact
    same kind of parenthesized, comma-separated position."""
    assert _color_of("x = foo(a, b)", "a") is None
    assert _color_of("x = foo(a, b)", "b") is None


def test_typed_parameter_splits_name_and_annotation_colors():
    line = "def foo(x: MyClass):"
    assert _color_of(line, "x") == theme.PARAMETER_COLOR
    assert _color_of(line, "MyClass") == theme.TYPE_COLOR


def test_default_value_is_not_parameter_colored():
    assert _color_of("def foo(c=5):", "c") == theme.PARAMETER_COLOR


TESTS = [
    test_class_definition_name_is_type_colored,
    test_class_name_with_base_class_is_still_type_colored,
    test_def_parameter_names_are_parameter_colored,
    test_call_site_arguments_are_not_parameter_colored,
    test_typed_parameter_splits_name_and_annotation_colors,
    test_default_value_is_not_parameter_colored,
]
