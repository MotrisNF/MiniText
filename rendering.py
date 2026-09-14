"""Everything that turns editor state into the ANSI-escaped frame
written to the terminal: the tab bar, bracket/quote match detection,
the help screen, and the main render() loop itself."""

import os
import sys

import theme
from autocomplete import MAX_SUGGESTION_DROPDOWN_ITEMS
from editing import BRACKET_PAIRS, CLOSING_TO_OPENING, QUOTE_CHARACTERS
from highlighting import _highlight
from terminal import _get_terminal_size
from worktree import MIN_EDITOR_WIDTH, WORKTREE_SEPARATOR_WIDTH, WORKTREE_WIDTH


class RenderMixin:

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
    def _display_text(text):
        return text.replace("\t", " " * theme.TAB_SIZE)

    def _display_column(self):
        return len(self._display_text(self.lines[self.line][:self.column]))

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
                apply_highlight(self._display_text(before), bracket_character)
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
            "  :tree    Toggle the worktree panel's visibility\r\n",
            "  :run     Run this .py file, output shown below the code\r\n",
            "           (Ctrl+C interrupts it, Esc unfocuses/closes it,\r\n",
            "           typing sends input to it, Up/Down or\r\n",
            "           Ctrl+Up/Down scroll its output)\r\n",
            "  :lint    Run flake8 + mypy on this file, same output\r\n",
            "           panel as :run; deletes .mypy_cache afterward\r\n",
            "  :cmd <text>  Run text as a bash command, same panel\r\n",
            "  Worktree: Up/Down or j/k move, l expands a directory,\r\n",
            "    h collapses it, Enter opens a file as a tab\r\n",
            "    (or switches to it if already open) or\r\n",
            "    expands/collapses a directory. Ctrl+F new file,\r\n",
            "    Ctrl+D new folder, Ctrl+H toggles hidden files,\r\n",
            "    Del deletes, v/Esc return focus,\r\n",
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
            "  :w       Save\r\n",
            "  :q       Close this tab (asks to save changes if any);\r\n",
            "           exits if it's the last tab open\r\n",
            "  :wq/:qw  Save and close this tab (or exit if last)\r\n",
            "  :w!      Save every open tab, no confirmation\r\n",
            "  :q!      Exit now, discarding all unsaved changes\r\n",
            "  :wq!/:qw!  Save every open tab, then exit\r\n",
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
        terminal_size = _get_terminal_size()
        terminal_height = max(4, terminal_size.lines)
        terminal_width = terminal_size.columns
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
        self._run_rows = run_rows
        # Where the visible window into run_display_lines starts:
        # pinned (None) always tracks the live tail, like `tail -f`;
        # otherwise it's a fixed absolute position the user scrolled
        # to, which stays put as more output arrives below it.
        run_max_start = max(0, len(run_display_lines) - run_rows)
        run_start = (
            run_max_start if self.run_view_start is None
            else min(self.run_view_start, run_max_start)
        )
        self._ensure_cursor_visible(editor_rows)
        last_visible_line = min(
            len(self.lines), self.viewport_top + editor_rows
        )
        selection_bounds = self._selection_bounds()
        self._refresh_suggestion_matches()
        suggestion = self._ghost_suggestion()
        bracket_match = self._matching_bracket_position()
        apply_highlight = _highlight if self._is_python_file() else (
            lambda text, lookahead="": text
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

        # Differential rendering: a row only gets re-sent to the
        # terminal when its own text actually changed since the last
        # frame - typing fast on one line, the common case, then only
        # ever redraws that one row instead of the whole screen. A
        # resize or the help screen (which paints over everything
        # itself) sets _force_full_redraw; a shrinking/closing
        # suggestion dropdown - the one overlay that isn't part of any
        # row's own content - is caught here, since it can leave
        # stale cells behind on the rows it used to cover otherwise.
        dropdown_will_show = (
            self.mode == "insert" and self.command is None
            and self.search_query is None and not self.worktree_focused
            and not self.run_focused
            and len(self.suggestion_matches[:MAX_SUGGESTION_DROPDOWN_ITEMS])
            >= 2
        )
        full_redraw = (
            self._force_full_redraw
            or (terminal_width, terminal_height) != self._last_terminal_size
            or dropdown_will_show or self._dropdown_was_shown
        )
        self._dropdown_was_shown = dropdown_will_show
        self._last_terminal_size = (terminal_width, terminal_height)
        self._force_full_redraw = False

        output = [theme.BASE_STYLE]
        if full_redraw:
            output.append("\x1b[2J")
            self._last_rendered_rows = {}
        output.append(f"\x1b[1;1H\x1b[K{tab_bar_row}")
        ruler_overlay = []
        for row_offset in range(visible_rows):
            if run_visible and row_offset == editor_rows:
                status_word = (
                    "running" if self.run_process is not None else "finished"
                )
                if self.run_view_start is None:
                    divider_text = f" Output ({status_word}) "
                else:
                    shown_through = min(
                        run_start + run_rows, len(run_display_lines)
                    )
                    divider_text = (
                        f" Output ({status_word}) - lines "
                        f"{run_start + 1}-{shown_through}"
                        f"/{len(run_display_lines)} "
                    )
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
                output_index = run_start + run_row_index
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
            if full_redraw or self._last_rendered_rows.get(
                row_offset
            ) != row_text:
                output.append(f"\x1b[{terminal_row};1H\x1b[K{row_text}")
            self._last_rendered_rows[row_offset] = row_text

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
