"""Multi-tab buffer lifecycle: each open file's own undo history,
cursor position, and unsaved-changes state, switching between them,
and reading files from disk."""

import os

from collections import deque

import theme

from editing import UNDO_HISTORY_LIMIT


class TabsMixin:
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
            "undo_stack": deque(maxlen=UNDO_HISTORY_LIMIT),
            "redo_stack": deque(maxlen=UNDO_HISTORY_LIMIT), "modified": False,
        }

    def _is_blank_buffer(self):
        """Whether the active tab is the one blank/unnamed/unmodified
        "MiniText" placeholder - never a real file, whether freshly
        started with no file argument or reached by closing the last
        real tab (see `_close_current_tab`). Used to keep it a plain
        landing screen: no typing into it (see text_editor.py's own
        `i`-key handling) and no line-number gutter (see rendering.py's
        `render`), on top of it already being the one tab that shows
        "MiniText" with no closing × and offers the "Close Mini"
        button instead of a real close."""
        return (
            self.file_name is None and self.lines == [""]
            and not self.modified
        )

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

    def _open_update_notice_tab(self):
        """Opens a new, unnamed tab announcing that an update was
        found by the background watcher (see updater.py) while this
        session was already running - `mini --update`'s own startup
        check shows a banner instead, since there's no editor open
        yet at that point to give it a tab."""
        self._sync_active_tab()
        new_state = self._blank_buffer_state()
        new_state["lines"] = [
            "A new version of Mini is available.",
            "",
            "Run 'mini --update' from a shell to install it.",
            "",
            "(This is just a notice, not a file - close it with :q.)",
        ]
        self.tabs.append(new_state)
        self.active_tab = len(self.tabs) - 1
        self._apply_buffer_state(self.tabs[self.active_tab])
        self.status = "A new version of Mini is available"

    def _close_current_tab(self):
        """Closing the last tab no longer exits Mini outright - it
        resets that tab to a blank, unnamed buffer instead, the same
        state a freshly started `mini` with no file argument opens
        in. Only closing a tab that's *already* in that state (nothing
        left to lose) actually exits - so `:q` (or the tab-bar × or
        the "Close Mini" button, once already down to a lone blank
        tab) still works exactly as before to quit."""
        if len(self.tabs) <= 1:
            if (
                self.file_name is None and self.lines == [""]
                and not self.modified
            ):
                self.running = False
                return
            self._apply_buffer_state(self._blank_buffer_state())
            self.tabs = [self._current_buffer_state()]
            self.active_tab = 0
            self.selection_anchor = None
            return
        del self.tabs[self.active_tab]
        self.active_tab = min(self.active_tab, len(self.tabs) - 1)
        self._apply_buffer_state(self.tabs[self.active_tab])
        self.selection_anchor = None

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

    def _is_python_file(self):
        return bool(self.file_name) and self.file_name.endswith(".py")

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
        self.undo_stack = deque(maxlen=UNDO_HISTORY_LIMIT)
        self.redo_stack = deque(maxlen=UNDO_HISTORY_LIMIT)
        self.modified = False
        self.viewport_top = 0
        self.status = f"Opened {path}"

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
