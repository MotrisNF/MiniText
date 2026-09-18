"""Minimal, dependency-free harness for exercising BufferEditMixin
methods directly, without a real terminal - just enough state for
_backspace/_new_line/etc. to run against. Not shipped/installed;
development-only, see README-less tests/ directory."""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))

from editing import BufferEditMixin  # noqa: E402


class FakeBuffer(BufferEditMixin):
    def __init__(self, lines, line=0, column=0, file_name="file.py"):
        self.lines = list(lines)
        self.line = line
        self.column = column
        self.file_name = file_name
        self.undo_stack = []
        self.redo_stack = []
        self.modified = False
        self.selection_anchor = None
        self.pending_count = ""
        self.count_locked = False
        self._comment_state = []
