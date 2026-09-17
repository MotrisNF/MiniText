"""Mini's TextEditor: composes the mixins in autocomplete.py,
commands.py, editing.py, rendering.py, run_panel.py, tabs.py, and
worktree.py into one class, owns the top-level state they all share
(cursor, buffers, tabs, panels, ...), and runs the main key-reading
loop that routes a keypress to whichever of them handles it."""

import os
import signal
import time
from collections import deque

import terminal
import updater
from autocomplete import SuggestionMixin
from commands import CommandMixin
from editing import (
    BufferEditMixin, STATUS_TIMEOUT_SECONDS, UNDO_HISTORY_LIMIT,
    _indent_unit,
)
from rendering import RenderMixin
from run_panel import RunPanelMixin
from tabs import TabsMixin
from terminal import (
    ESC, _disable_resize_wakeup, _enable_resize_wakeup, _handle_resize,
    raw_terminal, read_key,
)
from worktree import WorktreePanelMixin

HJKL_TO_ARROW = {"h": "LEFT", "j": "DOWN", "k": "UP", "l": "RIGHT"}
MOVEMENT_KEYS = {
    "UP", "DOWN", "LEFT", "RIGHT",
    "CTRL-UP", "CTRL-DOWN", "CTRL-LEFT", "CTRL-RIGHT",
}


class TextEditor(
    TabsMixin, RenderMixin, BufferEditMixin, SuggestionMixin,
    WorktreePanelMixin, RunPanelMixin, CommandMixin,
):
    def __init__(self, file_name=None):
        self.file_name = file_name
        self.lines = self._read_file(file_name)
        self.line = 0
        self.column = 0
        self.mode = "visual"
        self.command = None
        self._cmd_tab_state = None
        self.status = ""
        self.running = True
        self.help_mode = False
        self._help_scroll = 0
        self.move_mode = False
        self.viewport_top = 0
        self.selection_anchor = None
        self.clipboard = None
        self.pending_count = ""
        self.count_locked = False
        self.search_query = None
        self.last_search = None
        self.undo_stack = deque(maxlen=UNDO_HISTORY_LIMIT)
        self.redo_stack = deque(maxlen=UNDO_HISTORY_LIMIT)
        self.modified = False
        self.worktree_visible = False
        self.worktree_focused = False
        self.worktree_visible_because_of_focus = False
        self.worktree_root = os.getcwd()
        self.worktree_expanded = set()
        self.worktree_selected_entries = set()
        self.worktree_show_hidden = False
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
        # None = pinned to the live tail (follows new output, like
        # `tail -f`); otherwise the absolute line index the user
        # scrolled to, which stays put as more output arrives below it.
        self.run_view_start = None
        self._run_rows = 0
        # Differential rendering: only the rows whose own text actually
        # changed since the last frame get re-sent to the terminal -
        # everything that isn't part of any row's own content (a
        # resize, or the suggestion dropdown floating over rows that
        # otherwise wouldn't redraw) forces one full redraw instead,
        # to never leave stale content behind. See rendering.py.
        self._force_full_redraw = True
        self._last_rendered_rows = {}
        self._last_terminal_size = None
        self._dropdown_was_shown = False
        self._overlay_box_was_shown = False
        self.suggestion_matches = []
        self.suggestion_index = 0
        self._suggestion_dismissed_at = None
        self._import_members_cache = {}
        self._import_broken_cache = {}
        self._jedi_attribute_cache = {}
        self._elastic_width_cache = {}
        self._mouse_layout = None
        self._line_word_cache = {}
        self._word_pool_static = frozenset()
        self._word_pool_static_sorted = []
        self._included_header_words_sorted = []
        self._word_pool_lines_ref = None
        self._word_pool_line_count = -1
        self._word_pool_line_index = -1
        self._worktree_entries_cache = None
        self._last_click = None
        self._hovered_worktree_button = None
        self._hovered_tab_close = None
        self._close_mini_hovered = False
        self._hovered_worktree_delete = None
        self._hovered_worktree_row = None
        self._worktree_drag_origin = None
        self._worktree_drag_target = None
        self._name_dialog = None
        self._confirm_dialog = None

    def run(self):
        read_fd, write_fd = _enable_resize_wakeup()
        previous_handler = signal.signal(signal.SIGWINCH, _handle_resize)
        previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
        previous_sigquit = signal.signal(signal.SIGQUIT, signal.SIG_IGN)
        # A session that stays open past updater.CHECK_INTERVAL_SECONDS
        # still gets checked, on the same schedule as the startup
        # check - this is a no-op (returns None) for a dev checkout.
        update_check_fd = updater.start_background_update_watcher()
        if update_check_fd is not None:
            terminal.set_update_check_fd(update_check_fd)
        try:
            with raw_terminal():
                while self.running:
                    self._render()
                    read_timeout = None
                    if self.status and self._status_set_at is not None:
                        read_timeout = max(0.0, STATUS_TIMEOUT_SECONDS - (
                            time.monotonic() - self._status_set_at
                        ))
                    key = read_key(read_timeout)
                    if key == "IDLE_TIMEOUT":
                        self.status = ""
                        continue
                    if key == "RESIZE":
                        self._force_full_redraw = True
                        continue
                    if key == "EOF":
                        break
                    if key == "UPDATE_AVAILABLE":
                        self._open_update_notice_tab()
                        continue
                    if key == "RUN_OUTPUT":
                        self._pump_run_output()
                        continue
                    if key == "MOUSE_IGNORE":
                        continue
                    if key.startswith("MOUSE_"):
                        if not self.help_mode:
                            self._handle_mouse_event(key)
                        continue
                    if key == "\x03" and not self.run_focused:
                        continue
                    if (
                        key == "\x04" and not self.worktree_focused
                        and self.mode != "visual"
                    ):
                        continue
                    if self.help_mode:
                        if key == "q":
                            self.help_mode = False
                            # _render_help() painted the whole screen
                            # itself, bypassing the row cache below -
                            # it's now stale relative to what's
                            # actually on screen.
                            self._force_full_redraw = True
                        elif key in ("UP", "DOWN", "CTRL-UP", "CTRL-DOWN"):
                            self._scroll_help(key)
                        continue
                    if self.run_focused:
                        if key == "\x03":
                            if self.run_process is not None:
                                self.run_process.send_signal(signal.SIGINT)
                        elif key == ESC:
                            self._stop_run()
                        elif key in (
                            "UP", "DOWN", "CTRL-UP", "CTRL-DOWN"
                        ):
                            self._scroll_run_output(key)
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
                        elif key == "\x08":
                            self.worktree_show_hidden = (
                                not self.worktree_show_hidden
                            )
                            self._invalidate_worktree_cache()
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
                            if self._is_blank_buffer():
                                self.status = "Open or create a file first"
                            else:
                                self.mode = "insert"
                                self._maybe_autosave()
                        continue
                    if self.command is not None:
                        if key in ("\r", "\n"):
                            self._execute_command()
                        elif key in ("\x7f", "\b"):
                            self.command = self.command[:-1]
                        elif key == ESC:
                            self.command = None
                            self.mode = "visual"
                        elif key == "\t":
                            self._cmd_tab_complete()
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
                    if self.move_mode:
                        if key in ("j", "DOWN"):
                            self._move_current_line_or_selection(1)
                        elif key in ("k", "UP"):
                            self._move_current_line_or_selection(-1)
                        elif key in ("m", ESC):
                            self.move_mode = False
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
                    elif dropdown_open and key == "\t":
                        self._accept_highlighted_suggestion()
                    elif dropdown_open and key == ESC:
                        self.suggestion_matches = []
                        self._suggestion_dismissed_at = (
                            self.line, self.column
                        )
                    elif key == ESC:
                        was_insert = self.mode == "insert"
                        self.mode = "visual"
                        self.command = None
                        self.selection_anchor = None
                        if was_insert:
                            self._maybe_autosave()
                    elif self.mode == "visual" and key == ":":
                        self.mode = "command"
                        self.command = ""
                    elif self.mode == "visual" and key == "/":
                        self.mode = "search"
                        self.search_query = ""
                    elif self.mode == "visual" and key == "m":
                        self.move_mode = True
                    elif self.mode == "visual" and key == "w":
                        if not self.worktree_visible:
                            self.worktree_visible = True
                            self.worktree_visible_because_of_focus = True
                        self.worktree_focused = True
                        self._invalidate_worktree_cache()
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
                        if self._is_blank_buffer():
                            self.status = "Open or create a file first"
                        else:
                            self.mode = "insert"
                            self.selection_anchor = None
                            self._maybe_autosave()
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
                    elif self.mode == "visual" and key in ("a", "\x01"):
                        self._update_selection(
                            "CTRL-A" if key == "\x01" else key
                        )
                        self.column = 0
                    elif self.mode == "visual" and key in ("f", "\x06"):
                        self._update_selection(
                            "CTRL-F" if key == "\x06" else key
                        )
                        self.column = len(self.lines[self.line])
                    elif self.mode == "visual" and key in ("s", "\x13"):
                        self._update_selection(
                            "CTRL-S" if key == "\x13" else key
                        )
                        self.line = 0
                        self.column = 0
                    elif self.mode == "visual" and key in ("d", "\x04"):
                        self._update_selection(
                            "CTRL-D" if key == "\x04" else key
                        )
                        self.line = len(self.lines) - 1
                        self.column = 0
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
                            self._insert(_indent_unit(self.file_name))
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
            if update_check_fd is not None:
                terminal.set_update_check_fd(None)
                os.close(update_check_fd)


def edit_file(file_name=None, worktree_root=None):
    editor = TextEditor(file_name)
    if worktree_root is not None:
        editor.worktree_root = os.path.abspath(worktree_root)
        editor.worktree_selected_dir = editor.worktree_root
        editor.worktree_visible = True
        editor.worktree_focused = True
    editor.run()
