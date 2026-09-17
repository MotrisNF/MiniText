# Deferred: breaking up `run()` and grouping its state

Scope intentionally left out of the current cleanup pass, to be done together in
one dedicated session with full test-suite + manual smoke-test verification
after each step - not mixed into unrelated work, since `run()` is the single
most executed function in the program and a mistake there breaks everything.

## What's already done (for reference/pattern)

`text_editor.py`'s `__init__` used to set ~45 loose attributes directly on
`self` with no grouping. This pass grouped the ones that were fully
self-contained (only read/written inside `autocomplete.py`, never touched
inside `run()`, and never referenced by any test fixture) into one object:

```python
self._suggestion_caches = SuggestionCaches()  # was 10 separate attributes
```

`SuggestionCaches` lives in `autocomplete.py` next to the code that uses it.
This is the pattern to repeat for the groups below, once each is safe to move.

## Why the rest is still loose

Two more natural groups exist - worktree state (`worktree_visible`,
`worktree_focused`, `worktree_cursor`, `worktree_show_hidden`, `worktree_
visible_because_of_focus`, ...) and run-panel state (`run_process`,
`run_master_fd`, `run_focused`, ...) - but both are read and written
*directly inside `run()`'s own key-dispatch body*, not just in
`worktree.py`/`run_panel.py`. Grouping either into a nested object (e.g.
`self.worktree.cursor` instead of `self.worktree_cursor`) means rewriting
those call sites inside `run()` too - exactly the function this pass was
told to leave alone. Attempting it now would either silently touch `run()`
anyway or ship an incomplete/inconsistent rename.

A third group - mouse/hover state (`_hovered_worktree_button`, `_hovered_tab_
close`, `_hovered_close_mini`, `_hovered_worktree_delete`, `_hovered_worktree_
row`, `_worktree_drag_origin`, `_worktree_drag_target`, `_worktree_ctrl_drag_
active`, `_mouse_layout`, `_last_click`) - does *not* touch `run()` directly,
but is referenced across `worktree.py`, `mouse.py`, `dialogs.py`,
`rendering.py`, and `commands.py`, plus four test fixtures
(`test_worktree_delete_hover.py`, `test_worktree_multiselect.py`,
`test_worktree_drag_drop.py`, `test_confirm_box.py`) that construct fake
panels with these attributes set directly. It's independent of the `run()`
work, but has the widest blast radius of the three groups - it needs its own
full grep-audit (same as this document's own investigation) before touching
anything, so a missed call site doesn't turn into a silent `AttributeError`
at runtime instead of an import-time failure.

## Breaking up `run()`

`run()` (`text_editor.py`) is currently one ~300-line method mixing:
main-loop plumbing (signals, resize, the background update-checker wakeup),
and a full key dispatcher for seven different contexts in sequence:
`help_mode`, `run_focused` (the `:run`/`:lint`/`:cmd` output panel),
`worktree_focused`, command-line mode, search mode, `move_mode`, and finally
the normal insert/visual editing keys (including two near-identical
4-way branches - arrow keys with `_update_selection`/`_move_vertical`/
`_move_horizontal`, and the visual-mode `a`/`f`/`s`/`d` line-start/line-end
jumps - that were left as-is this pass, see "cosmetic" items skipped
earlier, since tabulating them means touching this same function).

Plan:

1. Extract each context into its own method (`_handle_help_mode_key`,
   `_handle_run_panel_key`, `_handle_worktree_key`, `_handle_command_mode_key`,
   `_handle_search_mode_key`, `_handle_move_mode_key`, `_handle_editing_key`),
   leaving `run()` itself as a thin loop: read a key, decide which context is
   active, call the matching handler, `continue`.
2. Do this as one single, atomic edit (not context-by-context left half done),
   the same discipline the two file splits earlier in this cleanup used -
   `run()` must never be left with some contexts extracted and others still
   inline.
3. Verify with the full test suite, `flake8`, *and* a manual smoke test
   exercising each extracted context for real (a keyboard-driven `TextEditor`
   session touching help mode, the run panel, the worktree panel, command
   mode, search, move mode, and plain editing) - the existing test suite does
   not exercise `run()`'s own dispatch end-to-end, only the methods it calls,
   so passing tests alone would not catch a context wired to the wrong
   handler or a key silently swallowed by the wrong branch.
4. Only after this lands: revisit the worktree-state and run-panel-state
   grouping above, since by then their remaining call sites are inside
   ordinary methods (`_handle_worktree_key`, `_handle_run_panel_key`, ...)
   instead of buried in one giant function, making the rename mechanically
   easier and easier to verify by reading the diff.
