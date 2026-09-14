"""Core buffer mutations: cursor movement, undo/redo, selection,
insert/backspace/delete (with auto-closing-pair awareness),
paste, and the auto-indenting Enter."""

import theme

PAIRS = {"(": ")", "[": "]", "{": "}", "'": "'", '"': '"'}
BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
CLOSING_TO_OPENING = {value: key for key, value in BRACKET_PAIRS.items()}
QUOTE_CHARACTERS = {"'", '"'}
UNDO_HISTORY_LIMIT = 1000


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


class BufferEditMixin:

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
        if before.rstrip().endswith(":"):
            indent += _indent_unit(self.file_name)
        self.lines[self.line] = before
        self.lines.insert(self.line + 1, indent + after)
        self.line += 1
        self.column = len(indent)
