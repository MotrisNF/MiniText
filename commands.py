"""The `:` command line: parsing, dispatch, save/close, line-numbered
operations (jump/copy/delete/paste by number), and search."""

import os
import re
import sys

import terminal
import theme


class CommandMixin:

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

    def _close_tab_prompting_if_modified(self):
        """`:q`'s own logic, factored out so the tab bar's mouse-only
        × (see rendering.py's `_tab_bar_line`) and the centered "Close
        Mini" button (shown once down to a lone blank tab) can share
        it exactly - closing a tab should never silently discard
        unsaved changes just because it was triggered by a click
        instead of `:q`. Closing the very last tab doesn't exit Mini
        outright anymore (see `_close_current_tab`) unless it was
        already blank, so the prompt only ever needs to talk about
        exiting when that's actually what's about to happen."""
        already_blank = (
            self.file_name is None and self.lines == [""]
            and not self.modified
        )
        prompt = (
            "Save changes before exiting? (y/n)"
            if len(self.tabs) <= 1 and already_blank else
            "Save changes before closing this tab? (y/n)"
        )
        if not self.modified:
            self._close_current_tab()
        elif self._confirm(prompt):
            if self._save():
                self._close_current_tab()
        else:
            self.status = "Closed without saving"
            self._close_current_tab()

    def _close_tab_by_index(self, index):
        """Closing a tab by its position in the tab bar (the ×
        clicked next to its name - see rendering.py's
        `_tab_bar_line`/`_handle_mouse_event`), which may not be the
        currently active one. `_close_tab_prompting_if_modified`
        (and, under it, `_close_current_tab`) only ever knows how to
        close *the* active tab, so a tab that isn't active is
        switched to first, closed, then whichever tab should end up
        active afterwards - the one the user was already on, shifted
        left by one if it came after the closed tab - is restored."""
        if index == self.active_tab:
            self._close_tab_prompting_if_modified()
            return
        original_active = self.active_tab
        tab_count_before = len(self.tabs)
        self._switch_to_tab(index)
        self._close_tab_prompting_if_modified()
        if len(self.tabs) < tab_count_before:
            restored_index = (
                original_active - 1 if index < original_active
                else original_active
            )
            self._switch_to_tab(
                max(0, min(restored_index, len(self.tabs) - 1))
            )
        else:
            self._switch_to_tab(original_active)

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
        if name == "w":
            self._save_all_tabs()
        elif name == "q":
            self.running = False
        elif name in ("wq", "qw"):
            self._save_all_tabs()
            self.running = False

    def _read_command_line(self, label="File name"):
        value = ""
        while True:
            key = terminal.read_key()
            if key in ("\r", "\n"):
                return value.strip()
            if key in ("\x7f", "\b"):
                value = value[:-1]
            elif key == terminal.ESC:
                return ""
            elif len(key) == 1 and key.isprintable():
                value += key
            self.status = f"{label}: {value}"
            self._render()

    def _confirm(self, prompt):
        self.status = prompt
        self._render()
        while True:
            key = terminal.read_key()
            if key in ("y", "Y"):
                return True
            if key in ("n", "N", terminal.ESC):
                return False

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
        if command in ("w!", "q!", "wq!", "qw!"):
            self._execute_forced_command(command[:-1])
            return
        if command == "cmd" or command.startswith("cmd "):
            # Free-form text after "cmd " - never matches
            # _parse_command's name/line-number pattern, so it has to
            # be pulled out before that runs.
            self._start_cmd(command[len("cmd"):].strip())
            return
        name, argument = self._parse_command(command)
        if name == "w" and argument is None:
            self._save()
        elif name == "q" and argument is None:
            self._close_tab_prompting_if_modified()
        elif name == "u" and argument is None:
            self._undo()
        elif name == "r" and argument is None:
            self._redo()
        elif name in ("wq", "qw") and argument is None:
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
        elif name == "tree" and argument is None:
            self.worktree_visible = not self.worktree_visible
            if self.worktree_visible:
                self._invalidate_worktree_cache()
            else:
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
        elif name == "refresh" and argument is None:
            self._refresh_config()
        else:
            self.status = f"Unknown command: :{command}"

    def _refresh_config(self):
        """`:refresh` - re-reads ~/.minirc and applies it live,
        without restarting Mini or touching any open buffer/tab/undo
        state: colors, MAX_COLS/INDENT_WITH_TABS/TAB_SIZE (plain and
        per-[filetype:...]), and MOUSE_ENABLED. A forced full redraw
        follows, since the differential-render cache holds rows drawn
        with whatever colors were active before this - stale colors
        would otherwise linger on any row that doesn't happen to
        change again on its own. MOUSE_ENABLED needs its own explicit
        escape sequence too: the terminal was only ever told to start/
        stop reporting mouse events once, when raw_terminal() was
        entered - reassigning theme.MOUSE_ENABLED alone wouldn't make
        the terminal itself do anything differently."""
        was_mouse_enabled = theme.MOUSE_ENABLED
        theme.reload()
        if theme.MOUSE_ENABLED != was_mouse_enabled:
            sys.stdout.write(
                terminal._MOUSE_ENABLE if theme.MOUSE_ENABLED
                else terminal._MOUSE_DISABLE
            )
            sys.stdout.flush()
        self._force_full_redraw = True
        self.status = "Reloaded ~/.minirc"

    def _cmd_completion_directory(self):
        return (
            os.path.dirname(os.path.abspath(self.file_name))
            if self.file_name else self.worktree_root
        )

    def _cmd_tab_complete(self):
        """Tab in a `:cmd <text>` command line: shell-style completion
        against file/directory names in the same directory `:cmd`
        itself would actually run in - one directory level only (a
        token that already has a `/` in it is left alone, same as
        typing `sub/` and pressing Tab not listing what's inside
        `sub/`). Each Tab press after the first cycles to the next
        match directly in the line, wrapping around - no dropdown.
        Self-validating rather than needing to be reset from every
        place the command line can change: a Tab continues the last
        cycle only if the line still ends in exactly what the
        previous Tab left there; anything else (typing, backspacing,
        a fresh `:cmd`) is naturally treated as starting over."""
        if not self.command.startswith("cmd "):
            return
        state = self._cmd_tab_state
        if state is not None:
            token_start, matches, index, last_inserted = state
            if self.command[token_start:] == last_inserted:
                index = (index + 1) % len(matches)
                new_text = matches[index]
                self.command = self.command[:token_start] + new_text
                self._cmd_tab_state = (token_start, matches, index, new_text)
                return
        token_start = self.command.rfind(" ") + 1
        token = self.command[token_start:]
        if "/" in token:
            return
        try:
            entries = sorted(os.listdir(self._cmd_completion_directory()))
        except OSError:
            return
        matches = [name for name in entries if name.startswith(token)]
        if not matches:
            return
        self.command = self.command[:token_start] + matches[0]
        self._cmd_tab_state = (token_start, matches, 0, matches[0])
