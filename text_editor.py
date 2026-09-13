import ast
import builtins
import keyword
import os
import pty
import re
import select
import shlex
import shutil
import signal
import subprocess
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
HJKL_TO_ARROW = {"h": "LEFT", "j": "DOWN", "k": "UP", "l": "RIGHT"}
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
_CLASS_INTROSPECTION_SCRIPT = (
    "import sys, importlib\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "module = importlib.import_module(sys.argv[2])\n"
    "obj = getattr(module, sys.argv[3])\n"
    "names = [\n"
    "    n for n in dir(obj)\n"
    "    if not (n.startswith('__') and n.endswith('__'))\n"
    "]\n"
    "print('\\n'.join(names))\n"
)
MODULE_VOCABULARY = sorted(
    name for name in sys.stdlib_module_names if not name.startswith("_")
)
IMPORT_CONTEXT_PATTERN = re.compile(r"^\s*(?:from|import)\s+$")
FROM_IMPORT_NAMES_PATTERN = re.compile(
    r"^\s*from\s+(\S+)\s+import\s+"
    r"(?:[A-Za-z_][A-Za-z0-9_]*(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*,\s*)*$"
)
FROM_IMPORT_LINE_PATTERN = re.compile(r"^\s*from\s+(\S+)\s+import\s+(.+)$")
MAX_SUGGESTION_DROPDOWN_ITEMS = 8
_MODULE_INTROSPECTION_SCRIPT = (
    "import sys, importlib\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "module = importlib.import_module(sys.argv[2])\n"
    "names = [\n"
    "    n for n in dir(module)\n"
    "    if not (n.startswith('__') and n.endswith('__'))\n"
    "]\n"
    "print('\\n'.join(names))\n"
)

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


def _is_inside_string_or_comment(line, column):
    """Whether `column` sits inside a string literal or a comment,
    scanning from the start of `line` - so an unterminated string
    being typed still counts, even though it has no closing quote
    yet for a regex to match against."""
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


def _introspect_module_members(directory, module_name):
    """Names `from module_name import <TAB>` could offer, found by
    actually importing the module in a throwaway subprocess (with
    `directory` on its sys.path, so local project files resolve too).

    A subprocess - not an in-process import - because this runs
    whatever top-level code the module has, including local files
    still being edited; a timeout and total isolation from Mini itself
    keep a slow or broken module from freezing the editor."""
    try:
        result = subprocess.run(
            [
                sys.executable, "-c", _MODULE_INTROSPECTION_SCRIPT,
                directory, module_name,
            ],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()
    if result.returncode != 0:
        return set()
    return set(result.stdout.split())


def _introspect_class_members(directory, module_name, class_name):
    """Like `_introspect_module_members`, but for one class imported
    from a module (`from module_name import ClassName`), so `thing.`
    can offer that class's own methods instead of every builtin type's
    methods mixed together."""
    try:
        result = subprocess.run(
            [
                sys.executable, "-c", _CLASS_INTROSPECTION_SCRIPT,
                directory, module_name, class_name,
            ],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()
    if result.returncode != 0:
        return set()
    return set(result.stdout.split())


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


def _reset_child_signals():
    # Mini ignores SIGINT/SIGQUIT for itself so Ctrl+C can't kill the
    # editor; that disposition is otherwise inherited across fork+exec,
    # which would make a :run child ignore them too. Reset both to the
    # default before exec so the child (and our SIGINT forwarding) work
    # normally.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGQUIT, signal.SIG_DFL)


_RUN_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _sanitize_run_output(text):
    def keep_only_colors(match):
        return match.group() if match.group().endswith("m") else ""

    text = _RUN_ANSI_PATTERN.sub(keep_only_colors, text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


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
_run_output_fd = None


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
    if _pending_byte is None and _run_output_fd is not None:
        watch_fds.append(_run_output_fd)
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
        if _run_output_fd is not None and _run_output_fd in ready:
            return "RUN_OUTPUT"

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
    if final == "Z":
        return "SHIFT-TAB"
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
        self.viewport_top = 0
        self.selection_anchor = None
        self.clipboard = None
        self.pending_count = ""
        self.count_locked = False
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
        self.run_process = None
        self.run_master_fd = None
        self.run_output_lines = []
        self.run_pending_text = ""
        self.run_focused = False
        self.suggestion_matches = []
        self.suggestion_index = 0
        self._suggestion_dismissed_at = None
        self._import_members_cache = {}

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
        self.count_locked = False

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
        total_lines = len(self.lines)
        for line_index in range(self.line, total_lines):
            text = self.lines[line_index]
            start_column = (
                self.column + 1 if line_index == self.line else 0
            )
            for column_index in range(start_column, len(text)):
                if text[column_index] == quote_character:
                    return (line_index, column_index)
        for line_index in range(self.line, -1, -1):
            text = self.lines[line_index]
            end_column = (
                self.column - 1 if line_index == self.line
                else len(text) - 1
            )
            for column_index in range(end_column, -1, -1):
                if text[column_index] == quote_character:
                    return (line_index, column_index)
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
            "  :help    Show this help\r\n",
            "  :config  Open ~/.minirc as a tab\r\n",
            "  i        Enter Insert mode\r\n",
            "  Tab      Accept suggestion (Insert mode); with 2+\r\n",
            "           matches, Up/Down/Enter also navigate/accept\r\n",
            "  Ctrl+Arrows  Select text (Visual mode)\r\n",
            "  w        Show and focus the worktree panel (Visual mode)\r\n",
            "  :w       Toggle the worktree panel's visibility\r\n",
            "  :run     Run this .py file, output shown below the code\r\n",
            "           (Ctrl+C interrupts it, Esc unfocuses/closes it,\r\n",
            "           typing sends input to it)\r\n",
            "  :lint    Run flake8 + mypy on this file, same output\r\n",
            "           panel as :run; deletes .mypy_cache afterward\r\n",
            "  Worktree: Up/Down or j/k move, l expands a directory,\r\n",
            "    h collapses it, Enter opens a file as a tab\r\n",
            "    (or switches to it if already open) or\r\n",
            "    expands/collapses a directory. Ctrl+F new file,\r\n",
            "    Ctrl+D new folder, Del deletes, v/Esc return focus,\r\n",
            "    : or i jump to Command/Insert\r\n",
            "  Tab      Switch to the next tab (Visual mode)\r\n",
            "  Shift+Tab  Switch to the previous tab (Visual mode)\r\n",
            "  h j k l  Move left/down/up/right (Visual mode)\r\n",
            "  <n> then a move   Repeat that move n times (Visual)\r\n",
            "  :l <n>   Jump to line n\r\n",
            "  :b       Jump to the beginning of the file\r\n",
            "  :e       Jump to the end of the file\r\n",
            "  :a       Jump to the start of the current line\r\n",
            "  :f       Jump to the end of the current line\r\n",
            "  :d       Delete selection\r\n",
            "  :d <n>   Delete line n\r\n",
            "  :c       Copy selection, or the current line if none\r\n",
            "  :cl <n>  Copy line n\r\n",
            "  :v       Paste at the cursor\r\n",
            "  :vl <n>  Paste as a new line before line n\r\n",
            "  :u / Ctrl+Z  Undo\r\n",
            "  :r / Ctrl+Y  Redo\r\n",
            "  /text     Search\r\n",
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
        run_visible = (
            self.run_process is not None or bool(self.run_output_lines)
            or bool(self.run_pending_text)
        )
        run_display_lines = self.run_output_lines
        if self.run_pending_text:
            run_display_lines = run_display_lines + [self.run_pending_text]
        if run_visible:
            run_rows = max(3, visible_rows // 2)
            editor_rows = max(1, visible_rows - run_rows - 1)
        else:
            run_rows = 0
            editor_rows = visible_rows
        self._ensure_cursor_visible(editor_rows)
        last_visible_line = min(
            len(self.lines), self.viewport_top + editor_rows
        )
        selection_bounds = self._selection_bounds()
        self._refresh_suggestion_matches()
        suggestion = self._ghost_suggestion()
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

        if sidebar_visible:
            separator = f"{theme.LINE_NUMBER_COLOR}|{theme.COLOR_RESET} "
            tab_bar_row = f"{self._pad_sidebar('')}{separator}{tab_bar}"
        else:
            tab_bar_row = tab_bar
        output = [
            "\x1b[2J\x1b[H", theme.BASE_STYLE,
            f"{tab_bar_row}\r\n",
        ]
        ruler_overlay = []
        for row_offset in range(visible_rows):
            if run_visible and row_offset == editor_rows:
                status_word = (
                    "running" if self.run_process is not None else "finished"
                )
                divider_text = f" Output ({status_word}) "
                divider_width = max(
                    len(divider_text), terminal_width - editor_col_offset
                )
                editor_row = (
                    f"{theme.LINE_NUMBER_COLOR}{divider_text}"
                    f"{'-' * (divider_width - len(divider_text))}"
                    f"{theme.COLOR_RESET}"
                )
            elif run_visible and row_offset > editor_rows:
                run_row_index = row_offset - editor_rows - 1
                output_index = (
                    len(run_display_lines) - run_rows + run_row_index
                )
                if 0 <= output_index < len(run_display_lines):
                    editor_row = (
                        run_display_lines[output_index] + theme.BASE_STYLE
                    )
                else:
                    editor_row = ""
            elif (
                index := self.viewport_top + row_offset
            ) < last_visible_line:
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
                display_length = len(self._display_text(text))
                if display_length > theme.MAX_COLS:
                    error_column = editor_col_offset + 1
                    ruler_overlay.append(
                        f"\x1b[{2 + row_offset};{error_column}H"
                        f"{theme.LINE_LENGTH_ERROR_COLOR}●"
                        f"{theme.BASE_STYLE}"
                    )
                else:
                    ruler_column = (
                        editor_col_offset + gutter_width + 1
                        + theme.MAX_COLS
                    )
                    if ruler_column <= terminal_width:
                        ruler_overlay.append(
                            f"\x1b[{2 + row_offset};{ruler_column}H"
                            f"{theme.RULER_COLOR}│{theme.BASE_STYLE}"
                        )
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

        output.extend(ruler_overlay)
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
        elif self.run_focused:
            cursor_row = 2 + editor_rows + run_rows
            cursor_column = (
                editor_col_offset + len(self.run_pending_text) + 1
            )
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
        if (
            self.mode == "insert"
            and self.command is None
            and self.search_query is None
            and not self.worktree_focused
            and not self.run_focused
        ):
            output.extend(self._suggestion_dropdown_output(
                cursor_row, cursor_column, terminal_width, terminal_height
            ))
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
        self.count_locked = True
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

    def _module_member_names(self, module_name):
        directory = (
            os.path.dirname(self.file_name) if self.file_name else ""
        ) or os.getcwd()
        cache_key = (directory, module_name)
        if cache_key not in self._import_members_cache:
            self._import_members_cache[cache_key] = (
                _introspect_module_members(directory, module_name)
            )
        return self._import_members_cache[cache_key]

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

    def _infer_attribute_pool(self, name):
        """Names to offer for `name.<TAB>`, narrowed to name's actual
        type/class when it can be worked out from the buffer - or
        None to fall back to the generic mixed-type vocabulary."""
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
        directory = (
            os.path.dirname(self.file_name) if self.file_name else ""
        ) or os.getcwd()
        cache_key = (directory, module_name, original_name)
        if cache_key not in self._import_members_cache:
            self._import_members_cache[cache_key] = (
                _introspect_class_members(
                    directory, module_name, original_name
                )
            )
        return self._import_members_cache[cache_key]

    def _suggestion_pools(self, prefix_start, line):
        context_before = line[:prefix_start]
        from_import_match = FROM_IMPORT_NAMES_PATTERN.match(context_before)
        if from_import_match:
            already_imported = _parse_imported_names(context_before)
            members = self._module_member_names(
                from_import_match.group(1)
            ) - already_imported
            return (members,)
        if IMPORT_CONTEXT_PATTERN.match(context_before):
            return (
                self._local_module_names(),
                MODULE_VOCABULARY,
                self._collect_buffer_words(),
            )
        return (self._collect_buffer_words(), PYTHON_VOCABULARY)

    def _compute_suggestion_matches(self):
        if self.mode != "insert" or not self._is_python_file():
            return []
        line = self.lines[self.line]
        if _is_inside_string_or_comment(line, self.column):
            return []
        if self.column < len(line) and _is_word_char(line[self.column]):
            return []
        prefix = self._current_word_prefix()
        prefix_start = self.column - len(prefix)
        is_attribute = (
            prefix_start > 0 and line[prefix_start - 1] == "."
        )
        if is_attribute:
            name = self._preceding_identifier(prefix_start - 1)
            inferred = self._infer_attribute_pool(name) if name else None
            if inferred is not None:
                # The type/class is known, so "." alone (an empty
                # prefix) already starts the suggestion - no need to
                # type anything first.
                pools = (inferred,)
            elif len(prefix) < MIN_SUGGESTION_PREFIX:
                return []
            else:
                pools = (self._collect_buffer_words(), ATTRIBUTE_VOCABULARY)
        else:
            if len(prefix) < MIN_SUGGESTION_PREFIX:
                return []
            pools = self._suggestion_pools(prefix_start, line)
        for pool in pools:
            matches = sorted(
                (
                    word for word in pool
                    if word != prefix and word.startswith(prefix)
                ),
                key=len,
            )
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

    def _ghost_suggestion(self):
        if len(self.suggestion_matches) != 1:
            return ""
        prefix = self._current_word_prefix()
        return self.suggestion_matches[0][len(prefix):]

    def _suggestion_dropdown_output(
        self, cursor_row, cursor_column, terminal_width, terminal_height
    ):
        items = self.suggestion_matches[:MAX_SUGGESTION_DROPDOWN_ITEMS]
        if len(items) < 2:
            return []
        prefix_length = len(self._current_word_prefix())
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

    def _accept_highlighted_suggestion(self):
        prefix = self._current_word_prefix()
        word = self.suggestion_matches[self.suggestion_index]
        self._accept_suggestion(word[len(prefix):])
        self.suggestion_matches = []
        self.suggestion_index = 0

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
        closing_character = ""
        if character in PAIRS:
            next_character = (
                current_line[self.column]
                if self.column < len(current_line) else ""
            )
            gap_is_free = next_character == "" or next_character.isspace()
            next_is_closing = next_character in PAIRS.values()
            if gap_is_free or next_is_closing:
                closing_character = PAIRS[character]
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
        between_brackets = (
            before and before[-1] in BRACKET_PAIRS
            and after and after[0] == BRACKET_PAIRS[before[-1]]
        )
        if between_brackets:
            inner_indent = indent + "\t"
            self.lines[self.line] = before
            self.lines.insert(self.line + 1, inner_indent)
            self.lines.insert(self.line + 2, indent + after)
            self.line += 1
            self.column = len(inner_indent)
            return
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
        self.count_locked = False
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

    def _start_process(self, command, label):
        """Runs `command` in a pty, streaming its output live into the
        same panel `:run`/`:terminal` uses - shared by `:lint` too, so
        both get live output, Ctrl+C, and Esc-to-close for free."""
        global _run_output_fd
        if self.run_process is not None and self.run_process.poll() is None:
            self.run_focused = True
            self.status = "A run is already in progress"
            return
        if self.modified or self.file_name is None:
            if not self._save():
                return
        master_fd, slave_fd = pty.openpty()
        try:
            process = subprocess.Popen(
                command,
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                cwd=os.path.dirname(self.file_name) or ".",
                close_fds=True,
                preexec_fn=_reset_child_signals,
            )
        except OSError as error:
            os.close(master_fd)
            os.close(slave_fd)
            self.status = f"Could not run: {error}"
            return
        os.close(slave_fd)
        self.run_process = process
        self.run_master_fd = master_fd
        self.run_output_lines = [f"$ {label}"]
        self.run_pending_text = ""
        self.run_focused = True
        _run_output_fd = master_fd

    def _start_run(self):
        if not self._is_python_file():
            self.status = "Can only run .py files"
            return
        self._start_process(
            [sys.executable, os.path.basename(self.file_name)],
            f"python3 {self.file_name}",
        )

    def _start_lint(self):
        if not self._is_python_file():
            self.status = "Can only lint .py files"
            return
        name = shlex.quote(os.path.basename(self.file_name))
        shell_command = f"flake8 {name}; mypy {name}; rm -rf .mypy_cache"
        self._start_process(["sh", "-c", shell_command], "lint")

    def _pump_run_output(self):
        try:
            data = os.read(self.run_master_fd, 4096)
        except OSError:
            data = b""
        if not data:
            self._finish_run()
            return
        text = self.run_pending_text + _sanitize_run_output(
            data.decode("utf-8", errors="replace")
        )
        *complete_lines, self.run_pending_text = text.split("\n")
        self.run_output_lines.extend(complete_lines)
        max_lines = 2000
        if len(self.run_output_lines) > max_lines:
            self.run_output_lines = self.run_output_lines[-max_lines:]

    def _finish_run(self):
        global _run_output_fd
        exit_code = None
        if self.run_process is not None:
            exit_code = self.run_process.poll()
            if exit_code is None:
                self.run_process.wait()
                exit_code = self.run_process.returncode
        if self.run_master_fd is not None:
            try:
                os.close(self.run_master_fd)
            except OSError:
                pass
        _run_output_fd = None
        self.run_process = None
        self.run_master_fd = None
        if self.run_pending_text:
            self.run_output_lines.append(self.run_pending_text)
            self.run_pending_text = ""
        self.run_output_lines.append("")
        self.run_output_lines.append(
            f"[Process finished with exit code {exit_code}]"
        )
        self.run_output_lines.append("(Press Esc to close)")

    def _stop_run(self):
        if self.run_process is not None and self.run_process.poll() is None:
            self.run_focused = False
            return
        if self.run_process is not None:
            self._finish_run()
        self.run_process = None
        self.run_master_fd = None
        self.run_output_lines = []
        self.run_pending_text = ""
        self.run_focused = False

    def _find_tab_for_path(self, path):
        for index, state in enumerate(self.tabs):
            file_name = (
                self.file_name if index == self.active_tab
                else state["file_name"]
            )
            if file_name == path:
                return index
        return None

    def _open_config_file(self):
        path = theme.RC_PATH
        existing_tab = self._find_tab_for_path(path)
        is_blank = self.lines == [""] and not self.modified
        if existing_tab is not None:
            self._switch_to_tab(existing_tab)
        elif self.file_name is None and is_blank:
            self._load_file(path)
        else:
            self._open_in_new_tab(path)

    def _worktree_expand(self, entries):
        if not entries:
            return
        path, _, is_directory, _ = entries[self.worktree_cursor]
        if is_directory and path not in self.worktree_expanded:
            self.worktree_expanded.add(path)
            self.worktree_selected_dir = path

    def _worktree_collapse(self, entries):
        if not entries:
            return
        path, _, is_directory, _ = entries[self.worktree_cursor]
        if is_directory and path in self.worktree_expanded:
            self.worktree_expanded.discard(path)
            self.worktree_selected_dir = os.path.dirname(path)

    def _worktree_activate(self, entries):
        if not entries:
            return
        path, _, is_directory, _ = entries[self.worktree_cursor]
        if is_directory:
            if path in self.worktree_expanded:
                self._worktree_collapse(entries)
            else:
                self._worktree_expand(entries)
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
        elif name == "b" and argument is None:
            self.line = 0
            self.column = 0
            self.selection_anchor = None
            self.status = "Beginning of file"
        elif name == "e" and argument is None:
            self.line = len(self.lines) - 1
            self.column = 0
            self.selection_anchor = None
            self.status = "End of file"
        elif name == "a" and argument is None:
            self.column = 0
            self.selection_anchor = None
        elif name == "f" and argument is None:
            self.column = len(self.lines[self.line])
            self.selection_anchor = None
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
        elif name in ("run", "terminal") and argument is None:
            self._start_run()
        elif name == "lint" and argument is None:
            self._start_lint()
        elif name == "help" and argument is None:
            self.help_mode = True
        elif name == "config" and argument is None:
            self._open_config_file()
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
                    if key == "RUN_OUTPUT":
                        self._pump_run_output()
                        continue
                    if key == "\x03" and not self.run_focused:
                        continue
                    if key == "\x04" and not self.worktree_focused:
                        continue
                    if self.help_mode:
                        if key == "q":
                            self.help_mode = False
                        continue
                    if self.run_focused:
                        if key == "\x03":
                            if self.run_process is not None:
                                self.run_process.send_signal(signal.SIGINT)
                        elif key == ESC:
                            self._stop_run()
                        elif self.run_master_fd is not None:
                            if key in ("\r", "\n"):
                                os.write(self.run_master_fd, b"\n")
                            elif key in ("\x7f", "\b"):
                                os.write(self.run_master_fd, b"\x7f")
                            elif len(key) == 1 and key.isprintable():
                                os.write(
                                    self.run_master_fd, key.encode("utf-8")
                                )
                        continue
                    if self.worktree_focused:
                        entries = self._worktree_entries()
                        if key in ("UP", "k"):
                            self.worktree_cursor = max(
                                0, self.worktree_cursor - 1
                            )
                        elif key in ("DOWN", "j"):
                            self.worktree_cursor = min(
                                len(entries) - 1, self.worktree_cursor + 1
                            )
                        elif key == "l":
                            self._worktree_expand(entries)
                        elif key == "h":
                            self._worktree_collapse(entries)
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
                        elif len(key) == 1 and key.isprintable():
                            self.search_query += key
                        continue

                    if self.mode == "visual" and key in HJKL_TO_ARROW:
                        key = HJKL_TO_ARROW[key]
                    if self.mode == "visual" and key.isdigit():
                        if self.count_locked:
                            self.pending_count = key
                            self.count_locked = False
                        else:
                            self.pending_count += key
                        continue
                    if self.mode == "visual" and key not in MOVEMENT_KEYS:
                        self.pending_count = ""
                        self.count_locked = False

                    dropdown_open = (
                        self.mode == "insert"
                        and len(self.suggestion_matches) >= 2
                    )
                    if dropdown_open and key == "UP":
                        self.suggestion_index = (
                            self.suggestion_index - 1
                        ) % len(self.suggestion_matches)
                    elif dropdown_open and key == "DOWN":
                        self.suggestion_index = (
                            self.suggestion_index + 1
                        ) % len(self.suggestion_matches)
                    elif dropdown_open and key in ("\t", "\r", "\n"):
                        self._accept_highlighted_suggestion()
                    elif dropdown_open and key == ESC:
                        self.suggestion_matches = []
                        self._suggestion_dismissed_at = (
                            self.line, self.column
                        )
                    elif key == ESC:
                        self.mode = "visual"
                        self.command = None
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
                    elif (
                        self.mode == "visual"
                        and key == "SHIFT-TAB"
                        and len(self.tabs) > 1
                    ):
                        self._switch_to_tab(
                            (self.active_tab - 1) % len(self.tabs)
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
                        if self.suggestion_matches:
                            self._accept_highlighted_suggestion()
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
