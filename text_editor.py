import builtins
import keyword
import os
import re
import select
import shutil
import signal
import sys
import termios
import tty
from contextlib import contextmanager

import theme


ESC = "\x1b"
PAIRS = {"(": ")", "[": "]", "{": "}", "'": "'", '"': '"'}
BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
CLOSING_TO_OPENING = {value: key for key, value in BRACKET_PAIRS.items()}
QUOTE_CHARACTERS = {"'", '"'}
ASDF_TO_ARROW = {"a": "LEFT", "s": "UP", "d": "DOWN", "f": "RIGHT"}
MOVEMENT_KEYS = {
    "UP", "DOWN", "LEFT", "RIGHT",
    "CTRL-UP", "CTRL-DOWN", "CTRL-LEFT", "CTRL-RIGHT",
}
WORKTREE_WIDTH = 28
MIN_EDITOR_WIDTH = 20
WORKTREE_SEPARATOR_WIDTH = 2
MIN_SUGGESTION_PREFIX = 2
PYTHON_VOCABULARY = sorted(
    set(keyword.kwlist)
    | {name for name in dir(builtins) if not name.startswith("_")}
)
ATTRIBUTE_VOCABULARY = sorted({
    name
    for type_object in (
        str, list, dict, set, tuple, frozenset, bytes, bytearray,
        int, float,
    )
    for name in dir(type_object)
    if not name.startswith("_")
})
MODULE_VOCABULARY = sorted(
    name for name in sys.stdlib_module_names if not name.startswith("_")
)
IMPORT_CONTEXT_PATTERN = re.compile(r"^\s*(?:from|import)\s+$")

TYPE_NAMES = {
    "int", "float", "str", "bool", "list", "dict", "tuple", "set",
    "frozenset", "bytes", "bytearray", "complex", "object", "type",
}
_TOKEN_PATTERN = re.compile(
    r"'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
    r"|#.*"
    r"|[A-Za-z_][A-Za-z0-9_]*"
)


def _is_word_char(character):
    return character.isalnum() or character == "_"


def _highlight(display_text):
    def _colorize(match):
        token = match.group()
        if token[0] in ("'", '"', "#"):
            return token
        if token in keyword.kwlist:
            return f"{theme.KEYWORD_COLOR}{token}{theme.COLOR_RESET}"
        if token.startswith("__"):
            return f"{theme.DUNDER_COLOR}{token}{theme.COLOR_RESET}"
        if token in TYPE_NAMES:
            return f"{theme.TYPE_COLOR}{token}{theme.COLOR_RESET}"
        if display_text[match.end():].lstrip(" ").startswith("("):
            return f"{theme.FUNCTION_COLOR}{token}{theme.COLOR_RESET}"
        return token

    return _TOKEN_PATTERN.sub(_colorize, display_text)


def _handle_resize(_signum, _frame):
    pass


def _get_terminal_size():
    try:
        return os.get_terminal_size(sys.stdout.fileno())
    except OSError:
        return os.terminal_size((80, 24))


_resize_wakeup_fd = None


def _enable_resize_wakeup():
    global _resize_wakeup_fd
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    signal.set_wakeup_fd(write_fd)
    _resize_wakeup_fd = read_fd
    return read_fd, write_fd


def _disable_resize_wakeup(read_fd, write_fd):
    global _resize_wakeup_fd
    signal.set_wakeup_fd(-1)
    _resize_wakeup_fd = None
    os.close(read_fd)
    os.close(write_fd)


@contextmanager
def raw_terminal():
    file_descriptor = sys.stdin.fileno()
    previous_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        sys.stdout.write(f"\x1b[?1049h{theme.BASE_STYLE}\x1b[2J\x1b[H")
        sys.stdout.flush()
        yield
    finally:
        termios.tcsetattr(
            file_descriptor, termios.TCSADRAIN, previous_settings
        )
        sys.stdout.write("\x1b[?25h\x1b[0m\x1b[?1049l")
        sys.stdout.flush()


_pending_byte = None


def _read_stdin_byte(stdin_fd):
    global _pending_byte
    if _pending_byte is not None:
        byte = _pending_byte
        _pending_byte = None
        return byte
    return os.read(stdin_fd, 1)


def _pushback_byte(byte):
    global _pending_byte
    _pending_byte = byte


def read_key():
    stdin_fd = sys.stdin.fileno()
    watch_fds = [stdin_fd]
    if _pending_byte is None and _resize_wakeup_fd is not None:
        watch_fds.append(_resize_wakeup_fd)
    if _pending_byte is None:
        try:
            ready, _, _ = select.select(watch_fds, [], [])
        except InterruptedError:
            return "RESIZE"
        if _resize_wakeup_fd is not None and _resize_wakeup_fd in ready:
            try:
                os.read(_resize_wakeup_fd, 4096)
            except OSError:
                pass
            return "RESIZE"

    first_byte = _read_stdin_byte(stdin_fd)
    if not first_byte:
        return "EOF"

    key = first_byte.decode("utf-8", errors="ignore")
    if key != ESC:
        return key

    try:
        ready, _, _ = select.select([stdin_fd], [], [], 0.05)
    except InterruptedError:
        return "RESIZE"
    if not ready:
        return ESC
    next_byte = _read_stdin_byte(stdin_fd)
    if next_byte != b"[":
        if next_byte:
            _pushback_byte(next_byte)
        return ESC

    final, params = _read_csi_final(stdin_fd)
    if final is None:
        return ESC
    modifier_parts = params.split(";")
    ctrl = len(modifier_parts) >= 2 and modifier_parts[1] in (
        "5", "6", "7", "8"
    )
    if final == "A":
        return "CTRL-UP" if ctrl else "UP"
    if final == "B":
        return "CTRL-DOWN" if ctrl else "DOWN"
    if final == "C":
        return "CTRL-RIGHT" if ctrl else "RIGHT"
    if final == "D":
        return "CTRL-LEFT" if ctrl else "LEFT"
    if final == "~" and modifier_parts[0] == "3":
        return "DELETE"
    return ESC


def _read_csi_final(stdin_fd):
    params = ""
    while True:
        try:
            ready, _, _ = select.select([stdin_fd], [], [], 0.05)
        except InterruptedError:
            return None, params
        if not ready:
            return None, params
        raw_byte = os.read(stdin_fd, 1)
        if not raw_byte:
            return None, params
        char = raw_byte.decode("utf-8", errors="ignore")
        if char in "0123456789;":
            params += char
        else:
            return char, params


class TextEditor:
    def __init__(self, file_name=None):
        self.file_name = file_name
        self.lines = self._read_file(file_name)
        self.line = 0
        self.column = 0
        self.mode = "visual"
        self.command = None
        self.status = ""
        self.running = True
        self.help_mode = False
        self.help_pending = False
        self.viewport_top = 0
        self.selection_anchor = None
        self.clipboard = None
        self.pending_count = ""
        self.search_query = None
        self.last_search = None
        self.undo_stack = []
        self.redo_stack = []
        self.modified = False
        self.worktree_visible = False
        self.worktree_focused = False
        self.worktree_visible_because_of_focus = False
        self.worktree_root = os.getcwd()
        self.worktree_expanded = set()
        self.worktree_cursor = 0
        self.worktree_scroll = 0
        self.worktree_selected_dir = self.worktree_root
        self.tabs = [self._current_buffer_state()]
        self.active_tab = 0

    BUFFER_ATTRIBUTES = (
        "file_name", "lines", "line", "column", "selection_anchor",
        "viewport_top", "undo_stack", "redo_stack", "modified",
    )

    def _current_buffer_state(self):
        return {
            attribute: getattr(self, attribute)
            for attribute in self.BUFFER_ATTRIBUTES
        }

    def _apply_buffer_state(self, state):
        for attribute, value in state.items():
            setattr(self, attribute, value)

    @staticmethod
    def _blank_buffer_state():
        return {
            "file_name": None, "lines": [""], "line": 0, "column": 0,
            "selection_anchor": None, "viewport_top": 0,
            "undo_stack": [], "redo_stack": [], "modified": False,
        }

    def _sync_active_tab(self):
        self.tabs[self.active_tab] = self._current_buffer_state()

    def _switch_to_tab(self, index):
        self._sync_active_tab()
        self.active_tab = index
        self._apply_buffer_state(self.tabs[self.active_tab])
        self.selection_anchor = None
        self.pending_count = ""

    def _open_in_new_tab(self, path):
        try:
            lines = self._read_file(path)
        except OSError as error:
            self.status = f"Cannot open: {error}"
            return
        self._sync_active_tab()
        new_state = self._blank_buffer_state()
        new_state["file_name"] = path
        new_state["lines"] = lines
        self.tabs.append(new_state)
        self.active_tab = len(self.tabs) - 1
        self._apply_buffer_state(self.tabs[self.active_tab])
        self.status = f"Opened {path} in a new tab"

    def _close_current_tab(self):
        if len(self.tabs) <= 1:
            self.running = False
            return
        del self.tabs[self.active_tab]
        self.active_tab = min(self.active_tab, len(self.tabs) - 1)
        self._apply_buffer_state(self.tabs[self.active_tab])
        self.selection_anchor = None

    def _tab_bar_line(self):
        segments = []
        for index, state in enumerate(self.tabs):
            if index == self.active_tab:
                file_name = self.file_name
                modified = self.modified
                background = theme.BACKGROUND_COLOR
            else:
                file_name = state["file_name"]
                modified = state["modified"]
                background = theme.INACTIVE_TAB_COLOR
            name = os.path.basename(file_name) if file_name else "no name"
            marker = "● " if modified else ""
            segments.append(
                f"{background}{theme.TEXT_COLOR} {marker}{name} "
                f"{theme.BASE_STYLE}"
            )
        separator = f"{theme.LINE_NUMBER_COLOR}│{theme.BASE_STYLE}"
        return separator.join(segments)

    @staticmethod
    def _read_file(file_name):
        if file_name is None:
            return [""]
        if not os.path.exists(file_name):
            parent_directory = os.path.dirname(os.path.abspath(file_name))
            if not os.path.isdir(parent_directory):
                raise FileNotFoundError(file_name)
            return [""]
        try:
            with open(file_name, "r", encoding="utf-8") as file:
                content = file.read()
        except UnicodeDecodeError as error:
            raise OSError(
                f"'{file_name}' is not a UTF-8 text file"
            ) from error
        return content.split("\n") if content else [""]

    @staticmethod
    def _display_text(text):
        return text.replace("\t", "    ")

    def _display_column(self):
        return len(self._display_text(self.lines[self.line][:self.column]))

    def _is_python_file(self):
        return bool(self.file_name) and self.file_name.endswith(".py")

    def _matching_bracket_position(self):
        line = self.lines[self.line]
        if self.column >= len(line):
            return None
        character = line[self.column]
        if character in BRACKET_PAIRS:
            return self._find_bracket_forward(
                character, BRACKET_PAIRS[character]
            )
        if character in CLOSING_TO_OPENING:
            return self._find_bracket_backward(
                CLOSING_TO_OPENING[character], character
            )
        if character in QUOTE_CHARACTERS:
            return self._find_matching_quote(character)
        return None

    def _find_matching_quote(self, quote_character):
        line = self.lines[self.line]
        for column_index in range(self.column + 1, len(line)):
            if line[column_index] == quote_character:
                return (self.line, column_index)
        for column_index in range(self.column - 1, -1, -1):
            if line[column_index] == quote_character:
                return (self.line, column_index)
        return None

    def _find_bracket_forward(self, opening, closing):
        depth = 0
        for line_index in range(self.line, len(self.lines)):
            text = self.lines[line_index]
            start_column = self.column if line_index == self.line else 0
            for column_index in range(start_column, len(text)):
                character = text[column_index]
                if character == opening:
                    depth += 1
                elif character == closing:
                    depth -= 1
                    if depth == 0:
                        return (line_index, column_index)
        return None

    def _find_bracket_backward(self, opening, closing):
        depth = 0
        for line_index in range(self.line, -1, -1):
            text = self.lines[line_index]
            end_column = (
                self.column if line_index == self.line else len(text) - 1
            )
            for column_index in range(end_column, -1, -1):
                character = text[column_index]
                if character == closing:
                    depth += 1
                elif character == opening:
                    depth -= 1
                    if depth == 0:
                        return (line_index, column_index)
        return None

    def _render_segment(
        self, text_segment, absolute_start, bracket_column, apply_highlight
    ):
        if (
            bracket_column is not None
            and absolute_start <= bracket_column
            < absolute_start + len(text_segment)
        ):
            local_index = bracket_column - absolute_start
            before = text_segment[:local_index]
            bracket_character = text_segment[local_index]
            after = text_segment[local_index + 1:]
            return (
                apply_highlight(self._display_text(before))
                + theme.BRACKET_MATCH_START
                + self._display_text(bracket_character)
                + theme.BRACKET_MATCH_END
                + apply_highlight(self._display_text(after))
            )
        return apply_highlight(self._display_text(text_segment))

    def _render_help(self):
        file_name = self.file_name or "[no name]"
        output = [
            "\x1b[2J\x1b[H",
            theme.BASE_STYLE,
            f"File: {file_name}\r\n\r\n",
            "Available commands:\r\n",
            "  Esc h    Show this help\r\n",
            "  :help    Show this help\r\n",
            "  i        Enter Insert mode\r\n",
            "  Tab      Accept suggestion (Insert mode)\r\n",
            "  Ctrl+Arrows  Select text (Visual mode)\r\n",
            "  w        Show and focus the worktree panel (Visual mode)\r\n",
            "  :w       Toggle the worktree panel's visibility\r\n",
            "  Worktree: Up/Down move, Enter opens a file as a tab\r\n",
            "    (or switches to it if already open) or\r\n",
            "    expands/collapses a directory. Ctrl+F new file,\r\n",
            "    Ctrl+D new folder, Del deletes, v/Esc return focus,\r\n",
            "    : or i jump to Command/Insert\r\n",
            "  Tab      Switch to the next tab (Visual mode)\r\n",
            "  a s d f  Move left/up/down/right (Visual mode)\r\n",
            "  <n> then a move   Repeat that move n times (Visual)\r\n",
            "  :l <n>   Jump to line n\r\n",
            "  :d       Delete selection\r\n",
            "  :d <n>   Delete line n\r\n",
            "  :c       Copy selection, or the current line if none\r\n",
            "  :cl <n>  Copy line n\r\n",
            "  :v       Paste at the cursor\r\n",
            "  :vl <n>  Paste as a new line before line n\r\n",
            "  :u / Ctrl+Z  Undo\r\n",
            "  :r / Ctrl+Y  Redo\r\n",
            "  /text or :f text  Search\r\n",
            "  n        Repeat last search (Visual mode)\r\n",
            "  :s       Save\r\n",
            "  :x       Close this tab (asks to save changes if any);\r\n",
            "           exits if it's the last tab open\r\n",
            "  :sx/:xs  Save and close this tab (or exit if last)\r\n",
            "  :s!      Save every open tab, no confirmation\r\n",
            "  :x!      Exit now, discarding all unsaved changes\r\n",
            "  :sx!/:xs!  Save every open tab, then exit\r\n",
            "  q        Return to the editor\r\n",
            "\r\nPress q to return to the editor.",
            "\x1b[?25l\x1b[3;1H\x1b[?25h",
        ]
        sys.stdout.write("".join(output))
        sys.stdout.flush()

    def _render(self):
        if self.help_mode:
            self._render_help()
            return
        number_width = len(str(len(self.lines)))
        tab_bar = self._tab_bar_line()
        terminal_height = max(4, _get_terminal_size().lines)
        terminal_width = _get_terminal_size().columns
        input_row = terminal_height - 1
        visible_rows = max(1, terminal_height - 3)
        self._ensure_cursor_visible(visible_rows)
        last_visible_line = min(
            len(self.lines), self.viewport_top + visible_rows
        )
        selection_bounds = self._selection_bounds()
        suggestion = self._suggestion()
        bracket_match = self._matching_bracket_position()
        apply_highlight = _highlight if self._is_python_file() else (
            lambda text: text
        )
        show_number = theme.SHOW_NUMBER_LINE
        show_indicator = theme.SHOW_LINE_INDICATOR
        gutter_width = (3 if show_indicator else 0) + (
            number_width + 1 if show_number else 0
        )
        sidebar_visible = self.worktree_visible and terminal_width >= (
            WORKTREE_WIDTH + WORKTREE_SEPARATOR_WIDTH + MIN_EDITOR_WIDTH
        )
        editor_col_offset = (
            WORKTREE_WIDTH + WORKTREE_SEPARATOR_WIDTH if sidebar_visible
            else 0
        )
        sidebar_lines = (
            self._worktree_body_lines(visible_rows) if sidebar_visible
            else []
        )

        output = [
            "\x1b[2J\x1b[H", theme.BASE_STYLE,
            f"{tab_bar}\r\n",
        ]
        for row_offset in range(visible_rows):
            index = self.viewport_top + row_offset
            if index < last_visible_line:
                text = self.lines[index]
                is_current_line = index == self.line
                if not show_indicator:
                    marker = ""
                elif is_current_line:
                    marker = (
                        f"{theme.CURRENT_LINE_INDICATOR_COLOR}"
                        f"->{theme.COLOR_RESET} "
                    )
                else:
                    marker = "   "
                if show_number:
                    number = (
                        f"{theme.LINE_NUMBER_COLOR}"
                        f"{index + 1:>{number_width}}"
                        f"{theme.COLOR_RESET} "
                    )
                else:
                    number = ""
                selection_range = self._selection_range_for_line(
                    index, selection_bounds
                )
                bracket_column = (
                    bracket_match[1]
                    if bracket_match and bracket_match[0] == index
                    else None
                )
                if is_current_line and suggestion:
                    displayed = (
                        self._render_segment(
                            text[:self.column], 0, bracket_column,
                            apply_highlight,
                        )
                        + theme.SUGGESTION_COLOR
                        + self._display_text(suggestion)
                        + theme.SUGGESTION_RESET
                        + self._render_segment(
                            text[self.column:], self.column,
                            bracket_column, apply_highlight,
                        )
                    )
                elif selection_range is None:
                    displayed = self._render_segment(
                        text, 0, bracket_column, apply_highlight
                    )
                else:
                    start, end = selection_range
                    displayed = (
                        self._render_segment(
                            text[:start], 0, bracket_column,
                            apply_highlight,
                        )
                        + theme.SELECTION_START
                        + self._render_segment(
                            text[start:end], start, bracket_column,
                            apply_highlight,
                        )
                        + theme.SELECTION_END
                        + self._render_segment(
                            text[end:], end, bracket_column,
                            apply_highlight,
                        )
                    )
                editor_row = f"{marker}{number}{displayed}"
            elif index == last_visible_line and show_number:
                placeholder_prefix = "   " if show_indicator else ""
                editor_row = (
                    f"{theme.PLACEHOLDER_COLOR}{placeholder_prefix}"
                    f"{last_visible_line + 1:>{number_width}} "
                    f"{theme.PLACEHOLDER_RESET}"
                )
            else:
                editor_row = ""

            terminal_row = 2 + row_offset
            if sidebar_visible:
                separator = f"{theme.LINE_NUMBER_COLOR}|{theme.COLOR_RESET} "
                row_text = (
                    f"{sidebar_lines[row_offset]}{separator}{editor_row}"
                )
            else:
                row_text = editor_row
            output.append(f"\x1b[{terminal_row};1H\x1b[K{row_text}")

        output.append(f"\x1b[{input_row};1H\x1b[K")
        if editor_col_offset:
            output.append(f"\x1b[{input_row};{editor_col_offset + 1}H")
        if self.command is not None:
            output.append(f":{self.command}")
        elif self.search_query is not None:
            output.append(f"/{self.search_query}")
        elif self.status:
            output.append(self.status)
        output.append(f"\x1b[{terminal_height};1H\x1b[K")
        if editor_col_offset:
            output.append(f"\x1b[{terminal_height};{editor_col_offset + 1}H")
        output.append(f"Mode: {self.mode.title()}")
        position_text = f"Line: {self.line + 1} Col: {self.column + 1}"
        position_column = max(1, terminal_width - len(position_text) + 1)
        output.append(
            f"\x1b[{terminal_height};{position_column}H{position_text}"
        )

        output.append("\x1b[?25l")
        if self.worktree_focused:
            cursor_row = 2 + 1 + self.worktree_cursor - self.worktree_scroll
            cursor_column = 1
        elif self.command is None and self.search_query is None:
            cursor_row = self.line - self.viewport_top + 2
            cursor_column = (
                editor_col_offset + gutter_width + 1
                + self._display_column()
            )
        elif self.command is not None:
            cursor_row = input_row
            cursor_column = editor_col_offset + len(self.command) + 2
        else:
            cursor_row = input_row
            cursor_column = editor_col_offset + len(self.search_query) + 2
        output.append(f"\x1b[{cursor_row};{cursor_column}H\x1b[?25h")
        sys.stdout.write("".join(output))
        sys.stdout.flush()

    def _ensure_cursor_visible(self, visible_rows):
        if self.line < self.viewport_top:
            self.viewport_top = self.line
        elif self.line >= self.viewport_top + visible_rows:
            self.viewport_top = self.line - visible_rows + 1

    def _move_vertical(self, amount):
        self.line = max(0, min(len(self.lines) - 1, self.line + amount))
        self.column = min(self.column, len(self.lines[self.line]))

    def _move_horizontal(self, amount):
        self.column = max(
            0, min(len(self.lines[self.line]), self.column + amount)
        )

    def _consume_count(self):
        count = int(self.pending_count) if self.pending_count else 1
        self.pending_count = ""
        return max(1, count)

    def _current_word_prefix(self):
        line = self.lines[self.line]
        start = self.column
        while start > 0 and _is_word_char(line[start - 1]):
            start -= 1
        return line[start:self.column]

    def _collect_buffer_words(self):
        words = set()
        for line in self.lines:
            word = ""
            for character in line:
                if _is_word_char(character):
                    word += character
                else:
                    if word:
                        words.add(word)
                    word = ""
            if word:
                words.add(word)
        return words

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
            if entry.name == "__init__.py":
                continue
            if entry.is_file() and entry.name.endswith(".py"):
                name = entry.name[:-len(".py")]
            elif entry.is_dir() and os.path.isfile(
                os.path.join(entry.path, "__init__.py")
            ):
                name = entry.name
            else:
                continue
            if name.isidentifier():
                names.add(name)
        return names

    def _suggestion(self):
        if self.mode != "insert" or not self._is_python_file():
            return ""
        prefix = self._current_word_prefix()
        if len(prefix) < MIN_SUGGESTION_PREFIX:
            return ""
        line = self.lines[self.line]
        if self.column < len(line) and _is_word_char(line[self.column]):
            return ""
        prefix_start = self.column - len(prefix)
        is_attribute = prefix_start > 0 and line[prefix_start - 1] == "."
        is_import = bool(
            IMPORT_CONTEXT_PATTERN.match(line[:prefix_start])
        )
        if is_import:
            pools = (
                self._collect_buffer_words(),
                self._local_module_names(),
                MODULE_VOCABULARY,
            )
        elif is_attribute:
            pools = (self._collect_buffer_words(), ATTRIBUTE_VOCABULARY)
        else:
            pools = (self._collect_buffer_words(), PYTHON_VOCABULARY)
        for pool in pools:
            matches = sorted(
                (
                    word for word in pool
                    if word != prefix and word.startswith(prefix)
                ),
                key=len,
            )
            if matches:
                return matches[0][len(prefix):]
        return ""

    def _snapshot(self):
        self.undo_stack.append((list(self.lines), self.line, self.column))
        self.redo_stack.clear()
        if len(self.undo_stack) > 1000:
            del self.undo_stack[0]
        self.modified = True

    def _undo(self):
        if not self.undo_stack:
            self.status = "Nothing to undo"
            return
        self.redo_stack.append((list(self.lines), self.line, self.column))
        self.lines, self.line, self.column = self.undo_stack.pop()
        self.selection_anchor = None
        self.modified = True
        self.status = "Undone"

    def _redo(self):
        if not self.redo_stack:
            self.status = "Nothing to redo"
            return
        self.undo_stack.append((list(self.lines), self.line, self.column))
        self.lines, self.line, self.column = self.redo_stack.pop()
        self.selection_anchor = None
        self.modified = True
        self.status = "Redone"

    def _accept_suggestion(self, suggestion):
        self._snapshot()
        current_line = self.lines[self.line]
        self.lines[self.line] = (
            current_line[:self.column]
            + suggestion
            + current_line[self.column:]
        )
        self.column += len(suggestion)

    def _update_selection(self, key):
        extending = self.mode == "visual" and key.startswith("CTRL-")
        if extending:
            if self.selection_anchor is None:
                self.selection_anchor = (self.line, self.column)
        else:
            self.selection_anchor = None

    def _selection_bounds(self):
        if self.selection_anchor is None:
            return None
        anchor = self.selection_anchor
        cursor = (self.line, self.column)
        if anchor == cursor:
            return None
        start, end = (anchor, cursor) if anchor < cursor else (cursor, anchor)
        return start[0], start[1], end[0], end[1]

    def _selection_range_for_line(self, index, bounds):
        if bounds is None:
            return None
        start_line, start_column, end_line, end_column = bounds
        if index < start_line or index > end_line:
            return None
        line_length = len(self.lines[index])
        start = start_column if index == start_line else 0
        end = end_column if index == end_line else line_length
        if start >= end:
            return None
        return start, end

    def _selected_text(self):
        bounds = self._selection_bounds()
        if bounds is None:
            return None
        start_line, start_column, end_line, end_column = bounds
        if start_line == end_line:
            return self.lines[start_line][start_column:end_column]
        parts = [self.lines[start_line][start_column:]]
        parts.extend(self.lines[start_line + 1:end_line])
        parts.append(self.lines[end_line][:end_column])
        return "\n".join(parts)

    def _delete_selection(self):
        bounds = self._selection_bounds()
        if bounds is None:
            return False
        self._snapshot()
        start_line, start_column, end_line, end_column = bounds
        remainder = (
            self.lines[start_line][:start_column]
            + self.lines[end_line][end_column:]
        )
        del self.lines[start_line:end_line + 1]
        self.lines.insert(start_line, remainder)
        if not self.lines:
            self.lines = [""]
        self.line = start_line
        self.column = start_column
        self.selection_anchor = None
        return True

    def _paste(self, text):
        self._snapshot()
        pasted_lines = text.split("\n")
        current_line = self.lines[self.line]
        before = current_line[:self.column]
        after = current_line[self.column:]
        if len(pasted_lines) == 1:
            self.lines[self.line] = before + pasted_lines[0] + after
            self.column = len(before) + len(pasted_lines[0])
            return
        middle_lines = pasted_lines[1:-1]
        last_line = pasted_lines[-1]
        self.lines[self.line] = before + pasted_lines[0]
        insert_at = self.line + 1
        for offset, line_text in enumerate(middle_lines):
            self.lines.insert(insert_at + offset, line_text)
        self.lines.insert(insert_at + len(middle_lines), last_line + after)
        self.line = insert_at + len(middle_lines)
        self.column = len(last_line)

    def _insert(self, character):
        current_line = self.lines[self.line]
        if (
            character in PAIRS.values()
            and self.column < len(current_line)
            and current_line[self.column] == character
        ):
            self.column += 1
            return
        self._snapshot()
        closing_character = PAIRS.get(character, "")
        self.lines[self.line] = (
            current_line[:self.column]
            + character
            + closing_character
            + current_line[self.column:]
        )
        self.column += len(character)

    def _backspace(self):
        if not self.column and not self.line:
            return
        self._snapshot()
        if self.column:
            current_line = self.lines[self.line]
            removed_character = current_line[self.column - 1]
            following_character = (
                current_line[self.column]
                if self.column < len(current_line) else ""
            )
            delete_pair = (
                removed_character in PAIRS
                and following_character == PAIRS[removed_character]
            )
            end = self.column + 1 if delete_pair else self.column
            self.lines[self.line] = (
                current_line[: self.column - 1] + current_line[end:]
            )
            self.column -= 1
        elif self.line:
            previous_line = self.lines[self.line - 1]
            self.column = len(previous_line)
            self.lines[self.line - 1] = (
                previous_line + self.lines.pop(self.line)
            )
            self.line -= 1

    def _delete_forward(self):
        current_line = self.lines[self.line]
        if self.column < len(current_line):
            self._snapshot()
            self.lines[self.line] = (
                current_line[:self.column] + current_line[self.column + 1:]
            )
        elif self.line < len(self.lines) - 1:
            self._snapshot()
            next_line = self.lines.pop(self.line + 1)
            self.lines[self.line] = current_line + next_line

    @staticmethod
    def _leading_tabs(line):
        count = 0
        for character in line:
            if character != "\t":
                break
            count += 1
        return "\t" * count

    def _new_line(self):
        self._snapshot()
        current_line = self.lines[self.line]
        before = current_line[:self.column]
        after = current_line[self.column:]
        indent = self._leading_tabs(current_line)
        if before.rstrip().endswith(":"):
            indent += "\t"
        self.lines[self.line] = before
        self.lines.insert(self.line + 1, indent + after)
        self.line += 1
        self.column = len(indent)

    def _save(self):
        if self.file_name is None:
            self.status = "Name of the file:"
            self._render()
            self.file_name = self._read_command_line()
            if not self.file_name:
                self.status = "Not saved"
                return False
        with open(self.file_name, "w", encoding="utf-8") as file:
            file.write("\n".join(self.lines))
        self.modified = False
        self.status = f"Saved to {self.file_name}"
        return True

    def _save_all_tabs(self):
        self._sync_active_tab()
        saved = 0
        skipped = 0
        for state in self.tabs:
            if state["file_name"] is None:
                skipped += 1
                continue
            try:
                with open(
                    state["file_name"], "w", encoding="utf-8"
                ) as file:
                    file.write("\n".join(state["lines"]))
            except OSError:
                skipped += 1
                continue
            state["modified"] = False
            saved += 1
        self._apply_buffer_state(self.tabs[self.active_tab])
        if skipped:
            self.status = f"Saved {saved} tab(s), skipped {skipped}"
        else:
            self.status = f"Saved {saved} tab(s)"

    def _execute_forced_command(self, name):
        if name == "s":
            self._save_all_tabs()
        elif name == "x":
            self.running = False
        elif name in ("sx", "xs"):
            self._save_all_tabs()
            self.running = False

    def _read_command_line(self, label="File name"):
        value = ""
        while True:
            key = read_key()
            if key in ("\r", "\n"):
                return value.strip()
            if key in ("\x7f", "\b"):
                value = value[:-1]
            elif key == ESC:
                return ""
            elif len(key) == 1 and key.isprintable():
                value += key
            self.status = f"{label}: {value}"
            self._render()

    def _confirm(self, prompt):
        self.status = prompt
        self._render()
        while True:
            key = read_key()
            if key in ("y", "Y"):
                return True
            if key in ("n", "N", ESC):
                return False

    def _load_file(self, path):
        try:
            lines = self._read_file(path)
        except OSError as error:
            self.status = f"Cannot open: {error}"
            return
        self.file_name = path
        self.lines = lines
        self.line = 0
        self.column = 0
        self.selection_anchor = None
        self.pending_count = ""
        self.command = None
        self.search_query = None
        self.undo_stack = []
        self.redo_stack = []
        self.modified = False
        self.viewport_top = 0
        self.status = f"Opened {path}"

    def _worktree_entries(self):
        entries = []

        def walk(directory, depth):
            try:
                children = sorted(
                    os.scandir(directory),
                    key=lambda entry: (not entry.is_dir(), entry.name.lower())
                )
            except OSError:
                children = []
            for entry in children:
                entries.append((entry.path, entry.name, entry.is_dir(), depth))
                if entry.is_dir() and entry.path in self.worktree_expanded:
                    walk(entry.path, depth + 1)

        walk(self.worktree_root, 0)
        return entries

    def _release_worktree_focus(self):
        self.worktree_focused = False
        if self.worktree_visible_because_of_focus:
            self.worktree_visible = False
            self.worktree_visible_because_of_focus = False

    def _find_tab_for_path(self, path):
        for index, state in enumerate(self.tabs):
            file_name = (
                self.file_name if index == self.active_tab
                else state["file_name"]
            )
            if file_name == path:
                return index
        return None

    def _worktree_activate(self, entries):
        if not entries:
            return
        path, _, is_directory, _ = entries[self.worktree_cursor]
        if is_directory:
            if path in self.worktree_expanded:
                self.worktree_expanded.discard(path)
                self.worktree_selected_dir = os.path.dirname(path)
            else:
                self.worktree_expanded.add(path)
                self.worktree_selected_dir = path
            return
        existing_tab = self._find_tab_for_path(path)
        if existing_tab is not None:
            self._switch_to_tab(existing_tab)
        elif (
            self.file_name is None
            and self.lines == [""]
            and not self.modified
        ):
            self._load_file(path)
        else:
            self._open_in_new_tab(path)
        self._release_worktree_focus()

    def _worktree_create(self, is_directory):
        label = "New directory name" if is_directory else "New file name"
        self.status = f"{label}:"
        self._render()
        name = self._read_command_line(label)
        if not name:
            self.status = "Cancelled"
            return
        new_path = os.path.join(self.worktree_selected_dir, name)
        try:
            if is_directory:
                os.mkdir(new_path)
            else:
                open(new_path, "x", encoding="utf-8").close()
        except OSError as error:
            self.status = f"Could not create '{name}': {error}"
            return
        self.status = f"Created {new_path}"

    def _worktree_delete(self, entries):
        if not entries:
            return
        path, name, is_directory, _ = entries[self.worktree_cursor]
        kind = "folder" if is_directory else "file"
        if not self._confirm(f"Delete {kind} '{name}'? (y/n)"):
            return
        try:
            if is_directory:
                shutil.rmtree(path)
                self.worktree_expanded.discard(path)
            else:
                os.remove(path)
        except OSError as error:
            self.status = f"Could not delete '{name}': {error}"
            return
        if self.file_name == path:
            self.status = f"Deleted {path} (still open here, unsaved)"
        else:
            self.status = f"Deleted {path}"
        self.worktree_cursor = max(0, self.worktree_cursor - 1)

    @staticmethod
    def _pad_sidebar(text):
        return text[:WORKTREE_WIDTH].ljust(WORKTREE_WIDTH)

    def _worktree_body_lines(self, height):
        entries = self._worktree_entries()
        self.worktree_cursor = max(
            0, min(self.worktree_cursor, len(entries) - 1)
        )
        list_height = max(1, height - 1)
        if self.worktree_cursor < self.worktree_scroll:
            self.worktree_scroll = self.worktree_cursor
        elif self.worktree_cursor >= self.worktree_scroll + list_height:
            self.worktree_scroll = self.worktree_cursor - list_height + 1
        root_label = os.path.basename(
            self.worktree_root.rstrip(os.sep)
        ) or self.worktree_root
        lines = [self._pad_sidebar(f"Worktree: {root_label}")]
        last_visible = min(len(entries), self.worktree_scroll + list_height)
        for index in range(self.worktree_scroll, last_visible):
            path, name, is_directory, depth = entries[index]
            indent = "  " * depth
            if is_directory:
                marker = "v " if path in self.worktree_expanded else "> "
                label = f"{marker}{name}/"
            else:
                label = f"  {name}"
            plain_row = self._pad_sidebar(f"{indent}{label}")
            if index == self.worktree_cursor:
                lines.append(
                    f"{theme.CURRENT_LINE_INDICATOR_COLOR}{plain_row}"
                    f"{theme.COLOR_RESET}"
                )
            else:
                lines.append(plain_row)
        while len(lines) < height:
            lines.append(self._pad_sidebar(""))
        return lines[:height]

    @staticmethod
    def _parse_command(command):
        match = re.match(r"^([a-zA-Z]+)\s*(\d+)?$", command)
        if not match:
            return command, None
        name = match.group(1)
        argument = int(match.group(2)) if match.group(2) else None
        return name, argument

    def _line_index_from_argument(self, argument):
        if argument is None or not 1 <= argument <= len(self.lines):
            return None
        return argument - 1

    def _jump_to_line(self, argument):
        line_index = self._line_index_from_argument(argument)
        if line_index is None:
            self.status = f"No line {argument}"
            return
        self.line = line_index
        self.column = min(self.column, len(self.lines[self.line]))
        self.selection_anchor = None
        self.status = f"Jumped to line {argument}"

    def _delete_line(self, argument):
        line_index = self._line_index_from_argument(argument)
        if line_index is None:
            self.status = f"No line {argument}"
            return
        self._snapshot()
        del self.lines[line_index]
        if not self.lines:
            self.lines = [""]
        self.line = min(self.line, len(self.lines) - 1)
        self.column = min(self.column, len(self.lines[self.line]))
        self.selection_anchor = None
        self.status = f"Deleted line {argument}"

    def _copy_selection_or_line(self):
        selected = self._selected_text()
        if selected is not None:
            self.clipboard = selected
            self.status = "Copied selection"
        else:
            self.clipboard = self.lines[self.line]
            self.status = f"Copied line {self.line + 1}"

    def _copy_line(self, argument):
        line_index = self._line_index_from_argument(argument)
        if line_index is None:
            self.status = f"No line {argument}"
            return
        self.clipboard = self.lines[line_index]
        self.status = f"Copied line {argument}"

    def _paste_at_cursor(self):
        if self.clipboard is None:
            self.status = "Nothing to paste"
            return
        self._delete_selection()
        self._paste(self.clipboard)
        self.status = "Pasted"

    def _paste_before_line(self, argument):
        if self.clipboard is None:
            self.status = "Nothing to paste"
            return
        line_index = self._line_index_from_argument(argument)
        if line_index is None:
            self.status = f"No line {argument}"
            return
        self._snapshot()
        new_lines = self.clipboard.split("\n")
        self.lines[line_index:line_index] = new_lines
        self.line = line_index
        self.column = 0
        self.selection_anchor = None
        self.status = f"Pasted before line {argument}"

    def _find_next(self, query, from_current):
        needle = query.lower()
        total_lines = len(self.lines)
        start_line = self.line
        start_column = self.column if from_current else self.column + 1
        for offset in range(total_lines + 1):
            line_index = (start_line + offset) % total_lines
            text = self.lines[line_index].lower()
            if offset == 0:
                found_at = text.find(needle, start_column)
            elif offset == total_lines:
                found_at = text.find(needle, 0, start_column)
            else:
                found_at = text.find(needle, 0)
            if found_at != -1:
                self.line = line_index
                self.column = found_at
                self.selection_anchor = None
                self.status = f"Found '{query}'"
                return
        self.status = f"'{query}' not found"

    def _execute_search(self):
        query = self.search_query
        self.search_query = None
        self.mode = "visual"
        if not query:
            return
        self.last_search = query
        self._find_next(query, from_current=False)

    def _execute_command(self):
        command = self.command
        self.command = None
        self.mode = "visual"
        if command == "f" or command.startswith("f "):
            query = command[1:].strip()
            if query:
                self.last_search = query
                self._find_next(query, from_current=False)
            else:
                self.status = "Usage: :f <text>"
            return
        if command in ("s!", "x!", "sx!", "xs!"):
            self._execute_forced_command(command[:-1])
            return
        name, argument = self._parse_command(command)
        if name == "s" and argument is None:
            self._save()
        elif name == "x" and argument is None:
            prompt = (
                "Save changes before closing this tab? (y/n)"
                if len(self.tabs) > 1 else
                "Save changes before exiting? (y/n)"
            )
            if not self.modified:
                self._close_current_tab()
            elif self._confirm(prompt):
                if self._save():
                    self._close_current_tab()
            else:
                self._close_current_tab()
        elif name == "u" and argument is None:
            self._undo()
        elif name == "r" and argument is None:
            self._redo()
        elif name in ("sx", "xs") and argument is None:
            if self._save():
                self._close_current_tab()
        elif name == "l" and argument is not None:
            self._jump_to_line(argument)
        elif name == "d" and argument is None:
            if self._delete_selection():
                self.status = "Deleted selection"
            else:
                self.status = "Nothing selected"
        elif name == "d" and argument is not None:
            self._delete_line(argument)
        elif name == "c" and argument is None:
            self._copy_selection_or_line()
        elif name == "cl" and argument is not None:
            self._copy_line(argument)
        elif name == "v" and argument is None:
            self._paste_at_cursor()
        elif name == "vl" and argument is not None:
            self._paste_before_line(argument)
        elif name == "w" and argument is None:
            self.worktree_visible = not self.worktree_visible
            if not self.worktree_visible:
                self.worktree_focused = False
            self.worktree_visible_because_of_focus = False
        elif name == "help" and argument is None:
            self.help_mode = True
        else:
            self.status = f"Unknown command: :{command}"

    def run(self):
        read_fd, write_fd = _enable_resize_wakeup()
        previous_handler = signal.signal(signal.SIGWINCH, _handle_resize)
        previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
        previous_sigquit = signal.signal(signal.SIGQUIT, signal.SIG_IGN)
        try:
            with raw_terminal():
                while self.running:
                    self._render()
                    key = read_key()
                    if key == "RESIZE":
                        continue
                    if key == "EOF":
                        break
                    if key == "\x03":
                        continue
                    if key == "\x04" and not self.worktree_focused:
                        continue
                    if self.help_mode:
                        if key == "q":
                            self.help_mode = False
                        continue
                    if self.worktree_focused:
                        entries = self._worktree_entries()
                        if key == "UP":
                            self.worktree_cursor = max(
                                0, self.worktree_cursor - 1
                            )
                        elif key == "DOWN":
                            self.worktree_cursor = min(
                                len(entries) - 1, self.worktree_cursor + 1
                            )
                        elif key in ("\r", "\n"):
                            self._worktree_activate(entries)
                        elif key == "\x06":
                            self._worktree_create(is_directory=False)
                        elif key == "\x04":
                            self._worktree_create(is_directory=True)
                        elif key == "DELETE":
                            self._worktree_delete(entries)
                        elif key in ("v", ESC):
                            self._release_worktree_focus()
                        elif key == ":":
                            self._release_worktree_focus()
                            self.mode = "command"
                            self.command = ""
                        elif key == "i":
                            self._release_worktree_focus()
                            self.mode = "insert"
                        continue
                    if self.command is not None:
                        if key in ("\r", "\n"):
                            self._execute_command()
                        elif key in ("\x7f", "\b"):
                            self.command = self.command[:-1]
                        elif key == ESC:
                            self.command = None
                            self.mode = "visual"
                            self.help_pending = True
                        elif len(key) == 1 and key.isprintable():
                            self.command += key
                        continue
                    if self.search_query is not None:
                        if key in ("\r", "\n"):
                            self._execute_search()
                        elif key in ("\x7f", "\b"):
                            self.search_query = self.search_query[:-1]
                        elif key == ESC:
                            self.search_query = None
                            self.mode = "visual"
                            self.help_pending = True
                        elif len(key) == 1 and key.isprintable():
                            self.search_query += key
                        continue

                    if self.help_pending:
                        self.help_pending = False
                        if key == "h":
                            self.help_mode = True
                            continue

                    if self.mode == "visual" and key in ASDF_TO_ARROW:
                        key = ASDF_TO_ARROW[key]
                    if self.mode == "visual" and key.isdigit():
                        self.pending_count += key
                        continue
                    if self.mode == "visual" and key not in MOVEMENT_KEYS:
                        self.pending_count = ""

                    if key == ESC:
                        self.mode = "visual"
                        self.command = None
                        self.help_pending = True
                        self.selection_anchor = None
                    elif self.mode == "visual" and key == ":":
                        self.mode = "command"
                        self.command = ""
                    elif self.mode == "visual" and key == "/":
                        self.mode = "search"
                        self.search_query = ""
                    elif self.mode == "visual" and key == "w":
                        if not self.worktree_visible:
                            self.worktree_visible = True
                            self.worktree_visible_because_of_focus = True
                        self.worktree_focused = True
                    elif (
                        self.mode == "visual"
                        and key == "\t"
                        and len(self.tabs) > 1
                    ):
                        self._switch_to_tab(
                            (self.active_tab + 1) % len(self.tabs)
                        )
                    elif self.mode == "visual" and key == "i":
                        self.mode = "insert"
                        self.selection_anchor = None
                    elif (
                        self.mode == "visual"
                        and key == "n"
                        and self.last_search
                    ):
                        self._find_next(self.last_search, from_current=False)
                    elif key == "\x1a":
                        self._undo()
                    elif key == "\x19":
                        self._redo()
                    elif key in ("UP", "CTRL-UP"):
                        self._update_selection(key)
                        self._move_vertical(-self._consume_count())
                    elif key in ("DOWN", "CTRL-DOWN"):
                        self._update_selection(key)
                        self._move_vertical(self._consume_count())
                    elif key in ("LEFT", "CTRL-LEFT"):
                        self._update_selection(key)
                        self._move_horizontal(-self._consume_count())
                    elif key in ("RIGHT", "CTRL-RIGHT"):
                        self._update_selection(key)
                        self._move_horizontal(self._consume_count())
                    elif self.mode == "insert" and key in ("\r", "\n"):
                        self._new_line()
                    elif self.mode == "insert" and key in ("\x7f", "\b"):
                        self._backspace()
                    elif self.mode == "insert" and key == "DELETE":
                        self._delete_forward()
                    elif self.mode == "insert" and key == "\t":
                        suggestion = self._suggestion()
                        if suggestion:
                            self._accept_suggestion(suggestion)
                        else:
                            self._insert(key)
                    elif (
                        self.mode == "insert"
                        and len(key) == 1
                        and key.isprintable()
                    ):
                        self._insert(key)
        finally:
            signal.signal(signal.SIGWINCH, previous_handler)
            signal.signal(signal.SIGINT, previous_sigint)
            signal.signal(signal.SIGQUIT, previous_sigquit)
            _disable_resize_wakeup(read_fd, write_fd)


def edit_file(file_name=None, worktree_root=None):
    editor = TextEditor(file_name)
    if worktree_root is not None:
        editor.worktree_root = os.path.abspath(worktree_root)
        editor.worktree_selected_dir = editor.worktree_root
        editor.worktree_visible = True
        editor.worktree_focused = True
    editor.run()
