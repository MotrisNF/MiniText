"""Mouse event dispatch: resolving a screen (column, row) to whatever
region of the last-rendered frame it lands on (`_mouse_target`), and
what a click, drag, release, or wheel event on each region actually
does (`_handle_mouse_event`) - split out of rendering.py, which still
owns the `self._mouse_state.layout` snapshot this reads every event
against."""

import time

# Two presses this close together, landing on the exact same cell, are
# a double-click - selecting the word there (see _handle_mouse_event's
# MOUSE_PRESS handling) instead of just moving the cursor like a
# single click does.
DOUBLE_CLICK_SECONDS = 0.4


class MouseState:
    """Hover/drag/click tracking shared by worktree.py, mouse.py,
    dialogs.py, rendering.py, and commands.py - grouped into one
    object instead of loose `self._hovered_*`/`self._*_drag_*`/
    `self._mouse_layout`/`self._last_click` attributes on TextEditor."""

    def __init__(self):
        # A snapshot of the geometry _render() last computed, resolved
        # against on every mouse event instead of recomputing it here.
        self.layout = None
        self.last_click = None
        self.worktree_button = None
        self.tab_close = None
        self.close_mini = False
        self.worktree_delete = None
        self.worktree_rename = None
        self.worktree_row = None
        self.drag_origin = None
        self.drag_target = None
        self.ctrl_drag_active = False


class MouseMixin:

    def _mouse_target(self, column, row):
        """What's at 1-indexed screen (column, row) as of the last
        render - one of ("tab_bar", tab_index_or_None, is_close),
        ("mode_bar", None), ("status", None), ("sidebar",
        row_within_panel, column0), ("sidebar_button", button_index),
        ("close_mini_button", None), ("run_output",
        row_within_output), or ("editor", line_index, raw_column);
        None if it doesn't land on anything the last frame actually
        drew (past the end of the file, say). Resolved against
        `self._mouse_state.layout`, a snapshot of the geometry `_render()`
        last computed, rather than recomputing any of it here."""
        layout = self._mouse_state.layout
        if layout is None:
            return None
        if row == 1:
            column0 = column - 1 - layout["editor_col_offset"]
            if column0 < 0:
                return None
            tab_index, is_close = self._tab_target_at(column0)
            return ("tab_bar", tab_index, is_close)
        if row == layout["terminal_height"]:
            return ("mode_bar", None)
        if row == layout["input_row"]:
            return ("status", None)
        row_offset = row - 2
        if row_offset < 0:
            return None
        column0 = column - 1
        close_box = layout.get("close_mini_box")
        if (
            close_box is not None
            and close_box["row_offset_start"]
            <= row_offset <= close_box["row_offset_end"]
            and close_box["col_start"]
            <= column0 <= close_box["col_end"]
        ):
            return ("close_mini_button", None)
        if layout["sidebar_visible"] and column0 < layout["editor_col_offset"]:
            button_index = self._worktree_button_index_at(
                row_offset, layout["visible_rows"]
            )
            if button_index is not None:
                return ("sidebar_button", button_index)
            return ("sidebar", row_offset, column0)
        if layout["run_visible"] and row_offset == layout["editor_rows"]:
            return ("run_divider", None)
        if layout["run_visible"] and row_offset > layout["editor_rows"]:
            return ("run_output", row_offset - layout["editor_rows"] - 1)
        row_descriptors = layout["row_descriptors"]
        if row_offset >= len(row_descriptors):
            return None
        line_index, seg_start, seg_end, _, _ = row_descriptors[row_offset]
        text_column0 = max(
            0,
            column0 - layout["editor_col_offset"] - layout["gutter_width"],
        )
        raw_column = self._raw_column_for_display_column(
            line_index, seg_start, seg_end, text_column0
        )
        return ("editor", line_index, raw_column)

    def _handle_mouse_event(self, key):
        """Dispatches one MOUSE_* event (see terminal.py's
        _read_mouse_event) to whichever region of the last-rendered
        frame it landed on - see `_reset_focus_for_click` for what a
        code-area or tab click does to whatever was focused before
        it."""
        kind, _, rest = key.partition(":")
        column_text, _, remainder = rest.partition(":")
        row_text, _, modifier = remainder.partition(":")
        try:
            column, row = int(column_text), int(row_text)
        except ValueError:
            return
        ctrl_held = modifier == "ctrl"
        target = self._mouse_target(column, row)
        if target is None:
            if kind == "MOUSE_MOVE":
                self._mouse_state.worktree_button = None
                self._mouse_state.tab_close = None
                self._mouse_state.close_mini = False
                self._mouse_state.worktree_delete = None
                self._mouse_state.worktree_rename = None
                self._mouse_state.worktree_row = None
            elif kind == "MOUSE_DRAG":
                self._mouse_state.drag_target = None
            elif kind == "MOUSE_RELEASE":
                self._mouse_state.drag_origin = None
                self._mouse_state.drag_target = None
                self._mouse_state.ctrl_drag_active = False
            return
        region = target[0]
        if kind == "MOUSE_RELEASE" and region != "sidebar":
            # A Ctrl+drag paint-select (armed below, on a sidebar
            # MOUSE_PRESS) releasing outside the sidebar it started
            # in - same "just stop" as releasing inside it, just
            # without sidebar's own MOUSE_RELEASE branch to do it.
            self._mouse_state.ctrl_drag_active = False
        if kind == "MOUSE_MOVE":
            self._mouse_state.worktree_button = (
                target[1] if region == "sidebar_button" else None
            )
            self._mouse_state.tab_close = (
                target[1] if region == "tab_bar" and target[2] else None
            )
            self._mouse_state.close_mini = region == "close_mini_button"
            self._mouse_state.worktree_delete = (
                self._worktree_delete_hit_test(target[1], target[2])
                if region == "sidebar" else None
            )
            self._mouse_state.worktree_rename = (
                self._worktree_rename_hit_test(target[1], target[2])
                if region == "sidebar" else None
            )
            hovered_entry = (
                self._worktree_entry_at_row(target[1])
                if region == "sidebar" else None
            )
            self._mouse_state.worktree_row = (
                hovered_entry[0] if hovered_entry is not None else None
            )
            return
        if region == "sidebar_button":
            if kind == "MOUSE_PRESS":
                self._activate_worktree_button(target[1])
            return
        if region == "close_mini_button":
            if kind == "MOUSE_PRESS":
                self._close_current_tab()
            return
        if region == "sidebar":
            if kind == "MOUSE_PRESS":
                delete_index = self._worktree_delete_hit_test(
                    target[1], target[2]
                )
                rename_index = self._worktree_rename_hit_test(
                    target[1], target[2]
                )
                if delete_index is not None:
                    self._worktree_delete_by_index(delete_index)
                elif rename_index is not None:
                    self._worktree_rename_by_index(rename_index)
                else:
                    entry = self._worktree_entry_at_row(target[1])
                    # A Ctrl+press starts a paint-select drag instead
                    # of the plain drag's "move this entry" one - see
                    # bugs_conocidos.md: "Ctrl + arrastrar ... permite
                    # seleccion multiple" - so it must never also arm
                    # _worktree_drag_origin, or releasing it later
                    # would try to move whatever was under the mouse
                    # on top of having just multi-selected it.
                    self._mouse_state.ctrl_drag_active = (
                        ctrl_held and entry is not None
                    )
                    self._mouse_state.drag_origin = (
                        entry[0]
                        if entry is not None and not ctrl_held
                        and entry[0] != self.worktree.root else None
                    )
                    self._handle_worktree_click(target[1], ctrl_held)
            elif kind == "MOUSE_DRAG":
                if self._mouse_state.ctrl_drag_active:
                    self._worktree_ctrl_drag_select(target[1])
                else:
                    self._update_worktree_drag_status(target[1])
            elif kind == "MOUSE_RELEASE":
                if self._mouse_state.ctrl_drag_active:
                    self._mouse_state.ctrl_drag_active = False
                else:
                    self._handle_worktree_drop(target[1])
            elif kind == "MOUSE_WHEEL_UP":
                self.worktree.cursor = max(0, self.worktree.cursor - 3)
            elif kind == "MOUSE_WHEEL_DOWN":
                entries = self._worktree_entries()
                if entries:
                    self.worktree.cursor = min(
                        len(entries) - 1, self.worktree.cursor + 3
                    )
            return
        if region == "editor":
            line_index, raw_column = target[1], target[2]
            column_clamped = min(raw_column, len(self.lines[line_index]))
            if kind == "MOUSE_PRESS":
                self._reset_focus_for_click()
                now = time.monotonic()
                previous_click = self._mouse_state.last_click
                self._mouse_state.last_click = (
                    line_index, column_clamped, now
                )
                word_bounds = None
                if (
                    previous_click is not None
                    and previous_click[0] == line_index
                    and previous_click[1] == column_clamped
                    and now - previous_click[2] <= DOUBLE_CLICK_SECONDS
                ):
                    word_bounds = self._word_bounds_at(
                        line_index, column_clamped
                    )
                if word_bounds is not None:
                    start, end = word_bounds
                    self.line = line_index
                    self.column = end
                    self.selection_anchor = (line_index, start)
                else:
                    self.line = line_index
                    self.column = column_clamped
                    self.selection_anchor = (self.line, self.column)
            elif kind == "MOUSE_DRAG":
                self.line = line_index
                self.column = column_clamped
            elif kind == "MOUSE_WHEEL_UP":
                self.selection_anchor = None
                self._move_vertical(-3)
            elif kind == "MOUSE_WHEEL_DOWN":
                self.selection_anchor = None
                self._move_vertical(3)
            return
        if region == "tab_bar":
            if kind == "MOUSE_PRESS" and target[1] is not None:
                tab_index, is_close = target[1], target[2]
                self._reset_focus_for_click()
                if is_close:
                    self._close_tab_by_index(tab_index)
                else:
                    self._switch_to_tab(tab_index)
            return
        if region == "run_output":
            if kind == "MOUSE_WHEEL_UP":
                self._scroll_run_output("UP")
            elif kind == "MOUSE_WHEEL_DOWN":
                self._scroll_run_output("DOWN")

    def _reset_focus_for_click(self):
        """A click meant to land in the code area or on a tab always
        wins over whatever was focused before it - the worktree panel,
        the :run/:lint/:cmd output panel, Command/Search mode - on the
        theory that it always means "take me there now", the same
        reasoning `Esc` already follows, just spelled with a mouse
        instead of a key. Insert mode is the one exception: a click
        there only moves the cursor, it never kicks you out of typing
        - Esc is still the only way out of Insert. Also where
        `AUTOSAVE` (mouse mode only) saves the current file, since
        every click that lands here is exactly the "the user just
        moved on to something else" moment that setting means to
        catch."""
        if self.run_panel.focused:
            self._stop_run()
        self._release_worktree_focus()
        self.command = None
        self.search_query = None
        self._highlight_query = None
        if self.mode != "insert":
            self.mode = "visual"
        self._maybe_autosave()
