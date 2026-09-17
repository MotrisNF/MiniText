"""Everything that turns editor state into the ANSI-escaped frame
written to the terminal: the tab bar, bracket/quote match detection,
the help screen, and the main render() loop itself. Mouse event
dispatch lives in mouse.py, and overlay-box geometry/rendering (the
"Close Mini" button, the welcome banner, the name/confirm dialogs) in
dialogs.py - both split out of here, and both still driven from
`render()`/`self._mouse_layout` below."""

import functools
import os
import sys

import theme
from autocomplete import _INCLUDE_LINE_PATTERN, MAX_SUGGESTION_DROPDOWN_ITEMS
from editing import BRACKET_PAIRS, CLOSING_TO_OPENING, QUOTE_CHARACTERS
from highlighting import (
    _highlight_c, _highlight_python, is_in_triple_quoted_string,
)
from languages import language_for
from terminal import _get_terminal_size
from worktree import MIN_EDITOR_WIDTH, WORKTREE_SEPARATOR_WIDTH, WORKTREE_WIDTH


def _no_highlight(text, lookahead=""):
    return text


# A guaranteed-red foreground for a hovered "×" (tab close, name-
# dialog cancel) - deliberately not one of theme.py's own palette
# colors, since those are user-customizable (LINE_LENGTH_ERROR_COLOR,
# the closest existing one, is themeable per ~/.minirc and isn't
# necessarily red at all) and "red" here is the whole point, not a
# theme choice. Standard SGR red, not a 256-color index, so it's not
# subject to a terminal's own 256-color palette remapping either.
# Also used by dialogs.py's own name-dialog "×".
_CLOSE_HOVER_COLOR = "\x1b[91m"


def _inline_tab_positions(line):
    """(leading_end, tab_indices): `leading_end` is where `line`'s own
    leading whitespace stops (a tab before it is plain indentation,
    not part of any alignment); `tab_indices` are every tab at or
    after that point - the "elastic tabstops" cell separators (see
    ElasticTabstopsMixin's own docstring). A cell's content never
    contains a tab itself, by construction: every tab in the line
    from `leading_end` on is already accounted for as a separator."""
    leading_end = len(line) - len(line.lstrip(" \t"))
    tab_indices = [
        index for index in range(leading_end, len(line))
        if line[index] == "\t"
    ]
    return leading_end, tab_indices


class RenderMixin:

    def _tab_file_name(self, index):
        if index == self.active_tab:
            return self.file_name
        return self.tabs[index]["file_name"]

    def _tab_label(self, index):
        file_name = self._tab_file_name(index)
        modified = (
            self.modified if index == self.active_tab
            else self.tabs[index]["modified"]
        )
        name = os.path.basename(file_name) if file_name else "MiniText"
        marker = "● " if modified else ""
        return marker, name

    def _tab_segment_text(self, index):
        """The plain (unstyled) text of tab `index`'s own segment in
        the tab bar, and the 0-indexed offset of its "×" close marker
        within that text - None when there is none. The × only exists
        at all in mouse mode (see terminal.py's own docstring on why
        mouse support is opt-in): without a mouse there's no way to
        click it, and `:q` already closes tabs just fine, so it would
        only ever be visual noise for a keyboard-only user. It's also
        never there on the one unnamed "MiniText" tab (no real file
        behind it - closing it, `:q`'s own job, just resets it back to
        blank rather than removing a tab at all, see tabs.py's own
        `_close_current_tab`), so there's nothing for it to click
        closed in the first place."""
        marker, name = self._tab_label(index)
        text = f" {marker}{name} "
        if not theme.MOUSE_ENABLED or self._tab_file_name(index) is None:
            return text, None
        close_offset = len(text)
        # A trailing space of its own margin after the × too, so it
        # doesn't sit flush against the "│" separator to its right -
        # the same reason there's already one before it, on the other
        # side of the tab's own name.
        return text + "× ", close_offset

    def _tab_bar_line(self):
        segments = []
        for index in range(len(self.tabs)):
            text, close_offset = self._tab_segment_text(index)
            background = (
                theme.ACTIVE_TAB_COLOR if index == self.active_tab
                else theme.INACTIVE_TAB_COLOR
            )
            base = f"{background}{theme.TEXT_COLOR}"
            if close_offset is not None and index == self._hovered_tab_close:
                before = text[:close_offset]
                close_char = text[close_offset]
                after = text[close_offset + 1:]
                styled = (
                    f"{base}{before}{_CLOSE_HOVER_COLOR}"
                    f"{close_char}{base}{after}"
                )
            else:
                styled = f"{base}{text}"
            segments.append(f"{styled}{theme.BASE_STYLE}")
        separator = f"{theme.LINE_NUMBER_COLOR}│{theme.BASE_STYLE}"
        return separator.join(segments)

    def _tab_target_at(self, column0):
        """(tab_index, is_close) for 0-indexed display column
        `column0` of the tab bar's own text - the same segments and
        "│" separators `_tab_bar_line` renders, just measured instead
        of styled. `is_close` is only ever true when the column lands
        exactly on the tab's own "×" (see `_tab_segment_text`).
        (None, False) past the last tab (the empty space after it, if
        the bar doesn't fill the whole width)."""
        position = 0
        for index in range(len(self.tabs)):
            text, close_offset = self._tab_segment_text(index)
            width = len(text)
            if column0 < position + width:
                is_close = (
                    close_offset is not None
                    and column0 == position + close_offset
                )
                return index, is_close
            position += width + 1
        return None, False

    def _elastic_block_bounds(self, line_index, column_index):
        """The maximal contiguous run of lines around `line_index`
        that all have a tab at cell-separator index `column_index` -
        the vertical group whose cell `column_index` must share one
        display width, "elastic tabstops" style: type the same kind
        of line below another (another tab at the same cell index) and
        the group - and its width - grows to include it; a line
        without one (blank, differently-shaped, or a gap) ends the
        group there, same as a real elastic-tabstops implementation."""
        start = line_index
        while (
            start > 0
            and len(_inline_tab_positions(self.lines[start - 1])[1])
            > column_index
        ):
            start -= 1
        end = line_index
        while (
            end + 1 < len(self.lines)
            and len(_inline_tab_positions(self.lines[end + 1])[1])
            > column_index
        ):
            end += 1
        return start, end

    def _elastic_cell_target_width(self, line_index, column_index):
        """Display width cell `column_index` (0-indexed: the text
        between the (column_index-1)-th and column_index-th tab, or
        the line's own indentation and the first tab for column 0)
        should be padded to on `line_index` - the widest such cell
        among every line in its block (see `_elastic_block_bounds`),
        plus one column of guaranteed spacing so cells never touch
        even when one of them is already the widest. Cached for the
        rest of this render() call only (cleared at the top of it) -
        every line in the block gets the same answer written at once,
        so a neighbor within it never repeats the same up/down scan."""
        cache_key = (line_index, column_index)
        if cache_key in self._elastic_width_cache:
            return self._elastic_width_cache[cache_key]
        start, end = self._elastic_block_bounds(line_index, column_index)
        widest = 0
        for index in range(start, end + 1):
            leading_end, tabs = _inline_tab_positions(self.lines[index])
            cell_start = (
                leading_end if column_index == 0
                else tabs[column_index - 1] + 1
            )
            widest = max(widest, tabs[column_index] - cell_start)
        target = widest + 1
        for index in range(start, end + 1):
            self._elastic_width_cache[(index, column_index)] = target
        return target

    def _character_display_width(self, line_index, raw_index):
        """Display width of the character at `self.lines[line_index]
        [raw_index]` - 1 for anything but a tab; a tab's own width is
        `TAB_SIZE` (per the file's own resolved settings) for a
        leading, purely-indenting one, or whatever's needed to reach
        its elastic-tabstop cell's target width for one used to
        separate cells later in the line."""
        line = self.lines[line_index]
        if line[raw_index] != "\t":
            return 1
        leading_end, tabs = _inline_tab_positions(line)
        if raw_index < leading_end:
            return theme.settings_for(self.file_name)["TAB_SIZE"]
        column_index = tabs.index(raw_index)
        cell_start = (
            leading_end if column_index == 0 else tabs[column_index - 1] + 1
        )
        target = self._elastic_cell_target_width(line_index, column_index)
        return target - (raw_index - cell_start)

    def _display_text(self, text, line_index=None, raw_start=0):
        """`text` with every tab expanded to the right number of
        spaces for how it's actually displayed. `line_index` (with
        `raw_start`, `text`'s own starting offset within
        `self.lines[line_index]`) is what makes an inline tab's width
        elastic - real buffer content always passes both; synthetic,
        program-generated text that isn't really at any position in
        the buffer (autocomplete's own ghost text, namely) omits them
        and falls back to a flat TAB_SIZE-per-tab expansion instead,
        which is never wrong for text that was never typed and so
        was never part of any elastic-tabstop cell to begin with."""
        if line_index is None:
            return text.replace("\t", " " * theme.TAB_SIZE)
        pieces = []
        for offset, character in enumerate(text):
            if character == "\t":
                width = self._character_display_width(
                    line_index, raw_start + offset
                )
                pieces.append(" " * width)
            else:
                pieces.append(character)
        return "".join(pieces)

    def _wrap_points(self, line_index, content_width):
        """Raw string indices where this line should be split so each
        resulting piece's *display* width fits within `content_width`
        - always at least one split point at 0 and one at len(text),
        even for an empty line or one that already fits with no
        wrapping needed at all."""
        text = self.lines[line_index]
        if content_width <= 0:
            return [0, len(text)]
        points = [0]
        display_column = 0
        for index in range(len(text)):
            char_width = self._character_display_width(line_index, index)
            fits = display_column + char_width <= content_width
            if not fits and display_column > 0:
                points.append(index)
                display_column = 0
            display_column += char_width
        points.append(len(text))
        return points

    def _line_row_count(self, line_index, content_width):
        return len(self._wrap_points(line_index, content_width)) - 1

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
        self, line_index, text_segment, absolute_start, bracket_column,
        apply_highlight, word_match_ranges=None,
    ):
        if word_match_ranges:
            segment_end = absolute_start + len(text_segment)
            local_ranges = [
                (max(0, s - absolute_start),
                 min(len(text_segment), e - absolute_start))
                for s, e in word_match_ranges
                if s < segment_end and e > absolute_start
            ]
            if local_ranges:
                pieces = []
                cursor = 0
                for local_start, local_end in local_ranges:
                    if local_start > cursor:
                        pieces.append(self._render_segment(
                            line_index, text_segment[cursor:local_start],
                            absolute_start + cursor, bracket_column,
                            apply_highlight,
                        ))
                    pieces.append(
                        theme.WORD_MATCH_START
                        + self._render_segment(
                            line_index, text_segment[local_start:local_end],
                            absolute_start + local_start, bracket_column,
                            apply_highlight,
                        )
                        + theme.WORD_MATCH_END
                    )
                    cursor = local_end
                if cursor < len(text_segment):
                    pieces.append(self._render_segment(
                        line_index, text_segment[cursor:],
                        absolute_start + cursor, bracket_column,
                        apply_highlight,
                    ))
                return "".join(pieces)
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
                apply_highlight(
                    self._display_text(before, line_index, absolute_start),
                    bracket_character,
                )
                + theme.BRACKET_MATCH_START
                + self._display_text(
                    bracket_character, line_index, bracket_column,
                )
                + theme.BRACKET_MATCH_END
                + apply_highlight(self._display_text(
                    after, line_index, bracket_column + 1,
                ))
            )
        return apply_highlight(
            self._display_text(text_segment, line_index, absolute_start)
        )

    def _render_wrapped_segment(
        self, line_index, text, seg_start, seg_end, is_last_segment,
        is_current_line, selection_range, bracket_column, apply_highlight,
        suggestion, word_match_ranges=None,
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
                    line_index, text[seg_start:self.column], seg_start,
                    bracket_column, apply_highlight, word_match_ranges,
                )
                + theme.SUGGESTION_COLOR
                + self._display_text(suggestion)
                + theme.SUGGESTION_RESET
                + self._render_segment(
                    line_index, text[self.column:seg_end], self.column,
                    bracket_column, apply_highlight, word_match_ranges,
                )
            )
        if selection_range is not None:
            sel_start, sel_end = selection_range
            clipped_start = max(sel_start, seg_start)
            clipped_end = min(sel_end, seg_end)
            if clipped_start < clipped_end:
                return (
                    self._render_segment(
                        line_index, text[seg_start:clipped_start], seg_start,
                        bracket_column, apply_highlight, word_match_ranges,
                    )
                    + theme.SELECTION_START
                    + self._render_segment(
                        line_index, text[clipped_start:clipped_end],
                        clipped_start, bracket_column, apply_highlight,
                        word_match_ranges,
                    )
                    + theme.SELECTION_END
                    + self._render_segment(
                        line_index, text[clipped_end:seg_end], clipped_end,
                        bracket_column, apply_highlight, word_match_ranges,
                    )
                )
        return self._render_segment(
            line_index, text[seg_start:seg_end], seg_start, bracket_column,
            apply_highlight, word_match_ranges,
        )

    def _render_help(self):
        """Renders the in-editor `:help` reference. Unlike the main
        editor, this bypasses the row-by-row differential renderer
        entirely and repaints the whole screen on every call - simple,
        and cheap enough for a screen that only redraws on `q`, a
        scroll key, or a resize. It does, though, actually look at the
        real terminal size (`_get_terminal_size()`, same as `_render`
        itself) and scroll (`self._help_scroll`, moved by
        `_scroll_help`) so the reference is reachable in full on a
        terminal too short to fit it all at once, instead of just
        losing whatever doesn't fit off the bottom."""
        file_name = self.file_name or "[no name]"
        content_lines = [
            f"File: {file_name}",
            "",
            "Available commands:",
            "  :help    Show this help",
            "  :config  Open ~/.minirc as a tab",
            "  i        Enter Insert mode",
            "  Tab      Accept suggestion (Insert mode); with 2+",
            "           matches, Up/Down/Enter also navigate/accept",
            "  Ctrl+Arrows  Select text (Visual mode)",
            "  w        Show and focus the worktree panel (Visual mode)",
            "  :tree    Toggle the worktree panel's visibility",
            "  :run     Run this .py file, output shown below the code",
            "           (Ctrl+C interrupts it, Esc unfocuses/closes it,",
            "           typing sends input to it, Up/Down or",
            "           Ctrl+Up/Down scroll its output)",
            "  :lint    Run flake8 + mypy on this file, same output",
            "           panel as :run; deletes .mypy_cache afterward",
            "  :cmd <text>  Run text as a bash command, same panel",
            "  Worktree: Up/Down or j/k move, l expands a directory,",
            "    h collapses it, Enter opens a file as a tab",
            "    (or switches to it if already open) or",
            "    expands/collapses a directory. Ctrl+F new file,",
            "    Ctrl+D new folder, Ctrl+H toggles hidden files,",
            "    Del deletes, v/Esc return focus,",
            "    : or i jump to Command/Insert",
            "  Tab      Switch to the next tab (Visual mode)",
            "  Shift+Tab  Switch to the previous tab (Visual mode)",
            "  h j k l  Move left/down/up/right (Visual mode)",
            "  <n> then a move   Repeat that move n times (Visual)",
            "  :l <n>   Jump to line n",
            "  :b       Jump to the beginning of the file",
            "  :e       Jump to the end of the file",
            "  :a       Jump to the start of the current line",
            "  :f       Jump to the end of the current line",
            "  :d       Delete selection",
            "  :d <n>   Delete line n",
            "  :c       Copy selection, or the current line if none",
            "  :cl <n>  Copy line n",
            "  :v       Paste at the cursor",
            "  :vl <n>  Paste as a new line before line n",
            "  :u / Ctrl+Z  Undo",
            "  :r / Ctrl+Y  Redo",
            "  /text     Search",
            "  n        Repeat last search (Visual mode)",
            "  :w       Save",
            "  :q       Close this tab (asks to save changes if any);",
            "           exits if it's the last tab open",
            "  :wq/:qw  Save and close this tab (or exit if last)",
            "  :w!      Save every open tab, no confirmation",
            "  :q!      Exit now, discarding all unsaved changes",
            "  :wq!/:qw!  Save every open tab, then exit",
            "  q        Return to the editor",
        ]
        terminal_size = _get_terminal_size()
        terminal_height = max(4, terminal_size.lines)
        # The last row is reserved for a fixed footer (below) rather
        # than being part of the scrollable content, so it's always
        # visible - including the scroll hint itself, which would
        # otherwise be exactly the line most likely to scroll out of
        # view on a short terminal.
        content_rows = max(1, terminal_height - 1)
        max_scroll = max(0, len(content_lines) - content_rows)
        self._help_scroll = max(0, min(self._help_scroll, max_scroll))
        visible = content_lines[
            self._help_scroll:self._help_scroll + content_rows
        ]
        footer = "Press q to exit."
        if max_scroll:
            footer += (
                f"  Lines {self._help_scroll + 1}-"
                f"{self._help_scroll + len(visible)} of "
                f"{len(content_lines)} - Up/Down/Ctrl+Up/Down scroll."
            )
        output = [
            "\x1b[2J\x1b[H",
            theme.BASE_STYLE,
            "\r\n".join(visible),
            f"\x1b[{terminal_height};1H\x1b[K{footer}",
            "\x1b[?25l",
        ]
        sys.stdout.write("".join(output))
        sys.stdout.flush()

    def _scroll_help(self, key):
        """Moves the help screen's view - UP/DOWN by one line,
        CTRL-UP/CTRL-DOWN by a page - the same idea as
        `_scroll_run_output`. Actual clamping to the real content
        length happens in `_render_help` itself on the next frame, so
        this only needs the terminal's current height to size a
        page."""
        terminal_size = _get_terminal_size()
        page = max(1, max(4, terminal_size.lines) - 1)
        step = page if key in ("CTRL-UP", "CTRL-DOWN") else 1
        if key in ("UP", "CTRL-UP"):
            self._help_scroll = max(0, self._help_scroll - step)
        else:
            self._help_scroll += step

    def _render(self):
        if self.help_mode:
            self._render_help()
            return
        # Elastic-tabstop cell widths are only ever valid for the
        # render they were computed in - a single keystroke anywhere
        # in a block can change every line's width in it, and this is
        # the simplest way to never render a stale one: throw the
        # whole thing away and let it be rebuilt, lazily, as this
        # render's own lookups need it.
        self._elastic_width_cache = {}
        file_settings = theme.settings_for(self.file_name)
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
        # The one blank/unnamed/unmodified "MiniText" placeholder tab
        # (see tabs.py's own `_is_blank_buffer`) isn't a real file -
        # no line-number gutter for it, same reasoning as it having no
        # closing × of its own.
        is_blank_buffer = self._is_blank_buffer()
        show_number = theme.SHOW_NUMBER_LINE and not is_blank_buffer
        show_indicator = theme.SHOW_LINE_INDICATOR and not is_blank_buffer
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
        current_selection_word = self._current_selection_word()
        self._refresh_suggestion_matches()
        suggestion = self._ghost_suggestion()
        bracket_match = self._matching_bracket_position()
        language = language_for(self.file_name)
        if language == "python":
            apply_highlight = _highlight_python
        elif language == "c":
            apply_highlight = functools.partial(_highlight_c, cpp=False)
        elif language == "cpp":
            apply_highlight = functools.partial(_highlight_c, cpp=True)
        else:
            apply_highlight = _no_highlight
        # Resolved once per render, not per import line - the same
        # interpreter :run/:lint would actually use for this file.
        python_path = (
            self._resolve_python_executable() if language == "python"
            else None
        )

        # Wrap rows for however many lines, starting at viewport_top,
        # fit in editor_rows - each entry is one screen row's worth of
        # one line's text (line_index, seg_start, seg_end, is_first,
        # is_last); a line short enough not to wrap is just one entry
        # covering the whole thing.
        row_descriptors = []
        wrap_line_index = self.viewport_top
        while len(row_descriptors) < editor_rows:
            if wrap_line_index >= len(self.lines):
                break
            points = self._wrap_points(wrap_line_index, content_width)
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
        # Closing the last real tab now resets it to blank instead of
        # exiting Mini (see tabs.py's own docstring on why) - so
        # there's otherwise no way at all to quit with just a mouse.
        # This button, shown only once things are down to that one
        # blank/unnamed/unmodified tab, is that way out; `:q` (typed,
        # so it needs no mouse) still works too, on this exact same
        # state, as does clicking it again. Shown - as part of the
        # welcome screen below - whether or not the mouse is on, even
        # though only mouse mode can actually click it; without it,
        # it's simply not interactive, the same as the banner/subtitle
        # above it never are either way.
        show_close_button = (
            len(self.tabs) <= 1
            and is_blank_buffer and self._name_dialog is None
        )
        code_area_left, code_area_width = self._code_area_bounds(
            editor_col_offset, gutter_width, content_width, file_settings
        )
        close_box = (
            self._close_mini_box_geometry(
                code_area_left, code_area_width, editor_rows
            ) if show_close_button else None
        )
        welcome_banner = (
            self._welcome_banner_geometry(
                close_box, code_area_left, code_area_width
            ) if close_box is not None else None
        )
        name_dialog_box = (
            self._name_dialog_box_geometry(
                code_area_left, code_area_width, editor_rows,
                self._name_dialog["label"],
            ) if self._name_dialog is not None else None
        )
        confirm_box = (
            self._confirm_box_geometry(
                code_area_left, code_area_width, editor_rows,
                self._confirm_dialog["prompt"],
                self._confirm_dialog.get("items"),
                self._confirm_dialog.get("scroll", 0),
            ) if theme.MOUSE_ENABLED and self._confirm_dialog is not None
            else None
        )
        # Snapshot of exactly this frame's geometry, so a mouse event
        # arriving before the *next* render (the only time one ever
        # can, since read_key() only runs between one render() call
        # and the next) can be resolved against what's actually on
        # screen right now, without redoing all of the layout math
        # above a second time just to answer "what's at row X, column
        # Y".
        self._mouse_layout = {
            "terminal_height": terminal_height,
            "input_row": input_row,
            "sidebar_visible": sidebar_visible,
            "editor_col_offset": editor_col_offset,
            "gutter_width": gutter_width,
            "run_visible": run_visible,
            "editor_rows": editor_rows,
            "row_descriptors": row_descriptors,
            "visible_rows": visible_rows,
            "close_mini_box": close_box,
            "name_dialog_box": name_dialog_box,
            "confirm_box": confirm_box,
        }
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
        # The "Close Mini"/name-dialog boxes are the same kind of
        # overlay the suggestion dropdown already is above - not part
        # of any row's own content, so a row whose real text hasn't
        # changed (the common case: typing a name doesn't touch
        # self.lines) would otherwise never get redrawn once the box
        # covering it goes away, leaving its border/text stuck on
        # screen forever. Only the *transition* (appearing/
        # disappearing) needs this, though - unlike the row loop below,
        # the box's own content is already repainted unconditionally
        # every frame further down (see close_box/name_dialog_box
        # writes past the row loop), so forcing a full clear on every
        # single keystroke *while* it stays open would only add cost
        # (a full-screen \x1b[2J plus every visible row resent) with
        # nothing extra to show for it - that was the real source of
        # the lag typing into this dialog used to have.
        # Identifies not just *whether* an overlay box is showing but
        # which ones, and at what geometry - a plain True/False here
        # used to treat any box-to-box transition as no change at all,
        # since both sides were simply "True", so the old box's
        # footprint never got cleared and left a stale border/
        # silhouette behind. Each of the three gets its own slot
        # (rather than one "whichever is showing" value) because
        # they're not mutually exclusive - close_box in particular can
        # be showing (the blank/unnamed last-tab welcome screen) at
        # the very same time a worktree delete/move opens a confirm_
        # box on top of it, and a single shared slot would have let
        # close_box's own unchanged presence hide the confirm box's
        # appearing/disappearing right underneath it.

        def _box_identity(box):
            return None if box is None else (
                box["left"], box["width"], box["top_row_offset"]
            )
        overlay_box_identity = (
            _box_identity(close_box), _box_identity(name_dialog_box),
            _box_identity(confirm_box),
        )
        full_redraw = (
            self._force_full_redraw
            or (terminal_width, terminal_height) != self._last_terminal_size
            or dropdown_will_show or self._dropdown_was_shown
            or overlay_box_identity != self._overlay_box_was_shown
        )
        self._dropdown_was_shown = dropdown_will_show
        self._overlay_box_was_shown = overlay_box_identity
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
                word_match_ranges = None
                if current_selection_word:
                    word_match_ranges = [
                        (start, end) for start, end in
                        self._word_match_columns(index, current_selection_word)
                        if selection_range != (start, end)
                        or index != selection_bounds[0]
                    ]
                displayed = self._render_wrapped_segment(
                    index, text, seg_start, seg_end, is_last_segment,
                    is_current_line, selection_range, bracket_column,
                    apply_highlight, suggestion, word_match_ranges,
                )
                editor_row = f"{marker}{number}{displayed}"
                if is_first_segment:
                    display_length = len(self._display_text(text, index))
                    include_match = (
                        _INCLUDE_LINE_PATTERN.match(text)
                        if language in ("c", "cpp") else None
                    )
                    missing_include = (
                        include_match is not None
                        and self._include_target_missing(
                            include_match.group(1), include_match.group(2),
                            language,
                        )
                    )
                    broken_import = (
                        language == "python"
                        and self._import_line_broken(text, python_path)
                    )
                    too_long = (
                        file_settings["MAX_COLS_ENABLED"]
                        and display_length > file_settings["MAX_COLS"]
                    )
                    if missing_include or broken_import or too_long:
                        error_column = editor_col_offset + 1
                        ruler_overlay.append(
                            f"\x1b[{2 + row_offset};{error_column}H"
                            f"{theme.LINE_LENGTH_ERROR_COLOR}●"
                            f"{theme.BASE_STYLE}"
                        )
                    elif file_settings["MAX_COLS_ENABLED"]:
                        ruler_column = (
                            editor_col_offset + gutter_width + 1
                            + file_settings["MAX_COLS"]
                        )
                        if ruler_column <= terminal_width:
                            ruler_overlay.append(
                                f"\x1b[{2 + row_offset};{ruler_column}H"
                                f"{theme.RULER_COLOR}│{theme.BASE_STYLE}"
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
        if welcome_banner is not None:
            output.extend(self._render_welcome_banner(welcome_banner))
        if close_box is not None:
            output.extend(self._render_close_mini_box(close_box))
        if name_dialog_box is not None:
            output.extend(self._render_name_dialog_box(
                name_dialog_box, self._name_dialog
            ))
        if confirm_box is not None:
            output.extend(
                self._render_confirm_box(confirm_box, self._confirm_dialog)
            )
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
        if self.worktree_focused:
            # worktree_focused sits alongside self.mode (still
            # "visual" underneath) rather than being a mode of its
            # own - shown here as one anyway, so a click or `w` that
            # jumps focus there is never mistaken for still being in
            # the editor.
            mode_text = "Mode: Worktree"
        else:
            mode_text = f"Mode: {self.mode.title()}"
            if self.move_mode:
                mode_text += " (Move: j/k or Up/Down, m/Esc to stop)"
        output.append(mode_text)
        position_text = f"Line: {self.line + 1} Col: {self.column + 1}"
        position_column = max(1, terminal_width - len(position_text) + 1)
        output.append(
            f"\x1b[{terminal_height};{position_column}H{position_text}"
        )

        output.append("\x1b[?25l")
        if name_dialog_box is not None:
            inner_width = name_dialog_box["width"] - 4
            value = self._name_dialog["value"]
            visible_len = min(len(value), inner_width)
            cursor_row = 2 + name_dialog_box["top_row_offset"] + 2
            # `input_row` is built as "│ " + value + ... - two cells
            # (the border, then its own leading space) before the
            # first character of the typed value, so the cursor - one
            # past the last typed character, not on top of it - sits
            # 3 (not 2) columns past the box's own left edge.
            cursor_column = name_dialog_box["left"] + 3 + visible_len
        elif self.worktree_focused:
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
                    self.lines[self.line][cursor_seg_start:self.column],
                    self.line, cursor_seg_start,
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
            self._line_row_count(index, content_width)
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
            rows_needed -= self._line_row_count(
                self.viewport_top, content_width
            )
            self.viewport_top += 1

    def _raw_column_for_display_column(
        self, line_index, seg_start, seg_end, target_display_column
    ):
        """The raw character index within `[seg_start, seg_end)` of
        `self.lines[line_index]` whose *display* column (accounting
        for elastic tabs, same as everywhere else this matters)
        reaches `target_display_column` - or `seg_end` if the click
        landed past the end of the visible text, so clicking in the
        empty space to the right of a short line still places the
        cursor at the end of it, like every other editor does."""
        display_column = 0
        for raw_index in range(seg_start, seg_end):
            char_width = self._character_display_width(line_index, raw_index)
            if display_column + char_width > target_display_column:
                return raw_index
            display_column += char_width
        return seg_end
