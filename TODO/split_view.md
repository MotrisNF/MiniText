# Deferred: split view (two files open side by side)

Scope: let the editor show two buffers at once, side by side, each
with its own cursor/selection/tabs/undo history - the VS Code
"split editor" idea. Deferred to its own session (or several) - this
is the largest single change discussed for Mini so far, bigger than
the `run()` breakup or multi-line highlighting. Not started; nothing
in the codebase today assumes more than one active buffer.

## Current state (why this doesn't exist yet)

`TextEditor` (`text_editor.py`) is one class with a *flat* attribute
namespace representing exactly one active buffer at a time -
`self.lines`, `self.line`, `self.column`, `self.mode`,
`self.selection_anchor`, `self.tabs`, `self.undo_stack`, and so on.
Tabs already exist, but they work by swapping this flat state in and
out (`tabs.py`'s `_current_buffer_state`/`_apply_buffer_state`) - at
any instant, only one buffer's worth of state is actually live on
`self.*`. Every mixin (`editing.py`, `autocomplete.py`, `commands.py`,
`rendering.py`, `mouse.py`, ...) reads and writes these flat
attributes directly, with no notion of "which buffer" beyond "the one
currently loaded."

`_render()` (`rendering.py`) is built the same way: one ~550-line
method that lays out one tab bar, one gutter, one editor content
area, optionally the worktree sidebar and the `:run`/`:lint`/`:cmd`
panel, all against that single set of flat attributes.

## Why this is bigger than it looks

Splitting the view needs two independent live buffers, not just two
items in one list you switch between - both need to render, accept
their own keystrokes, and hold their own cursor/selection/undo state
*simultaneously*. That touches the state model, the renderer, and
input dispatch all at once:

1. **State**: roughly 29 of today's flat attributes would need to
   move from "one shared copy" to "one copy per pane" - `file_name`,
   `lines`, `line`, `column`, `mode`, `command`, `_cmd_tab_state`,
   `move_mode`, `viewport_top`, `selection_anchor`, `pending_count`,
   `count_locked`, `search_query`, `last_search`, `_highlight_query`,
   `_highlight_whole_word`, `undo_stack`, `redo_stack`, `modified`,
   `_comment_state`, `_comment_state_language`, `tabs`, `active_tab`,
   `suggestion_matches`, `suggestion_index`,
   `_suggestion_dismissed_at`, `_suggestion_caches`,
   `_elastic_width_cache`, `_indent_guide_depth_cache`,
   `_dropdown_was_shown`. Everything else stays global, the same way
   VS Code shares these across split editors: the worktree panel
   (`self.worktree`), the `:run`/`:lint`/`:cmd` panel
   (`self.run_panel`), the clipboard (so copying in one pane and
   pasting in the other keeps working), the status line, and modal
   dialogs (name/confirm prompts, the welcome banner).

2. **A migration path that doesn't rewrite every mixin**: introduce a
   `PaneState` object holding the ~29 attributes above, keep
   `self.panes` (a list of them) plus `self.active_pane_index` on
   `TextEditor`, and turn the flat attributes into *properties* that
   delegate to `self.panes[self.active_pane_index]`. Every existing
   method that already says `self.lines`/`self.line`/etc. keeps
   working unmodified, blind to there being more than one pane - it's
   always reading "whichever pane is currently focused". Starting
   with `self.panes = [PaneState()]` (one pane, matching today
   exactly) means the ~180 existing tests shouldn't need to change at
   all; they never trigger a second pane. This is the same shape as
   the `SuggestionCaches`/`RunPanelState`/`MouseState`/`WorktreeState`
   groupings already done this session, just applied to the whole
   buffer-state surface instead of one feature's own corner of it.

3. **Rendering is where the real risk concentrates.** `_render()` is
   already ~550 lines and assumes one editor area. Splitting it means
   computing two independent sets of wrap points, row descriptors,
   cursor position, and gutter/tab-bar content, side by side, with
   the available terminal width divided between them (sidebar | pane
   A | divider | pane B). Every rendering feature built this session
   has to keep working correctly and *independently* per pane -
   syntax highlighting, the multi-line comment/docstring carryover
   cache (`_comment_state_for`), indent guides
   (`_indent_guide_depth`), word/search highlighting
   (`_refresh_highlight_query`), bracket/quote matching, elastic
   tabstops, and the suggestion dropdown. None of these were written
   with a second, independent instance of themselves in mind, even
   though most are already per-pane-attribute-shaped (a cache keyed
   or reset per render, not something that assumes global
   uniqueness) - each one still needs to be checked, not assumed.
   `_last_rendered_rows` (the differential-render cache) can likely
   stay a single dict keyed by absolute screen row, as long as each
   cached value is the *whole* row's text (both panes stitched
   together) rather than one pane's piece of it - a real design point
   to settle, not just an assumption to carry over.

4. **Mouse and keyboard dispatch need a new dimension.**
   `_mouse_target()` (`mouse.py`) resolves a click to a named region
   ("editor", "sidebar", "tab_bar", ...) - it would also need to say
   *which pane*, and a click in a pane's own editor area should focus
   it (mirroring how a plain click already changes focus elsewhere -
   see `_reset_focus_for_click`). Keyboard dispatch
   (`text_editor.py`'s `run()` and its `_handle_*_key` methods) reads
   the (now-delegated) flat attributes already, so most of it keeps
   working once the property indirection is in place - the missing
   piece is new keybindings/commands to open a split, close it, and
   cycle focus between panes, plus deciding what opening a file from
   the worktree does (simplest: always into the focused pane).

## Suggested scope, when picked up

Deliberately smaller than VS Code's own split view, matching Mini's
own minimalism:

- Exactly two panes, one fixed vertical divider (roughly 50/50) - no
  arbitrary grid of panes, no resizing in v1.
- Worktree, run panel, clipboard, status line, and dialogs stay
  global/shared, exactly as sketched above.
- One key/command to toggle the split on and off, one to cycle focus
  between the two panes.
- Opening a file from the worktree always goes into the focused pane.

## Suggested order, when picked up

1. `PaneState` plus the delegating properties on `TextEditor`, with
   `self.panes` starting at length 1 - a pure refactor, no visible
   behavior change yet. Verify with the full test suite and a manual
   smoke test exactly like the `run()` breakup did, before touching
   rendering at all.
2. Only then: split `_render()`'s layout math to divide the available
   width between two panes when a second one exists, reusing the
   per-pane caches/state from step 1 as-is.
3. Mouse region resolution and focus-follows-click for the new pane
   boundary.
4. The toggle-split/cycle-focus keys or commands, and the
   worktree-opens-into-focused-pane wiring.
5. A dedicated test pass per rendering feature (syntax highlighting,
   multi-line comments, indent guides, word/search highlighting,
   bracket matching, elastic tabstops, suggestions) confirming each
   one still behaves correctly with two independent panes open at
   once - not just that the split renders at all.
