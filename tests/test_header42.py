""":header inserts the 11-line, 80-column comment block 42-school
projects expect at the top of every source file, built from a login
and campus saved once with :configuser into ~/.mini42 and dropped
again with :clearuser. Covers the three refusals that leave the
buffer completely alone (no file name, no saved login, a cancelled
:configuser), since those are the cases where a half-built header
would otherwise end up in the file.

The fixed Created:/Updated: timestamps are deliberately not asserted
here - they're a known gap listed under Limitations in the README, and
pinning them down in a test would turn that gap into expected
behaviour."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import header42  # noqa: E402
from commands import CommandMixin  # noqa: E402
from editing import BufferEditMixin  # noqa: E402


class FakeEditor(CommandMixin, BufferEditMixin):
    def __init__(self, lines, file_name="main.c", answers=None):
        self.lines = lines
        self.line = 0
        self.column = 0
        self.file_name = file_name
        self.selection_anchor = None
        self.undo_stack = []
        self.redo_stack = []
        self.modified = False
        self._comment_state = []
        self.status = ""
        self.command = None
        self._highlight_query = None
        self._answers = list(answers or [])
        self.prompts = []

    def _render(self):
        pass

    def _read_command_line(self, prompt="File name: "):
        self.prompts.append(prompt)
        return self._answers.pop(0) if self._answers else ""


def _with_temp_config(test_body, existing=None):
    """Points header42 at a throwaway ~/.mini42 for one test, the same
    way test_minirc_migration redirects theme.RC_PATH - these tests
    must never read, write or delete the real login of whoever is
    running them. `existing` pre-seeds the file's raw text."""
    config_path = os.path.join(tempfile.mkdtemp(), "mini42")
    if existing is not None:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(existing)
    original = header42.CONFIG_PATH
    header42.CONFIG_PATH = config_path
    try:
        test_body(config_path)
    finally:
        header42.CONFIG_PATH = original


def test_build_header_needs_a_saved_login_first():
    def body(_path):
        assert header42.build_header("main.c") is None
    _with_temp_config(body)


def test_saved_login_and_campus_are_read_back():
    def body(_path):
        header42.save_config("jsanchez", "Madrid")
        assert header42.load_config() == ("jsanchez", "Madrid")
    _with_temp_config(body)


def test_clearing_forgets_the_login_and_the_file():
    def body(path):
        header42.save_config("jsanchez", "Madrid")
        header42.clear_config()
        assert not os.path.exists(path)
        assert header42.load_config() == (None, None)
        assert header42.build_header("main.c") is None
    _with_temp_config(body)


def test_clearing_an_already_missing_config_is_not_an_error():
    def body(_path):
        header42.clear_config()
        header42.clear_config()
    _with_temp_config(body)


def test_a_config_missing_its_campus_counts_as_unconfigured():
    """A truncated/hand-edited ~/.mini42 shouldn't produce a header
    with "None" in the email address."""
    def body(_path):
        assert header42.load_config() == ("jsanchez", None)
        assert header42.build_header("main.c") is None
    _with_temp_config(body, existing="jsanchez\n")


def test_header_is_eleven_lines_of_exactly_eighty_columns():
    def body(_path):
        header42.save_config("jsanchez", "madrid")
        header = header42.build_header("main.c")
        assert len(header) == 11, len(header)
        assert {len(line) for line in header} == {80}
    _with_temp_config(body)


def test_header_carries_the_file_name_and_the_login():
    def body(_path):
        header42.save_config("jsanchez", "madrid")
        header = header42.build_header("main.c")
        assert "main.c" in header[3]
        assert "By: jsanchez <jsanchez@student.42madrid.com>" in header[5]
    _with_temp_config(body)


def test_the_campus_is_lowercased_in_the_email_only():
    def body(_path):
        header42.save_config("jsanchez", "Madrid")
        assert "@student.42madrid.com" in "\n".join(
            header42.build_header("main.c")
        )
        assert header42.load_config()[1] == "Madrid"
    _with_temp_config(body)


def test_header_command_inserts_above_the_existing_lines():
    def body(_path):
        header42.save_config("jsanchez", "madrid")
        fake = FakeEditor(["int main(void)", "{", "}"])
        fake.command = "header"
        fake._execute_command()
        assert fake.lines[11:] == ["int main(void)", "{", "}"]
        assert len(fake.lines) == 14
        assert fake.status == "Inserted header"
    _with_temp_config(body)


def test_header_command_is_a_single_undo_step():
    def body(_path):
        header42.save_config("jsanchez", "madrid")
        fake = FakeEditor(["int main(void)"])
        fake.command = "header"
        fake._execute_command()
        assert len(fake.undo_stack) == 1
        fake._undo()
        assert fake.lines == ["int main(void)"]
    _with_temp_config(body)


def test_header_command_keeps_the_cursor_on_the_same_code_line():
    def body(_path):
        header42.save_config("jsanchez", "madrid")
        fake = FakeEditor(["int main(void)", "{", "}"], )
        fake.line = 1
        fake.command = "header"
        fake._execute_command()
        assert fake.lines[fake.line] == "{"
    _with_temp_config(body)


def test_header_command_uses_the_base_name_not_the_whole_path():
    def body(_path):
        header42.save_config("jsanchez", "madrid")
        fake = FakeEditor([""], file_name="/home/jsanchez/libft/ft_split.c")
        fake.command = "header"
        fake._execute_command()
        assert "ft_split.c" in fake.lines[3]
        assert "/home/jsanchez" not in "\n".join(fake.lines)
    _with_temp_config(body)


def test_header_on_an_unnamed_buffer_inserts_nothing():
    def body(_path):
        header42.save_config("jsanchez", "madrid")
        fake = FakeEditor(["int main(void)"], file_name=None)
        fake.command = "header"
        fake._execute_command()
        assert fake.lines == ["int main(void)"]
        assert fake.status == "Open or create a file first"
        assert fake.undo_stack == []
    _with_temp_config(body)


def test_header_without_a_saved_login_inserts_nothing():
    def body(_path):
        fake = FakeEditor(["int main(void)"])
        fake.command = "header"
        fake._execute_command()
        assert fake.lines == ["int main(void)"]
        assert fake.status == "User/campus not configured, use :configuser"
        assert fake.undo_stack == []
    _with_temp_config(body)


def test_configuser_saves_both_answers_in_order():
    def body(_path):
        fake = FakeEditor([""], answers=["jsanchez", "Madrid"])
        fake.command = "configuser"
        fake._execute_command()
        assert header42.load_config() == ("jsanchez", "Madrid")
        assert fake.status == "Saved user/campus: jsanchez @ Madrid"
        assert fake.prompts == [
            "User name: ", "Campus (example: madrid, paris, etc...): "
        ]
    _with_temp_config(body)


def test_an_empty_login_cancels_configuser_before_asking_the_campus():
    def body(_path):
        fake = FakeEditor([""], answers=[""])
        fake.command = "configuser"
        fake._execute_command()
        assert header42.load_config() == (None, None)
        assert fake.status == "User name not saved"
        assert fake.prompts == ["User name: "]
    _with_temp_config(body)


def test_an_empty_campus_cancels_configuser_without_saving_the_login():
    def body(_path):
        fake = FakeEditor([""], answers=["jsanchez", ""])
        fake.command = "configuser"
        fake._execute_command()
        assert header42.load_config() == (None, None)
        assert fake.status == "Campus not saved"
    _with_temp_config(body)


def test_a_cancelled_configuser_leaves_an_earlier_login_in_place():
    def body(_path):
        header42.save_config("jsanchez", "Madrid")
        fake = FakeEditor([""], answers=[""])
        fake.command = "configuser"
        fake._execute_command()
        assert header42.load_config() == ("jsanchez", "Madrid")
    _with_temp_config(body)


def test_clearuser_command_forgets_the_login():
    def body(_path):
        header42.save_config("jsanchez", "Madrid")
        fake = FakeEditor([""])
        fake.command = "clearuser"
        fake._execute_command()
        assert header42.load_config() == (None, None)
        assert fake.status == "Cleared saved user/campus"
    _with_temp_config(body)


def test_the_three_commands_reject_a_line_number_argument():
    """:header 3 is a typo, not "header line 3" - it should report an
    unknown command rather than quietly behaving like plain :header."""
    def body(_path):
        header42.save_config("jsanchez", "madrid")
        for command in ("header 3", "configuser 3", "clearuser 3"):
            fake = FakeEditor(["int main(void)"])
            fake.command = command
            fake._execute_command()
            assert fake.lines == ["int main(void)"]
            assert fake.status == f"Unknown command: :{command}"
    _with_temp_config(body)


TESTS = [
    test_build_header_needs_a_saved_login_first,
    test_saved_login_and_campus_are_read_back,
    test_clearing_forgets_the_login_and_the_file,
    test_clearing_an_already_missing_config_is_not_an_error,
    test_a_config_missing_its_campus_counts_as_unconfigured,
    test_header_is_eleven_lines_of_exactly_eighty_columns,
    test_header_carries_the_file_name_and_the_login,
    test_the_campus_is_lowercased_in_the_email_only,
    test_header_command_inserts_above_the_existing_lines,
    test_header_command_is_a_single_undo_step,
    test_header_command_keeps_the_cursor_on_the_same_code_line,
    test_header_command_uses_the_base_name_not_the_whole_path,
    test_header_on_an_unnamed_buffer_inserts_nothing,
    test_header_without_a_saved_login_inserts_nothing,
    test_configuser_saves_both_answers_in_order,
    test_an_empty_login_cancels_configuser_before_asking_the_campus,
    test_an_empty_campus_cancels_configuser_without_saving_the_login,
    test_a_cancelled_configuser_leaves_an_earlier_login_in_place,
    test_clearuser_command_forgets_the_login,
    test_the_three_commands_reject_a_line_number_argument,
]
