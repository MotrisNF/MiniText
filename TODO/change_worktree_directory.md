# Deferred: opening an additional worktree root, without closing the
current one

Scope: let a running Mini add a *second* (or third, ...) top-level
directory to the worktree panel - VS Code's "Add Folder to Workspace"
- rather than replacing what's already open. Supersedes an earlier,
simpler draft of this same document that assumed *replacing* the
current directory instead; the user explicitly wants add-alongside,
not swap. Deferred to its own session - not started.

## Current state

`self.worktree` (`worktree.py`) has exactly one root
(`self.worktree.root`, a single path) and one boolean tracking whether
*it* is collapsed (`self.worktree.root_collapsed`) - separate from
`self.worktree.expanded` (a set), which tracks every *other*
expanded directory. `_worktree_entries()` always starts the flattened
listing with one synthetic depth-0 entry for `self.worktree.root`
itself (collapsible, but protected from delete/rename/drag - see
`_worktree_activate`/`_worktree_delete`/`_worktree_rename`/
`_handle_worktree_drop`'s own `path == self.worktree.root` guards),
then walks into it if `not self.worktree.root_collapsed`.

Open tabs are already independent of the worktree root entirely (see
`change_worktree_directory.md`'s original analysis) - nothing about
adding a second root touches them.

## The key simplification: unify roots with ordinary directories

`root_collapsed` only exists because a single root defaults to
*expanded*, the opposite of `expanded`'s own default (empty = every
ordinary directory starts collapsed) - that mismatch is what forced
it into its own separate boolean instead of just reusing the set.
Once there's more than one root, tracking a second, parallel
collapse-state field *per root* would be worse than what's there
today. The cleaner fix, once picked up:

- `self.worktree.root` (one path) becomes `self.worktree.roots` (a
  list of paths, in the order they were added).
- Drop `root_collapsed` entirely. A root is a depth-0 entry that
  participates in the *same* `self.worktree.expanded` set every
  ordinary directory already uses - seeded with all of `roots` up
  front (and with any newly-added one, right when it's added), so
  every root still starts expanded, matching today's default, with no
  separate flag needed to make that happen.
- `_worktree_entries()` loops over `self.worktree.roots`, appending
  one depth-0 entry per root and walking into it exactly the way it
  already walks into any expanded directory - the current single
  `if not self.worktree.root_collapsed: walk(self.worktree.root, 1)`
  branch goes away completely, replaced by the loop.
- Every `path == self.worktree.root` guard (delete/rename/drag/multi-
  select protection, and the two expand/collapse special cases)
  becomes `path in self.worktree.roots` - protecting *all* of them,
  not just one.
- The one place that still needs to know "this depth-0 entry is a
  root" specifically, even after unifying the expand/collapse state
  itself: collapsing an ordinary directory sets
  `self.worktree.new_entry_dir` to its *parent* (`_worktree_collapse`,
  `worktree.py`) - collapsing a root has to keep setting it to the
  root *itself* instead (a root's filesystem parent is outside every
  worktree root and a nonsensical place for "new files go here" to
  point at). A one-line special case, not a reason to keep a whole
  parallel boolean around.
- `_worktree_root_label()` takes the specific root as a parameter
  instead of reading `self.worktree.root` directly, so it can label
  whichever one a given depth-0 entry is for.

Rendering (`_worktree_body_lines` and friends) needs no changes at
all beyond this - it already scrolls through however many rows
`_worktree_entries()` hands it; more depth-0 entries are just more
rows, the same as a directory with more children already are.

## What else needs to change

1. **A command to add a root** - `:add <path>` (name open; `:cd` reads
   as "replace", which this explicitly isn't). Same free-form-text
   special-casing `:cmd`/`:s/old/new/` already get in
   `_execute_command` (`commands.py`), before `_parse_command` ever
   sees it. A relative `<path>` should resolve against
   `self.worktree.new_entry_dir` (wherever you're currently browsing)
   rather than Mini's own process `cwd`, which can quietly differ.
   Validate it's an existing, readable directory, and that it isn't
   already one of `self.worktree.roots` (skip/no-op with a clear
   status message rather than showing the same folder twice) - on
   any failure, leave the current roots completely untouched.

2. **The "no file open" fallback in `commands.py`/`run_panel.py`**
   (`:cmd`'s own cwd, and venv detection's start directory) currently
   reads `self.worktree.root` directly in three places. With more
   than one root, there's no single obvious "the" root to fall back
   to any more - `self.worktree.new_entry_dir` (already tracking
   wherever was last navigated, defaulting to the first root added)
   is the natural replacement, and needs no new state of its own.

3. **`mouse.py`'s drag-origin guard** (`entry[0] != self.worktree.root`,
   preventing a root from being dragged) becomes a `not in
   self.worktree.roots` check, same as every other root guard above.

## Nice to have, not required for a first version

- **Removing** a root (`:close <path>` or similar) - the natural
  complement once adding one exists, but not asked for here and not
  needed for `roots` to work correctly with just one entry (today's
  exact behavior) or several.
- Tab-completion for `:add`'s own argument, mirroring `:cmd`'s
  existing directory-name completion (`_cmd_tab_complete`).
