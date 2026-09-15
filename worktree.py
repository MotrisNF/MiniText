"""The worktree file explorer panel: listing, expanding/collapsing
directories, creating/deleting entries, and rendering its rows -
everything except the key handling that drives it (that stays in the
main run() loop, since it needs to route between the worktree, the
editor, and the other focus targets)."""

import os
import shutil

import theme

WORKTREE_WIDTH = 28
MIN_EDITOR_WIDTH = 20
WORKTREE_SEPARATOR_WIDTH = 2


class WorktreePanelMixin:

    def _worktree_entries(self):
        """The flattened, currently-visible worktree listing (one
        entry per row the panel draws). Rebuilding this means walking
        the filesystem, so it's cached across renders -
        `_invalidate_worktree_cache` is called wherever something that
        should change the listing actually happens (expanding or
        collapsing a directory, creating or deleting an entry, or
        (re)showing/focusing the panel, to also pick up changes made
        outside Mini)."""
        if self._worktree_entries_cache is not None:
            return self._worktree_entries_cache

        entries = []
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

        walk(self.worktree_root, 0)
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
        if is_directory and path not in self.worktree_expanded:
            self.worktree_expanded.add(path)
            self.worktree_selected_dir = path
            self._invalidate_worktree_cache()

    def _worktree_collapse(self, entries):
        if not entries:
            return
        path, _, is_directory, _ = entries[self.worktree_cursor]
        if is_directory and path in self.worktree_expanded:
            self.worktree_expanded.discard(path)
            self.worktree_selected_dir = os.path.dirname(path)
            self._invalidate_worktree_cache()

    def _worktree_activate(self, entries):
        if not entries:
            return
        path, _, is_directory, _ = entries[self.worktree_cursor]
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
        self.status = f"{label}:"
        self._render()
        name = self._read_command_line(label)
        if not name:
            self.status = "Cancelled"
            return
        new_path = os.path.join(self.worktree_selected_dir, name)
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

    def _worktree_delete(self, entries):
        if not entries:
            return
        path, name, is_directory, _ = entries[self.worktree_cursor]
        kind = "folder" if is_directory else "file"
        if not self._confirm(f"Delete {kind} '{name}'? (y/n)"):
            return
        try:
            if is_directory:
                shutil.rmtree(path)
                self.worktree_expanded.discard(path)
            else:
                os.remove(path)
        except OSError as error:
            self.status = f"Could not delete '{name}': {error}"
            return
        self._invalidate_worktree_cache()
        if self.file_name == path:
            self.status = f"Deleted {path} (still open here, unsaved)"
        else:
            self.status = f"Deleted {path}"
        self.worktree_cursor = max(0, self.worktree_cursor - 1)

    def _handle_worktree_click(self, panel_row):
        """A mouse click at `panel_row` (0-indexed from the top of the
        sidebar - row 0 is the "Worktree: root" header, matching
        `_worktree_body_lines`'s own layout) always focuses the panel
        first, the same as pressing `w` (including picking up changes
        made outside Mini, but only on the transition into focus, not
        on every click while already there - same as `w` itself).
        Clicking an entry moves the selection to it; clicking the
        entry *already* selected - only meaningful if the panel was
        already focused, i.e. this isn't the click that just focused
        it - activates it instead (open the file, or expand/collapse
        the directory), the "first click selects, second click opens"
        behavior a mouse-driven file explorer is expected to have."""
        newly_focused = not self.worktree_focused
        if not self.worktree_visible:
            self.worktree_visible = True
            self.worktree_visible_because_of_focus = True
        self.worktree_focused = True
        if newly_focused:
            self._invalidate_worktree_cache()
        entries = self._worktree_entries()
        if panel_row <= 0 or not entries:
            return
        entry_index = self.worktree_scroll + (panel_row - 1)
        if entry_index >= len(entries):
            return
        already_selected = (
            not newly_focused and entry_index == self.worktree_cursor
        )
        self.worktree_cursor = entry_index
        if already_selected:
            self._worktree_activate(entries)

    @staticmethod
    def _pad_sidebar(text):
        return text[:WORKTREE_WIDTH].ljust(WORKTREE_WIDTH)

    def _worktree_body_lines(self, height):
        entries = self._worktree_entries()
        self.worktree_cursor = max(
            0, min(self.worktree_cursor, len(entries) - 1)
        )
        list_height = max(1, height - 1)
        if self.worktree_cursor < self.worktree_scroll:
            self.worktree_scroll = self.worktree_cursor
        elif self.worktree_cursor >= self.worktree_scroll + list_height:
            self.worktree_scroll = self.worktree_cursor - list_height + 1
        root_label = os.path.basename(
            self.worktree_root.rstrip(os.sep)
        ) or self.worktree_root
        lines = [self._pad_sidebar(f"Worktree: {root_label}")]
        last_visible = min(len(entries), self.worktree_scroll + list_height)
        for index in range(self.worktree_scroll, last_visible):
            path, name, is_directory, depth = entries[index]
            indent = "  " * depth
            if is_directory:
                marker = "v " if path in self.worktree_expanded else "> "
                label = f"{marker}{name}/"
            else:
                label = f"  {name}"
            plain_row = self._pad_sidebar(f"{indent}{label}")
            if index == self.worktree_cursor:
                lines.append(
                    f"{theme.CURRENT_LINE_INDICATOR_COLOR}{plain_row}"
                    f"{theme.COLOR_RESET}"
                )
            else:
                lines.append(plain_row)
        while len(lines) < height:
            lines.append(self._pad_sidebar(""))
        return lines[:height]
