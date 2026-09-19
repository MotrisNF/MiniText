""":s/old/new/ - replaces every (plain substring, case-insensitive,
no regex - same matching `_find_next`'s own search already uses)
occurrence of `old` with `new` across the whole buffer, confirmed
first the same way a bulk delete/move already is, undoable as one
step."""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
from commands import CommandMixin  # noqa: E402
from editing import BufferEditMixin  # noqa: E402


class FakeEditor(CommandMixin, BufferEditMixin):
    def __init__(self, lines, confirm_answer=True):
        self.lines = lines
        self.line = 0
        self.column = 0
        self.selection_anchor = None
        self.undo_stack = []
        self.redo_stack = []
        self.modified = False
        self._comment_state = []
        self.status = ""
        self.command = None
        self._highlight_query = "stale"
        self._confirm_answer = confirm_answer
        self.confirm_calls = []

    def _confirm(self, prompt, items=None):
        self.confirm_calls.append(prompt)
        return self._confirm_answer


def test_replaces_every_occurrence_case_insensitively():
    fake = FakeEditor(["Foo = 1", "bar = foo + FOO"])
    fake.command = "s/foo/count/"
    fake._execute_command()
    assert fake.lines == ["count = 1", "bar = count + count"]
    assert fake.status == "Replaced 3 occurrence(s)"
    assert fake.confirm_calls == [
        "Replace 3 occurrence(s) of 'foo' with 'count'? (y/n)"
    ]


def test_empty_new_deletes_every_occurrence():
    fake = FakeEditor(["remove-me-here"])
    fake.command = "s/-me-/-/"
    fake._execute_command()
    assert fake.lines == ["remove-here"]


def test_query_not_found_skips_confirmation_entirely():
    fake = FakeEditor(["nothing here"])
    fake.command = "s/zzz/yyy/"
    fake._execute_command()
    assert fake.lines == ["nothing here"]
    assert fake.status == "'zzz' not found"
    assert fake.confirm_calls == []


def test_declining_the_confirmation_leaves_the_buffer_untouched():
    fake = FakeEditor(["keep me"], confirm_answer=False)
    fake.command = "s/keep/gone/"
    fake._execute_command()
    assert fake.lines == ["keep me"]
    assert fake.status == "Cancelled"


def test_missing_trailing_slash_is_a_usage_error():
    fake = FakeEditor(["a b c"])
    fake.command = "s/a/b"
    fake._execute_command()
    assert fake.lines == ["a b c"]
    assert fake.status == "Usage: :s/old/new/"
    assert fake.confirm_calls == []


def test_empty_old_is_a_usage_error_not_a_match_everything():
    fake = FakeEditor(["a b c"])
    fake.command = "s//new/"
    fake._execute_command()
    assert fake.lines == ["a b c"]
    assert fake.status == "Usage: :s/old/new/"


def test_a_literal_slash_in_old_is_rejected_gracefully():
    """No regex support here (matching search's own "no regex"
    simplicity) - a fourth "/" just doesn't parse as one old/new pair,
    same usage message as any other malformed command instead of
    silently doing something unexpected."""
    fake = FakeEditor(["a/b = 1"])
    fake.command = "s/a/b/c/"
    fake._execute_command()
    assert fake.lines == ["a/b = 1"]
    assert fake.status == "Usage: :s/old/new/"


def test_replace_is_a_single_undo_step():
    fake = FakeEditor(["foo foo foo"])
    fake.command = "s/foo/bar/"
    fake._execute_command()
    assert fake.lines == ["bar bar bar"]
    assert len(fake.undo_stack) == 1
    fake._undo()
    assert fake.lines == ["foo foo foo"]


def test_replace_clears_a_stale_highlight():
    fake = FakeEditor(["foo"])
    fake.command = "s/foo/bar/"
    fake._execute_command()
    assert fake._highlight_query is None


def test_cursor_column_is_clamped_if_the_line_shrank():
    fake = FakeEditor(["a very long line here"])
    fake.column = 20
    fake.command = "s/a very long line here/x/"
    fake._execute_command()
    assert fake.lines == ["x"]
    assert fake.column <= len(fake.lines[0])


TESTS = [
    test_replaces_every_occurrence_case_insensitively,
    test_empty_new_deletes_every_occurrence,
    test_query_not_found_skips_confirmation_entirely,
    test_declining_the_confirmation_leaves_the_buffer_untouched,
    test_missing_trailing_slash_is_a_usage_error,
    test_empty_old_is_a_usage_error_not_a_match_everything,
    test_a_literal_slash_in_old_is_rejected_gracefully,
    test_replace_is_a_single_undo_step,
    test_replace_clears_a_stale_highlight,
    test_cursor_column_is_clamped_if_the_line_shrank,
]
