"""Everything that turns editor state into the ANSI-escaped frame
written to the terminal: the tab bar, bracket/quote match detection,
the help screen, and the main render() loop itself."""

import functools
import os
import sys

import theme
from autocomplete import MAX_SUGGESTION_DROPDOWN_ITEMS
from editing import BRACKET_PAIRS, CLOSING_TO_OPENING, QUOTE_CHARACTERS
from highlighting import _highlight, _highlight_c, is_in_triple_quoted_string
from languages import language_for
from terminal import _get_terminal_size
from worktree import MIN_EDITOR_WIDTH, WORKTREE_SEPARATOR_WIDTH, WORKTREE_WIDTH


def _no_highlight(text, lookahead=""):
    return text


def _wrap_points(text, content_width):
    """Raw string indices where `text` should be split so each
    resulting piece's *display* width (tabs expanded to TAB_SIZE
    columns) fits within `content_width` - always at least one
    split point at 0 and one at len(text), even for an empty line or
    one that already fits with no wrapping needed at all."""
    if content_width <= 0:
        return [0, len(text)]
    points = [0]
    display_column = 0
    for index, character in enumerate(text):
        char_width = theme.TAB_SIZE if character == "\t" else 1
        if display_column + char_width > content_width and display_column > 0:
            points.append(index)
            display_column = 0
        display_column += char_width
    points.append(len(text))
    return points


def _line_row_count(text, content_width):
    return len(_wrap_points(text, content_width)) - 1


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

    def _matching_bracket_position(self):
        line = self.lines[self.line]
        if self.column >= len(line):
            return None
        if is_in_triple_quoted_string(line, self.column):
            # Quote-matching has no notion of a triple-quote as one
            # three-character delimiter - left alone, it would pair
            # up two of the docstring's own quotes (or split its
            # highlighting apart at whichever one the cursor is on)
            # instead of leaving the whole thing as the one
            # comment-colored block it actually renders as.
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

    def _render_wrapped_segment(
        self, text, seg_start, seg_end, is_last_segment, is_current_line,
        selection_range, bracket_column, apply_highlight, suggestion,
    ):
        """One wrap row's worth of colored/escaped content for
        `text[seg_start:seg_end]` - the same selection/suggestion/
        bracket handling a whole unwrapped line gets, just scoped to
        this one segment. Always in absolute, whole-line column
        coordinates throughout (what _render_segment and
        bracket_column already use), never segment-local ones. With
        only one segment covering the whole line (the common,
        unwrapped case), this produces exactly what the old
        single-segment code did."""
        if is_last_segment:
            cursor_in_segment = seg_start <= self.column <= seg_end
        else:
            cursor_in_segment = seg_start <= self.column < seg_end
        if is_current_line and suggestion and cursor_in_segment:
            return (
                self._render_segment(
                    text[seg_start:self.column], seg_start, bracket_column,
                    apply_highlight,
                )
                + theme.SUGGESTION_COLOR
                + self._display_text(suggestion)
                + theme.SUGGESTION_RESET
                + self._render_segment(
                    text[self.column:seg_end], self.column, bracket_column,
                    apply_highlight,
                )
            )
        if selection_range is not None:
            sel_start, sel_end = selection_range
            clipped_start = max(sel_start, seg_start)
            clipped_end = min(sel_end, seg_end)
            if clipped_start < clipped_end:
                return (
                    self._render_segment(
                        text[seg_start:clipped_start], seg_start,
                        bracket_column, apply_highlight,
                    )
                    + theme.SELECTION_START
                    + self._render_segment(
                        text[clipped_start:clipped_end], clipped_start,
                        bracket_column, apply_highlight,
                    )
                    + theme.SELECTION_END
                    + self._render_segment(
                        text[clipped_end:seg_end], clipped_end,
                        bracket_column, apply_highlight,
                    )
                )
        return self._render_segment(
            text[seg_start:seg_end], seg_start, bracket_column,
            apply_highlight,
        )

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
        # How many columns are actually left for a line's own text,
        # after the sidebar (if shown) and the gutter (line number/
        # current-line marker) - a line that doesn't fit soft-wraps
        # onto more than one screen row instead of either overflowing
        # into the next row at column 1 (the terminal's own doing, not
        # Mini's) or getting cut off.
        content_width = max(
            1, terminal_width - editor_col_offset - gutter_width
        )
        self._ensure_cursor_visible(editor_rows, content_width)
        selection_bounds = self._selection_bounds()
        self._refresh_suggestion_matches()
        suggestion = self._ghost_suggestion()
        bracket_match = self._matching_bracket_position()
        language = language_for(self.file_name)
        if language == "python":
            apply_highlight = _highlight
        elif language == "c":
            apply_highlight = functools.partial(_highlight_c, cpp=False)
        elif language == "cpp":
            apply_highlight = functools.partial(_highlight_c, cpp=True)
        else:
            apply_highlight = _no_highlight

        # Wrap rows for however many lines, starting at viewport_top,
        # fit in editor_rows - each entry is one screen row's worth of
        # one line's text (line_index, seg_start, seg_end, is_first,
        # is_last); a line short enough not to wrap is just one entry
        # covering the whole thing.
        row_descriptors = []
        wrap_line_index = self.viewport_top
        ran_out_of_lines = False
        while len(row_descriptors) < editor_rows:
            if wrap_line_index >= len(self.lines):
                ran_out_of_lines = True
                break
            points = _wrap_points(self.lines[wrap_line_index], content_width)
            segment_count = len(points) - 1
            for segment_index in range(segment_count):
                row_descriptors.append((
                    wrap_line_index, points[segment_index],
                    points[segment_index + 1], segment_index == 0,
                    segment_index == segment_count - 1,
                ))
                if len(row_descriptors) >= editor_rows:
                    break
            wrap_line_index += 1
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
            elif row_offset < len(row_descriptors):
                (
                    index, seg_start, seg_end, is_first_segment,
                    is_last_segment,
                ) = row_descriptors[row_offset]
                text = self.lines[index]
                is_current_line = index == self.line
                if is_first_segment:
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
                else:
                    # A wrapped line's continuation row: no marker or
                    # number of its own, but padded to the exact same
                    # width so the text still starts right where a
                    # first-segment row's text would - not back at
                    # column 1, which is what made this look broken.
                    marker = "   " if show_indicator else ""
                    number = " " * (number_width + 1) if show_number else ""
                selection_range = self._selection_range_for_line(
                    index, selection_bounds
                )
                bracket_column = (
                    bracket_match[1]
                    if bracket_match and bracket_match[0] == index
                    else None
                )
                displayed = self._render_wrapped_segment(
                    text, seg_start, seg_end, is_last_segment,
                    is_current_line, selection_range, bracket_column,
                    apply_highlight, suggestion,
                )
                editor_row = f"{marker}{number}{displayed}"
                if is_first_segment:
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
            elif (
                row_offset == len(row_descriptors)
                and ran_out_of_lines and show_number
            ):
                placeholder_prefix = "   " if show_indicator else ""
                editor_row = (
                    f"{theme.PLACEHOLDER_COLOR}{placeholder_prefix}"
                    f"{len(self.lines) + 1:>{number_width}} "
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
            # Which wrap row the cursor's own line/column falls on -
            # normally the only (or first) row for that line; keeps
            # scanning past an exact-but-wrong-boundary match so a
            # cursor sitting right at a wrap point lands at the start
            # of the next row rather than the end of the previous one.
            cursor_row_offset = None
            cursor_seg_start = 0
            for offset, descriptor in enumerate(row_descriptors):
                idx, seg_start, seg_end, _, is_last = descriptor
                if idx != self.line:
                    continue
                cursor_row_offset = offset
                cursor_seg_start = seg_start
                if self.column < seg_end or (
                    is_last and self.column <= seg_end
                ):
                    break
            if cursor_row_offset is None:
                # The cursor's own line got cut off before its
                # relevant segment (an extremely long current line on
                # a very short screen) - the last row shown is the
                # closest thing to "where the cursor is" available.
                cursor_row_offset = max(0, len(row_descriptors) - 1)
            cursor_row = 2 + cursor_row_offset
            cursor_column = (
                editor_col_offset + gutter_width + 1
                + len(self._display_text(
                    self.lines[self.line][cursor_seg_start:self.column]
                ))
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

    def _ensure_cursor_visible(self, visible_rows, content_width):
        if self.line < self.viewport_top:
            self.viewport_top = self.line
            return
        rows_needed = sum(
            _line_row_count(self.lines[index], content_width)
            for index in range(self.viewport_top, self.line + 1)
        )
        # Doesn't fit from the current viewport_top - slide it forward
        # one line at a time (dropping that line's own row count from
        # the running total) until it does, the same idea as the old
        # closed-form shortcut, just accounting for a line that can
        # now cost more than one row. Stops at self.line itself even
        # if that one line alone still doesn't fit the whole screen -
        # its own first rows are still the right thing to show.
        while rows_needed > visible_rows and self.viewport_top < self.line:
            rows_needed -= _line_row_count(
                self.lines[self.viewport_top], content_width
            )
            self.viewport_top += 1
