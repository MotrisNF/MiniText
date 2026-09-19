"""Core buffer mutations: cursor movement, undo/redo, selection,
insert/backspace/delete (with auto-closing-pair awareness),
paste, and the auto-indenting Enter."""

import re
import time

import theme

PAIRS = {"(": ")", "[": "]", "{": "}", "'": "'", '"': '"'}
BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
CLOSING_TO_OPENING = {value: key for key, value in BRACKET_PAIRS.items()}
QUOTE_CHARACTERS = {"'", '"'}
UNDO_HISTORY_LIMIT = 1000
# Leading keywords a line has to start with for a trailing `:` to
# really mean "opens a new indented block" - `else:`, `case 1:`,
# `def foo():`, ... - rather than just happening to end in a colon,
# the way a comment ("# note:"), a docstring line (":param x:"), or a
# dict/annotation can too. Not a real parser, just enough to rule out
# the common non-block cases without tracking strings/comments.
_BLOCK_OPENING_KEYWORDS = {
    "if", "elif", "else", "for", "while", "try", "except", "finally",
    "with", "def", "class", "match", "case", "default",
}
_LEADING_WORD_PATTERN = re.compile(r"[A-Za-z_]\w*")
# How long a one-off status message ("Saved", "Cancelled", "Created
# ...", ...) stays on screen before clearing itself, instead of
# sitting there until some later message happens to overwrite it.
STATUS_TIMEOUT_SECONDS = 4


def _is_word_character(character):
    """Whether `character` is part of a "word" for double-click
    selection and the highlight-other-occurrences feature - an
    identifier character (letters, digits, underscore), same as
    what makes up a name in every language Mini highlights. Anything
    else (whitespace, punctuation, brackets, quotes) is a boundary."""
    return character.isalnum() or character == "_"


def _indent_unit(file_name):
    """One level of new indentation, per ~/.minirc's INDENT_WITH_TABS
    and TAB_SIZE - or `file_name`'s own [filetype:.ext] override of
    either, if it has one: a tab character, or TAB_SIZE spaces. Only
    decides what gets *added* for a new indent level - carrying over
    a line's *existing* indentation (whatever mix of characters it
    already has) is handled separately, verbatim, by
    `_leading_whitespace`."""
    settings = theme.settings_for(file_name)
    return "\t" if settings["INDENT_WITH_TABS"] else " " * settings["TAB_SIZE"]


def _opens_a_block(before):
    """Whether `before` (the current line up to the cursor, already
    known to end in a trailing `:`) really looks like it opens a new
    block - starts with one of `_BLOCK_OPENING_KEYWORDS` - instead of
    just happening to end in a colon."""
    match = _LEADING_WORD_PATTERN.match(before.lstrip())
    return match is not None and match.group() in _BLOCK_OPENING_KEYWORDS


class BufferEditMixin:

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        """Every `self.status = "..."` assignment anywhere in the
        editor goes through here, timestamping it - the single choke
        point that makes the message expire on its own (see
        `_render`'s own check of `_status_set_at`) without having to
        touch each of the (many) places that set one."""
        self._status = value
        self._status_set_at = time.monotonic() if value else None

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

    def _snapshot(self):
        # undo_stack/redo_stack are deques capped at UNDO_HISTORY_LIMIT,
        # so the oldest entry is dropped in O(1) once full - a plain
        # list would need an O(n) shift for that on every single
        # keystroke past the cap, which is exactly what made continuous
        # fast typing get laggier the longer a session went on.
        self.undo_stack.append((list(self.lines), self.line, self.column))
        self.redo_stack.clear()
        self.modified = True
        # Every real mutation happens at or after `self.line` (the one
        # exception, joining into the *previous* line on a column-0
        # Backspace, still only reaches back one line) - so entries
        # before that are still valid; only entries from here on need
        # recomputing, lazily, the next time they're actually rendered
        # (see rendering.py's `_comment_state_for`).
        del self._comment_state[max(0, self.line - 1):]

    def _swap_history(
        self, source_stack, dest_stack, empty_status, done_status
    ):
        """Shared core of `_undo`/`_redo`: they're mirror images of
        each other (which stack is the source and which is the
        destination is the only real difference), so this is the one
        place that snapshots the current state onto `dest_stack`
        before restoring the top of `source_stack`."""
        if not source_stack:
            self.status = empty_status
            return
        dest_stack.append((list(self.lines), self.line, self.column))
        self.lines, self.line, self.column = source_stack.pop()
        self.selection_anchor = None
        self.modified = True
        self.status = done_status
        # An undo/redo can restore arbitrarily different content from
        # anywhere in history - unlike a plain edit, there's no single
        # "everything before this line is still valid" line to keep,
        # so the whole cache is dropped and lazily rebuilt on demand.
        self._comment_state = []

    def _undo(self):
        self._swap_history(
            self.undo_stack, self.redo_stack, "Nothing to undo", "Undone"
        )

    def _redo(self):
        self._swap_history(
            self.redo_stack, self.undo_stack, "Nothing to redo", "Redone"
        )

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

    def _word_bounds_at(self, line_index, column):
        """The (start, end) raw-column bounds of the word touching
        column `column` of `self.lines[line_index]` - the character
        right at `column` first, then the one just before it (so a
        double-click landing exactly on a word's trailing edge, where
        the cursor itself would sit, still selects that word instead
        of nothing) - or None if neither side is a word character."""
        text = self.lines[line_index]
        probe = column
        if not (0 <= probe < len(text) and _is_word_character(text[probe])):
            probe = column - 1
            if not (
                0 <= probe < len(text) and _is_word_character(text[probe])
            ):
                return None
        start = probe
        while start > 0 and _is_word_character(text[start - 1]):
            start -= 1
        end = probe + 1
        while end < len(text) and _is_word_character(text[end]):
            end += 1
        return start, end

    def _current_selection_word(self):
        """The exact text of the current selection if it spans one
        whole word - one line, entirely word characters, flanked by a
        non-word character (or the line's edge) on both sides - else
        None. Deliberately blind to *how* the selection was made
        (double-click, a mouse drag released, Ctrl+arrow selection):
        the same check drives the highlight-other-occurrences feature
        uniformly for all three, recomputed fresh every render so it
        appears and disappears with the selection itself, with no
        separate state of its own to fall out of sync."""
        bounds = self._selection_bounds()
        if bounds is None:
            return None
        start_line, start_column, end_line, end_column = bounds
        if start_line != end_line:
            return None
        text = self.lines[start_line]
        word = text[start_column:end_column]
        if not word or not all(_is_word_character(c) for c in word):
            return None
        if start_column > 0 and _is_word_character(text[start_column - 1]):
            return None
        if end_column < len(text) and _is_word_character(text[end_column]):
            return None
        return word

    def _word_match_columns(self, line_index, word):
        """Every (start, end) raw-column span on `self.lines
        [line_index]` where `word` occurs as a whole word - exact,
        case-sensitive text, flanked by a non-word character or the
        line's edge on both sides, same rule `_current_selection_word`
        itself is checked against."""
        text = self.lines[line_index]
        columns = []
        search_from = 0
        word_length = len(word)
        while True:
            found = text.find(word, search_from)
            if found == -1:
                break
            end = found + word_length
            before_ok = found == 0 or not _is_word_character(text[found - 1])
            after_ok = end == len(text) or not _is_word_character(text[end])
            if before_ok and after_ok:
                columns.append((found, end))
            search_from = found + 1
        return columns

    def _substring_match_columns(self, line_index, query):
        """Every (start, end) raw-column span on `self.lines
        [line_index]` where `query` occurs, plain substring, case-
        insensitive - the same matching rule `_find_next`'s own search
        already uses, unlike `_word_match_columns`'s whole-word,
        case-sensitive one: a search for "urn" is meant to find it
        inside "return" or "turn" too, not just as its own identifier."""
        text = self.lines[line_index].lower()
        needle = query.lower()
        if not needle:
            return []
        columns = []
        search_from = 0
        needle_length = len(needle)
        while True:
            found = text.find(needle, search_from)
            if found == -1:
                break
            columns.append((found, found + needle_length))
            search_from = found + 1
        return columns

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

    def _move_current_line_or_selection(self, direction):
        """Moves the current line - or, with an active selection,
        every line it spans (start to end, the same range
        `_delete_selection`/`_selected_text` already use) - one
        position up (`direction=-1`) or down (`direction=1`), trading
        places with whichever single line sits immediately in that
        direction. A no-op at either edge of the file - there's
        nothing to trade places with past it. The cursor (and the
        selection, if there is one) always shifts by exactly one line
        along with whatever moved, since a swap with one neighbor is
        the only kind of move this ever makes."""
        bounds = self._selection_bounds()
        if bounds is not None:
            start_line, _, end_line, _ = bounds
        else:
            start_line = end_line = self.line
        if direction < 0 and start_line == 0:
            return
        if direction > 0 and end_line == len(self.lines) - 1:
            return
        self._snapshot()
        if direction < 0:
            neighbor = self.lines.pop(start_line - 1)
            self.lines.insert(end_line, neighbor)
        else:
            neighbor = self.lines.pop(end_line + 1)
            self.lines.insert(start_line, neighbor)
        self.line += direction
        if bounds is not None:
            anchor_line, anchor_column = self.selection_anchor
            self.selection_anchor = (anchor_line + direction, anchor_column)

    def _paste(self, text):
        self.selection_anchor = None
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
        # A plain mouse click arms `selection_anchor` at the cursor
        # (see mouse.py) so a *drag* right after it can select - but
        # typing instead of dragging must drop it, or it stays fixed
        # at the click point while the cursor moves ahead with every
        # character typed, turning the newly typed text itself into
        # what looks like a growing selection.
        self.selection_anchor = None
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
        self.selection_anchor = None
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
            start = self._soft_tab_backspace_start(current_line) \
                if not delete_pair and removed_character == " " \
                else self.column - 1
            self.lines[self.line] = (
                current_line[:start] + current_line[end:]
            )
            self.column = start
        elif self.line:
            previous_line = self.lines[self.line - 1]
            self.column = len(previous_line)
            self.lines[self.line - 1] = (
                previous_line + self.lines.pop(self.line)
            )
            self.line -= 1

    def _soft_tab_backspace_start(self, current_line):
        """Where a Backspace right after a run of leading-indentation
        spaces should land: `TAB_SIZE` columns back, as one unit,
        rather than the usual single character - the same size Tab
        itself inserts as one unit (`_indent_unit`) when
        INDENT_WITH_TABS is False. Only applies inside the line's own
        leading whitespace (everything up to the cursor is space-only)
        and only when the whole block being removed is spaces aligned
        to a tab stop; anything else (an actual `\\t` character,
        mid-line alignment spaces, an uneven column) falls back to
        plain single-character deletion."""
        settings = theme.settings_for(self.file_name)
        tab_size = settings["TAB_SIZE"]
        if (
            settings["INDENT_WITH_TABS"]
            or self.column < tab_size
            or self.column % tab_size
            or not current_line[:self.column].isspace()
        ):
            return self.column - 1
        block_start = self.column - tab_size
        if current_line[block_start:self.column] == " " * tab_size:
            return block_start
        return self.column - 1

    def _delete_forward(self):
        self.selection_anchor = None
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
    def _leading_whitespace(line):
        """`line`'s own leading indentation, verbatim (spaces, tabs,
        or a mix) - auto-indent carries this over as-is; only a *new*
        level added on top of it goes through `_indent_unit`, per the
        configured style."""
        count = 0
        for character in line:
            if character not in (" ", "\t"):
                break
            count += 1
        return line[:count]

    def _new_line(self):
        self.selection_anchor = None
        self._snapshot()
        current_line = self.lines[self.line]
        before = current_line[:self.column]
        after = current_line[self.column:]
        indent = self._leading_whitespace(current_line)
        between_brackets = (
            before and before[-1] in BRACKET_PAIRS
            and after and after[0] == BRACKET_PAIRS[before[-1]]
        )
        if between_brackets:
            inner_indent = indent + _indent_unit(self.file_name)
            self.lines[self.line] = before
            self.lines.insert(self.line + 1, inner_indent)
            self.lines.insert(self.line + 2, indent + after)
            self.line += 1
            self.column = len(inner_indent)
            return
        if before.rstrip().endswith(":") and _opens_a_block(before):
            indent += _indent_unit(self.file_name)
        self.lines[self.line] = before
        self.lines.insert(self.line + 1, indent + after)
        self.line += 1
        self.column = len(indent)
