"""The worktree file explorer panel: listing, expanding/collapsing
directories, creating/deleting entries, and rendering its rows -
everything except the key handling that drives it (that stays in the
main run() loop, since it needs to route between the worktree, the
editor, and the other focus targets)."""

import os
import shutil

import terminal
import theme

# Fixed ANSI red, independent of the active theme - same value as
# rendering.py's own _CLOSE_HOVER_COLOR (a tab's × on hover), kept as
# its own copy here rather than imported to avoid a circular import
# (rendering.py already imports WORKTREE_WIDTH and friends from this
# module).
_DELETE_HOVER_COLOR = "\x1b[91m"

WORKTREE_WIDTH = 28
MIN_EDITOR_WIDTH = 20
WORKTREE_SEPARATOR_WIDTH = 2
# Mouse-only buttons drawn at the bottom of the panel (see
# _worktree_body_lines/_worktree_button_index_at/
# _activate_worktree_button) - one row each, in this order, each
# comfortably under WORKTREE_WIDTH on its own. Closing a tab moved to
# the × on the tab itself (see rendering.py's _tab_bar_line) - a
# worktree entry has nothing to do with which *tab* is open.
_WORKTREE_BUTTON_LABELS = ("+ New file", "+ New folder")


class WorktreePanelMixin:

    def _worktree_root_label(self):
        return os.path.basename(
            self.worktree_root.rstrip(os.sep)
        ) or self.worktree_root

    def _worktree_entries(self):
        """The flattened, currently-visible worktree listing (one
        entry per row the panel draws) - `entries[0]` is always
        `self.worktree_root` itself, a directory entry like any
        other except it can't be deleted or renamed from here, and
        collapsing it (`self.worktree_root_collapsed`, not part of
        `worktree_expanded` since it's a single fixed root rather
        than a set of arbitrarily many directories) hides the whole
        rest of the tree at once - the "collapse everything and come
        back to creating files at the top level" case `_worktree_
        collapse` already gives it, one level up from every other
        directory's own collapse. Rebuilding the real filesystem walk
        means walking the filesystem, so it's cached across renders -
        `_invalidate_worktree_cache` is called wherever something that
        should change the listing actually happens (expanding or
        collapsing a directory, creating, deleting, or renaming an
        entry, or (re)showing/focusing the panel, to also pick up
        changes made outside Mini)."""
        if self._worktree_entries_cache is not None:
            return self._worktree_entries_cache

        entries = [
            (self.worktree_root, self._worktree_root_label(), True, 0)
        ]
        show_hidden = self.worktree_show_hidden

        def walk(directory, depth):
            try:
                children = sorted(
                    os.scandir(directory),
                    key=lambda entry: (not entry.is_dir(), entry.name.lower())
                )
            except OSError:
                children = []
            for entry in children:
                if not show_hidden and entry.name.startswith("."):
                    continue
                entries.append((entry.path, entry.name, entry.is_dir(), depth))
                if entry.is_dir() and entry.path in self.worktree_expanded:
                    walk(entry.path, depth + 1)

        if not self.worktree_root_collapsed:
            walk(self.worktree_root, 1)
        self._worktree_entries_cache = entries
        return entries

    def _invalidate_worktree_cache(self):
        self._worktree_entries_cache = None

    def _release_worktree_focus(self):
        self.worktree_focused = False
        if self.worktree_visible_because_of_focus:
            self.worktree_visible = False
            self.worktree_visible_because_of_focus = False

    def _worktree_expand(self, entries):
        if not entries:
            return
        path, _, is_directory, _ = entries[self.worktree_cursor]
        if path == self.worktree_root:
            if self.worktree_root_collapsed:
                self.worktree_root_collapsed = False
                self._invalidate_worktree_cache()
            return
        if is_directory and path not in self.worktree_expanded:
            self.worktree_expanded.add(path)
            self.worktree_new_entry_dir = path
            self._invalidate_worktree_cache()

    def _worktree_collapse(self, entries):
        if not entries:
            return
        path, _, is_directory, _ = entries[self.worktree_cursor]
        if path == self.worktree_root:
            if not self.worktree_root_collapsed:
                self.worktree_root_collapsed = True
                self.worktree_new_entry_dir = self.worktree_root
                self._invalidate_worktree_cache()
            return
        if is_directory and path in self.worktree_expanded:
            self.worktree_expanded.discard(path)
            self.worktree_new_entry_dir = os.path.dirname(path)
            self._invalidate_worktree_cache()

    def _worktree_activate(self, entries):
        if not entries:
            return
        path, _, is_directory, _ = entries[self.worktree_cursor]
        if path == self.worktree_root:
            if self.worktree_root_collapsed:
                self._worktree_expand(entries)
            else:
                self._worktree_collapse(entries)
            return
        if is_directory:
            if path in self.worktree_expanded:
                self._worktree_collapse(entries)
            else:
                self._worktree_expand(entries)
            return
        existing_tab = self._find_tab_for_path(path)
        if existing_tab is not None:
            self._switch_to_tab(existing_tab)
        elif (
            self.file_name is None
            and self.lines == [""]
            and not self.modified
        ):
            self._load_file(path)
        else:
            self._open_in_new_tab(path)
        self._release_worktree_focus()

    def _worktree_create(self, is_directory):
        label = "New directory name" if is_directory else "New file name"
        name = self._prompt_name_dialog(label)
        if not name:
            self.status = "Cancelled"
            return
        new_path = os.path.join(self.worktree_new_entry_dir, name)
        try:
            if is_directory:
                os.mkdir(new_path)
            else:
                open(new_path, "x", encoding="utf-8").close()
        except OSError as error:
            self.status = f"Could not create '{name}': {error}"
            return
        self._invalidate_worktree_cache()
        self.status = f"Created {new_path}"

    def _worktree_rename(self, entries, index=None):
        """Renames the entry at `index` (`self.worktree_cursor` if not
        given) - keyboard `r`, or the row's own hover "✎" in mouse
        mode (see `_worktree_rename_hit_test`). Prompts for a new name
        pre-filled with the current one, then just `os.rename()`s it
        in place - moving it to a different directory is drag & drop's
        job, not this one's. A no-op (not even a confirmation) if the
        name comes back unchanged or empty, same "nothing to do"
        treatment `_worktree_create` gives an empty name."""
        if not entries:
            return
        index = self.worktree_cursor if index is None else index
        old_path, old_name, is_directory, _ = entries[index]
        if old_path == self.worktree_root:
            self.status = "Can't rename the worktree root"
            return
        new_name = self._prompt_name_dialog("New name", old_name)
        if not new_name or new_name == old_name:
            self.status = "Cancelled"
            return
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        try:
            os.rename(old_path, new_path)
        except OSError as error:
            self.status = f"Could not rename '{old_name}': {error}"
            return
        self._rewrite_worktree_path(old_path, new_path, is_directory)
        self._invalidate_worktree_cache()
        self.status = f"Renamed to {new_name}"

    def _rewrite_worktree_path(self, old_path, new_path, is_directory):
        """After an on-disk rename, updates every place a path might
        be cached by its old value: open tabs (including the active
        one, which lives on `self.file_name` rather than in `self.
        tabs` until the next tab switch syncs it - see rendering.py's
        `_tab_file_name`), `worktree_expanded`, `worktree_selected_
        entries`, and `worktree_new_entry_dir`. Renaming a directory
        moves everything nested under it too, so any of those that
        merely *started* with the old path (not just an exact match)
        gets that same prefix swapped, not just an identical one."""
        old_prefix = old_path + os.sep

        def rewrite(path):
            if path == old_path:
                return new_path
            if is_directory and path is not None and path.startswith(
                old_prefix
            ):
                return new_path + path[len(old_path):]
            return path

        self.worktree_expanded = {
            rewrite(path) for path in self.worktree_expanded
        }
        self.worktree_selected_entries = {
            rewrite(path) for path in self.worktree_selected_entries
        }
        self.worktree_new_entry_dir = rewrite(self.worktree_new_entry_dir)
        for index, state in enumerate(self.tabs):
            file_name = (
                self.file_name if index == self.active_tab
                else state["file_name"]
            )
            if file_name is None:
                continue
            rewritten = rewrite(file_name)
            if index == self.active_tab:
                self.file_name = rewritten
            else:
                state["file_name"] = rewritten

    def _prompt_name_dialog(self, label, initial_value=""):
        """Blocking modal prompt for a name, used by `_worktree_create`
        for both `Ctrl+F`/`Ctrl+D` and the matching worktree buttons,
        and by `_worktree_rename` (pre-filled with the entry's current
        name via `initial_value`, so renaming rarely means retyping
        the whole thing). Unlike `_read_command_line`'s own status-line
        prompt (still used for "Name of the file:" on `:w`/`:wq` with
        no file open), this one is drawn as its own box centered in
        the code area (see rendering.py's `render`/`_render_name_
        dialog_box`/`_name_dialog_box_geometry`) - `self._name_dialog`
        is what tells `render` to draw it at all, and carries the live
        typed value plus whether the mouse is hovering its own "×"
        (top-right corner of the box, mouse mode only) between
        renders, the same way `self.command`/`self.search_query`
        already carry their own state through every render while
        active. Returns the typed name, or "" if cancelled (`Esc`, or
        a click on the "×")."""
        self._name_dialog = {
            "label": label, "value": initial_value, "close_hovered": False,
        }
        try:
            while True:
                self._render()
                key = terminal.read_key()
                if key == "MOUSE_IGNORE":
                    continue
                if key.startswith("MOUSE_"):
                    if self._handle_name_dialog_mouse_event(key):
                        return ""
                    continue
                if key in ("\r", "\n"):
                    return self._name_dialog["value"].strip()
                if key == terminal.ESC:
                    return ""
                if key in ("\x7f", "\b"):
                    self._name_dialog["value"] = (
                        self._name_dialog["value"][:-1]
                    )
                elif len(key) == 1 and key.isprintable():
                    self._name_dialog["value"] += key
        finally:
            self._name_dialog = None

    def _handle_name_dialog_mouse_event(self, key):
        """Whether the click/move `key` (a MOUSE_* event - see
        terminal.py's own docstring on the ones it can produce) lands
        on `_prompt_name_dialog`'s own "×"; True only for a press
        that does, telling the dialog's loop to cancel. Hovering it
        (mouse mode's own cue for "this is clickable") is tracked the
        same way `_hovered_worktree_button` already is for the
        worktree panel's buttons, just kept on `self._name_dialog`
        itself since that's what `render` already threads through to
        `_render_name_dialog_box` for the "×"'s own hover styling."""
        kind, _, rest = key.partition(":")
        column_text, _, remainder = rest.partition(":")
        row_text, _, _modifier = remainder.partition(":")
        try:
            column, row = int(column_text), int(row_text)
        except ValueError:
            return False
        layout = self._mouse_layout
        box = layout.get("name_dialog_box") if layout else None
        if box is None or box["close_col"] is None:
            return False
        on_close = (
            row - 2 == box["row_offset_start"]
            and column - 1 == box["close_col"]
        )
        if kind == "MOUSE_MOVE":
            self._name_dialog["close_hovered"] = on_close
            return False
        return kind == "MOUSE_PRESS" and on_close

    def _confirm_batch_op(self, single_prompt, multi_prompt, names):
        """Shared confirm step for `_worktree_delete`/`_handle_
        worktree_drop`: a single-item op is confirmed with
        `single_prompt` as-is; more than one gets `multi_prompt`
        (already carrying the count) plus the item names as their own
        scrollable list (see commands.py's `_confirm`) instead of
        folded into the prompt text itself. Sets "Cancelled" on
        self.status - the one part of a decline both callers do
        identically - if the user says no."""
        if len(names) > 1:
            confirmed = self._confirm(multi_prompt, names)
        else:
            confirmed = self._confirm(single_prompt)
        if not confirmed:
            self.status = "Cancelled"
        return confirmed

    def _worktree_delete(self, entries, index=None):
        """Deletes the entry at `index` (`self.worktree_cursor` if not
        given) after confirming - or, if that entry is part of a
        Ctrl+click multi-selection (`self.worktree_selected_entries`),
        every selected entry together in one confirmation, the same
        "act on the whole selection" idea `_handle_worktree_drop`
        already uses for a drag."""
        if not entries:
            return
        index = self.worktree_cursor if index is None else index
        path, name, is_directory, _ = entries[index]
        if path == self.worktree_root:
            self.status = "Can't delete the worktree root"
            return
        if path in self.worktree_selected_entries:
            by_path = {entry[0]: entry for entry in entries}
            targets = [
                by_path[p] for p in sorted(self.worktree_selected_entries)
                if p in by_path
            ]
        else:
            targets = [(path, name, is_directory, None)]
        names = [target[1] for target in targets]
        kind = "folder" if targets[0][2] else "file"
        single_prompt = f"Delete {kind} '{names[0]}'? (y/n)"
        multi_prompt = f"Delete {len(targets)} items? (y/n)"
        if not self._confirm_batch_op(single_prompt, multi_prompt, names):
            return
        deleted, errors = [], []
        for target_path, target_name, target_is_directory, _ in targets:
            try:
                if target_is_directory:
                    shutil.rmtree(target_path)
                    self.worktree_expanded.discard(target_path)
                else:
                    os.remove(target_path)
                deleted.append(target_path)
            except OSError as error:
                errors.append(f"{target_name}: {error}")
        self.worktree_selected_entries -= set(deleted)
        if deleted:
            self._invalidate_worktree_cache()
        if errors:
            failed = "; ".join(errors)
            self.status = f"Deleted {len(deleted)}, failed: {failed}"
        elif len(deleted) > 1:
            self.status = f"Deleted {len(deleted)} items"
        elif deleted and self.file_name == deleted[0]:
            self.status = f"Deleted {deleted[0]} (still open here, unsaved)"
        elif deleted:
            self.status = f"Deleted {deleted[0]}"
        if index <= self.worktree_cursor:
            self.worktree_cursor = max(0, self.worktree_cursor - 1)

    def _worktree_delete_by_index(self, index):
        """The worktree row's own hover "×" (mouse mode only, see
        `_worktree_delete_hit_test`) - deletes that specific entry
        directly (or its whole multi-selection, if it's part of one -
        see `_worktree_delete`), independent of whatever's currently
        selected (`self.worktree_cursor`), same confirm-then-delete
        path as pressing `Delete` on the selected one."""
        self._worktree_delete(self._worktree_entries(), index)

    def _worktree_rename_by_index(self, index):
        """The worktree row's own hover "✎" (mouse mode only, see
        `_worktree_rename_hit_test`) - renames that specific entry
        directly, independent of whatever's currently selected
        (`self.worktree_cursor`), same as `_worktree_delete_by_index`
        does for the delete "×"."""
        self._worktree_rename(self._worktree_entries(), index)

    def _worktree_row_index(self, panel_row, entries):
        """The `entries` index `panel_row` (0-indexed from the
        panel's own top - `entries[0]` is the worktree root itself,
        there's no separate non-entry header row above it any more)
        resolves to, or None if it isn't a real entry row at all (a
        blank filler row past the last one, or a button row) - the
        one bounds check every mouse-driven worktree interaction
        (click, hover, drag, delete-×/rename-✎) needs before turning
        a screen row into a real entry."""
        if panel_row < 0 or not entries:
            return None
        entry_index = self.worktree_scroll + panel_row
        if entry_index >= len(entries):
            return None
        return entry_index

    def _worktree_entry_at_row(self, panel_row):
        """The (path, is_directory) of the real entry at `panel_row`
        (0-indexed from the panel's own top - same convention as
        `_handle_worktree_click`), or None if that row isn't a real
        entry."""
        entries = self._worktree_entries()
        entry_index = self._worktree_row_index(panel_row, entries)
        if entry_index is None:
            return None
        path, _, is_directory, _ = entries[entry_index]
        return path, is_directory

    def _worktree_ctrl_drag_select(self, panel_row):
        """Adds whichever entry sits at `panel_row` to the multi-
        selection - called on every MOUSE_DRAG while a Ctrl+press-
        started paint-select (`self._worktree_ctrl_drag_active`, armed
        in `_handle_mouse_event`) is in progress, so dragging with
        Ctrl held paints a selection across every row the mouse passes
        over (see bugs_conocidos.md: "Ctrl + arrastrar raton ...
        permite seleccion multiple de archivos"). Only ever adds -
        never toggles back off, so passing back over an already-
        selected row mid-drag can't accidentally deselect it - and is
        a silent no-op past the last real entry."""
        entry = self._worktree_entry_at_row(panel_row)
        if entry is not None and entry[0] != self.worktree_root:
            self.worktree_selected_entries.add(entry[0])

    def _update_worktree_drag_status(self, panel_row):
        """Live feedback while dragging a worktree entry (mouse mode
        only, see `_handle_worktree_drop`) - a status-line preview of
        where releasing right now would move it, plus `self.
        _worktree_drag_target` (the row `_worktree_body_lines` paints
        as the drop zone), both updated on every MOUSE_DRAG the mouse
        is still over the sidebar for. No-op with nothing currently
        being dragged, or while hovering the dragged entry's own row
        (dropping something on itself is always a no-op, see
        `_handle_worktree_drop`) - either way `_worktree_drag_target`
        is cleared, so nothing stays highlighted as a bogus drop
        zone."""
        if self._worktree_drag_origin is None:
            return
        entry = self._worktree_entry_at_row(panel_row)
        if entry is None or entry[0] == self._worktree_drag_origin:
            self._worktree_drag_target = None
            return
        target_path, is_directory = entry
        self._worktree_drag_target = target_path
        destination_dir = (
            target_path if is_directory else os.path.dirname(target_path)
        )
        label = os.path.basename(destination_dir) or destination_dir
        origin_name = os.path.basename(self._worktree_drag_origin)
        self.status = f"Moving '{origin_name}': release to move into '{label}'"

    def _handle_worktree_drop(self, panel_row):
        """Finishes a worktree drag started by a MOUSE_PRESS on some
        entry's row (`self._worktree_drag_origin`, armed in
        `_handle_mouse_event`) and released on `panel_row`. Dropping
        on a directory moves the dragged entry (entries, if it was
        part of a Ctrl+click multi-selection - see
        `_handle_worktree_click`) inside it; dropping on a file moves
        it to that file's own parent directory instead - either way
        after confirming. Releasing on the very entry that was picked
        up (a plain click-and-release, with no real drag in between,
        included - press and release then land on the exact same row)
        is always a silent no-op, never a confirmation prompt for
        "moving" something nowhere."""
        origin = self._worktree_drag_origin
        self._worktree_drag_origin = None
        self._worktree_drag_target = None
        if origin is None:
            return
        entry = self._worktree_entry_at_row(panel_row)
        if entry is None:
            return
        target_path, target_is_directory = entry
        if target_path == origin:
            return
        destination_dir = (
            target_path if target_is_directory
            else os.path.dirname(target_path)
        )
        if destination_dir == os.path.dirname(origin):
            return
        sources = (
            sorted(self.worktree_selected_entries)
            if origin in self.worktree_selected_entries else [origin]
        )
        names = [os.path.basename(path) for path in sources]
        destination_label = (
            os.path.basename(destination_dir) or destination_dir
        )
        single_prompt = f"Move {names[0]} to '{destination_label}'? (y/n)"
        multi_prompt = (
            f"Move {len(names)} items to '{destination_label}'? (y/n)"
        )
        if not self._confirm_batch_op(single_prompt, multi_prompt, names):
            return
        moved, errors = [], []
        for source in sources:
            destination = os.path.join(
                destination_dir, os.path.basename(source)
            )
            try:
                shutil.move(source, destination)
                moved.append(source)
            except (OSError, shutil.Error) as error:
                errors.append(f"{os.path.basename(source)}: {error}")
        self.worktree_selected_entries -= set(moved)
        if moved:
            self._invalidate_worktree_cache()
        if errors:
            self.status = f"Moved {len(moved)}, failed: {'; '.join(errors)}"
        else:
            self.status = f"Moved {len(moved)} item(s) to {destination_dir}"

    def _worktree_icon_hit_test(self, row_offset, column0, col_start, col_end):
        """Shared core of `_worktree_delete_hit_test`/`_worktree_
        rename_hit_test`: the entry index under (row_offset, column0)
        if it falls within a hover icon's own [col_start, col_end)
        zone and isn't the worktree root - neither icon ever applies
        to that row (see `_worktree_delete`/`_worktree_rename`'s own
        guards) - None everywhere else, including a blank filler or
        button row past the real entries."""
        if not theme.MOUSE_ENABLED:
            return None
        if not (col_start <= column0 < col_end):
            return None
        entries = self._worktree_entries()
        index = self._worktree_row_index(row_offset, entries)
        if index is None or entries[index][0] == self.worktree_root:
            return None
        return index

    def _worktree_delete_hit_test(self, row_offset, column0):
        """The worktree entry index under (row_offset, column0) if it
        falls on that row's own hover "×" (the last 2 display columns
        of the panel, mouse mode only - see `_worktree_body_lines`);
        None everywhere else."""
        return self._worktree_icon_hit_test(
            row_offset, column0, WORKTREE_WIDTH - 2, WORKTREE_WIDTH
        )

    def _worktree_rename_hit_test(self, row_offset, column0):
        """Like `_worktree_delete_hit_test`, for the row's own hover
        "✎" - the 2 display columns immediately to the left of the
        delete "×"'s own zone."""
        return self._worktree_icon_hit_test(
            row_offset, column0, WORKTREE_WIDTH - 4, WORKTREE_WIDTH - 2
        )

    def _handle_worktree_click(self, panel_row, ctrl_held=False):
        """A mouse click at `panel_row` (0-indexed from the top of the
        sidebar - row 0 is the worktree root itself, matching
        `_worktree_body_lines`'s own layout) always focuses the panel
        first, the same as pressing `w` (including picking up changes
        made outside Mini, but only on the transition into focus, not
        on every click while already there - same as `w` itself).
        Clicking an entry moves the selection to it; clicking the
        entry *already* selected - only meaningful if the panel was
        already focused, i.e. this isn't the click that just focused
        it - activates it instead (open the file, or expand/collapse
        the directory), the "first click selects, second click opens"
        behavior a mouse-driven file explorer is expected to have. A
        directory is the one exception: a single click on it (once the
        panel is already focused) expands/collapses it right away -
        there's no real "open" step to hold back the way there is for
        a file, so making it wait for a second click only added a
        pointless extra click every time.

        A Ctrl+click is a different action entirely - it never opens/
        expands/collapses anything, it only toggles that one entry in
        `self.worktree_selected_entries` (for moving several at once,
        see the worktree's own drag & drop), leaving `worktree_cursor`
        and everything else untouched. A plain click always clears
        that multi-selection first, the same "a click starts fresh"
        behavior a desktop file explorer has."""
        newly_focused = not self.worktree_focused
        if not self.worktree_visible:
            self.worktree_visible = True
            self.worktree_visible_because_of_focus = True
        self.worktree_focused = True
        if newly_focused:
            self._invalidate_worktree_cache()
        entries = self._worktree_entries()
        entry_index = self._worktree_row_index(panel_row, entries)
        if entry_index is None:
            return
        path, _, is_directory, _ = entries[entry_index]
        if ctrl_held:
            # The root can't be part of a multi-selection - there's no
            # sensible "delete/move the root along with these" - see
            # _worktree_delete/_handle_worktree_drop.
            if path != self.worktree_root:
                self.worktree_selected_entries.symmetric_difference_update(
                    {path}
                )
            return
        # A plain click on an entry that's already part of a
        # Ctrl+click multi-selection preserves it, rather than
        # collapsing it down to just this one - this is what makes it
        # possible to actually drag the whole selection at once
        # (a drag starts with a plain MOUSE_PRESS; clearing the
        # selection right here would mean the drop, later, would only
        # ever see the one entry the drag happened to start on). A
        # click on anything else still clears it, same "a click starts
        # fresh" behavior as before.
        if path not in self.worktree_selected_entries:
            self.worktree_selected_entries = set()
        already_selected = (
            not newly_focused and entry_index == self.worktree_cursor
        )
        self.worktree_cursor = entry_index
        if already_selected or (is_directory and not newly_focused):
            self._worktree_activate(entries)

    def _worktree_button_index_at(self, panel_row, visible_rows):
        """Which of `_WORKTREE_BUTTON_LABELS` (if any) sits at
        `panel_row` - the last few rows of the panel, only there at
        all when `MOUSE_ENABLED` (see `_worktree_body_lines`, which
        lays them out identically); None everywhere else, including
        the whole panel when the buttons aren't being drawn."""
        if not theme.MOUSE_ENABLED:
            return None
        first_button_row = visible_rows - len(_WORKTREE_BUTTON_LABELS)
        index = panel_row - first_button_row
        return index if 0 <= index < len(_WORKTREE_BUTTON_LABELS) else None

    def _activate_worktree_button(self, index):
        """Ctrl+F/Ctrl+D's own worktree actions - exactly what a click
        on the matching button (see `_worktree_button_index_at`)
        means."""
        if index == 0:
            self._worktree_create(is_directory=False)
        elif index == 1:
            self._worktree_create(is_directory=True)

    @staticmethod
    def _pad_sidebar(text):
        return text[:WORKTREE_WIDTH].ljust(WORKTREE_WIDTH)

    def _worktree_row_style(self, path, index, dragging):
        """The (base_color, base_close) pair `_worktree_body_lines`
        wraps one row in, picked from cursor/multi-selection/drag-
        target/hover state in that priority order. A Ctrl+click-
        toggled entry (see `_handle_worktree_click`) gets its own
        background, same idea as WORD_MATCH_START already
        highlighting other occurrences of a selected word elsewhere.
        WORD_MATCH_START is a background color (unlike CURRENT_LINE_
        INDICATOR_COLOR, which is foreground), so when a row is both
        the cursor and part of the multi-selection both are applied
        together - otherwise Ctrl+clicking the cursor's own row gave
        no visible sign it had joined the selection at all."""
        is_cursor = index == self.worktree_cursor
        is_multi_selected = path in self.worktree_selected_entries
        if is_cursor and is_multi_selected:
            return (
                theme.WORD_MATCH_START + theme.CURRENT_LINE_INDICATOR_COLOR,
                theme.WORD_MATCH_END + theme.COLOR_RESET,
            )
        if is_cursor:
            return theme.CURRENT_LINE_INDICATOR_COLOR, theme.COLOR_RESET
        if is_multi_selected:
            return theme.WORD_MATCH_START, theme.WORD_MATCH_END
        if dragging and path == self._worktree_drag_target:
            # Where a drag would land if released right now (see
            # _update_worktree_drag_status) - reverse video, same as
            # the editor's own text selection, rather than a theme
            # color, so it reads as "drop zone" regardless of what
            # the multi-select/cursor colors happen to be.
            return theme.SELECTION_START, theme.SELECTION_END
        if (
            not dragging and theme.MOUSE_ENABLED
            and path == self._hovered_worktree_row
        ):
            # Bare mouse-over feedback (see bugs_conocidos.md: "es
            # necesario que se resalten minimamente") - same reverse-
            # video treatment as a drag's own drop-zone highlight
            # above, just without a drag in progress.
            return theme.SELECTION_START, theme.SELECTION_END
        return None, theme.COLOR_RESET

    def _worktree_body_lines(self, height):
        entries = self._worktree_entries()
        self.worktree_cursor = max(
            0, min(self.worktree_cursor, len(entries) - 1)
        )
        button_rows = (
            len(_WORKTREE_BUTTON_LABELS) if theme.MOUSE_ENABLED else 0
        )
        list_height = max(1, height - button_rows)
        if self.worktree_cursor < self.worktree_scroll:
            self.worktree_scroll = self.worktree_cursor
        elif self.worktree_cursor >= self.worktree_scroll + list_height:
            self.worktree_scroll = self.worktree_cursor - list_height + 1
        lines = []
        last_visible = min(len(entries), self.worktree_scroll + list_height)
        dragging = self._worktree_drag_origin is not None
        for index in range(self.worktree_scroll, last_visible):
            path, name, is_directory, depth = entries[index]
            indent = "  " * depth
            if is_directory:
                if path == self.worktree_root:
                    marker = "> " if self.worktree_root_collapsed else "v "
                else:
                    marker = "v " if path in self.worktree_expanded else "> "
                label = f"{marker}{name}/"
            else:
                label = f"  {name}"
            plain_row = self._pad_sidebar(f"{indent}{label}")
            base_color, base_close = self._worktree_row_style(
                path, index, dragging
            )
            is_hovered = (
                theme.MOUSE_ENABLED and not dragging
                and path == self._hovered_worktree_row
                and path != self.worktree_root
            )
            if is_hovered:
                # Reserve the row's own last 4 display columns for
                # hover-only "✎"/"×" (rename/delete) icons - only
                # drawn for the entry the mouse is currently over
                # *anywhere on that row* (see bugs_conocidos.md: "al
                # pasar el ratón por encima"), kept separate from the
                # narrower hit-tests `_worktree_rename_hit_test`/
                # `_worktree_delete_hit_test` still use to decide
                # whether a click actually landed on one of them. Same
                # before/hover-color/resume-color nesting `_tab_bar_
                # line` already uses for a tab's own ×. Not drawn
                # mid-drag - _hovered_worktree_row only updates on
                # MOUSE_MOVE, so it'd otherwise show stale icons over
                # wherever the drag started. Never drawn for the
                # worktree root itself either - it can't be deleted or
                # renamed from here (see _worktree_delete/_worktree_
                # rename), so neither icon would ever do anything.
                # Each icon only actually turns its own color when the
                # mouse is precisely over its own narrow zone (see
                # _worktree_rename_hit_test/_worktree_delete_hit_test)
                # - blending into the row's own color otherwise - so
                # the color itself tells you a click right here would
                # do something, not just "this row has icons at all".
                # Same idea as `_tab_bar_line`'s own × already uses.
                resume = base_color if base_color else theme.COLOR_RESET
                rename_color = (
                    theme.CURRENT_LINE_INDICATOR_COLOR
                    if self._hovered_worktree_rename == index else resume
                )
                delete_color = (
                    _DELETE_HOVER_COLOR
                    if self._hovered_worktree_delete == index else resume
                )
                # \x1b[22m only ever cancels bold - when `resume` is
                # theme.SELECTION_START (reverse video, a mode toggle,
                # not a color-setting code, on an otherwise plain
                # hovered row) it does nothing to cancel a foreground
                # color the ✎/× themselves just set, which would
                # otherwise bleed from one icon into the other (and
                # into whatever follows) instead of actually "blending
                # back into the row". theme.COLOR_RESET always sets a
                # real foreground first, so `resume` only ever has to
                # additionally toggle a mode, never undo a color.
                row_text = (
                    f"{plain_row[:-4]} "
                    f"{rename_color}\x1b[1m✎\x1b[22m{theme.COLOR_RESET}"
                    f"{resume} {delete_color}\x1b[1m×"
                    f"\x1b[22m{theme.COLOR_RESET}{resume}"
                )
            else:
                row_text = plain_row
            if base_color:
                lines.append(f"{base_color}{row_text}{base_close}")
            else:
                lines.append(row_text)
        while len(lines) < height - button_rows:
            lines.append(self._pad_sidebar(""))
        for button_index, label in (
            enumerate(_WORKTREE_BUTTON_LABELS) if button_rows else ()
        ):
            color = (
                theme.CURRENT_LINE_INDICATOR_COLOR
                if button_index == self._hovered_worktree_button
                else theme.SUGGESTION_COLOR
            )
            lines.append(
                f"{color}{self._pad_sidebar('  ' + label)}"
                f"{theme.COLOR_RESET}"
            )
        return lines[:height]
