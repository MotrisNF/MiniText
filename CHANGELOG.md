# Changelog

Notable changes to Mini, release by release. The version number here
matches `VERSION` (what `mini --version` prints).

## 1.11.5 - 2026-09-18

- Fixed renaming a file/directory, or dragging one onto another in
  the worktree panel, silently overwriting an existing entry that
  already had the destination name - `os.rename()`/`shutil.move()`
  both replace an existing destination on their own with no warning
  at all, unlike creating a new file/directory (which already refused
  outright). Both now check first and refuse the same way, rather
  than risking destroying whatever was already there.
- Fixed AUTOSAVE (mouse mode) not saving the file being left when
  opening a different one by clicking it in the worktree panel - only
  a click landing in the code area or on a tab actually triggered it
  before, so a click that opened another file from the sidebar could
  skip saving the one just left, silently.
- Autocompletion backed by jedi (type-aware `name.` completion, and
  `from module import <TAB>`) used to run synchronously and could
  visibly freeze the editor - measured at ~100-160ms per new
  completion context, and over a second for the very first one of a
  session. It now runs on a background thread: a render waits only a
  short, bounded moment for it (still instant once jedi's warm), falls
  back to Mini's own heuristics otherwise, and picks up the real
  answer moments later - even without another keypress, if the
  background job finishes while idle. Opening a `.py` file also now
  kicks off jedi's own one-time warm-up in the background right away,
  instead of it landing on the first real completion attempt.

## 1.11.4 - 2026-09-18

- Fixed `_save()` permanently blanking `file_name` to `""` (not back
  to `None`) after cancelling the "Name of the file:" prompt (Enter on
  an empty line, or Esc) - every save attempt afterward skipped the
  "ask for a name" step entirely and crashed trying to
  `open("", "w")`.
- Fixed a Ctrl+click multi-selection in the worktree panel staying
  armed and visibly highlighted after leaving the panel (clicking into
  the editor, opening a file, entering command/search/Insert) -
  nothing ever cleared it, so it could resurface later on whatever
  still matched those paths, with no apparent reason why.
- Fixed a mouse click's `selection_anchor` (armed so a *drag* right
  after it can select text) persisting through ordinary typing instead
  of dragging - it stayed fixed at the click point while the cursor
  moved ahead with every character typed, making the text just typed
  look like it was progressively selecting itself.
- Added multi-line-aware syntax highlighting: a Python triple-quoted
  docstring (`"""..."""`/`'''...'''`) or a C/C++ `/* ... */` comment
  spanning several lines is now colored as one block - including its
  own opening line, which previously fell through single-line
  tokenizing as a stray "empty string" plus an uncolored quote
  character. Tracked incrementally per line and invalidated only from
  wherever an edit actually lands, so it stays fast even in large
  files.
- Added an MIT license (`LICENSE`) and reorganized the README for
  readability: a table of contents, build/mouse-support badges, and
  clearer section grouping, with no content removed.
- Internal: every module now lives under a `mini/` package directory
  instead of as loose files at the repo root (`install.sh`/
  `updater.py`/`main.py` updated to match, preserving git history via
  `git mv`). `text_editor.py`'s ~300-line `run()` key dispatcher is
  now a thin loop delegating to 7 per-context handler methods
  (`_handle_help_mode_key`, `_handle_run_panel_key`, etc. - see
  `run_refactor.md`, since removed now that this landed), and the
  worktree/run-panel/mouse-hover attributes it used to share with
  those handlers are grouped into `WorktreeState`/`RunPanelState`/
  `MouseState` objects instead of ~30 loose `self.*` attributes.

## 1.11.3 - 2026-09-17

- Fixed a second, deeper case of the overlay boxes leaving a stale
  border/silhouette behind (1.11.1 fixed the simple "one box replaces
  another" case, but missed this one): the "Close Mini" button and a
  confirm box can legitimately be showing at the same time (deleting
  or moving a worktree entry while the last tab is still the blank
  welcome screen), and the redraw check only tracked "which single box
  is showing" - close_box staying up the whole time hid confirm_box's
  own appearing/disappearing right underneath it. Each of the three
  overlay boxes now has its own independent slot in that check instead
  of sharing one.
- Fixed `read_key()` decoding stdin one byte at a time, which silently
  dropped every accented/non-ASCII character typed (a lone UTF-8 lead
  byte always fails to decode on its own) - it now reads the whole
  multi-byte sequence before decoding.
- Fixed `mini --update`'s own `git pull`/`install.sh` running with no
  timeout at all, unlike every other git call the updater makes - a
  stalled network or a hung install.sh could block indefinitely with
  no way out.
- Class names (both a class's own definition and any type annotation
  naming one) are now colored the same as builtin type names; a
  function/method definition's own parameter names get their own new
  color (`PARAMETER_COLOR`, configurable in `~/.minirc` like every
  other syntax color), separate from a typed parameter's own
  annotation.
- Added renaming files/directories in the worktree panel: `r`, or the
  row's own hover "✎" in mouse mode (next to the existing delete "×"),
  prompts for a new name pre-filled with the current one. Renaming a
  directory rewrites every path that was nested under it (open tabs,
  the multi-selection, expanded directories, and where new entries get
  created), so nothing is left pointing at a path that no longer
  exists.
- The worktree panel's own root directory is now its own row at the
  top of the tree (not a separate, non-interactive header line) -
  collapsible like any other directory, except it can't be deleted or
  renamed from here. Collapsing it hides the whole tree at once and
  moves "new files/folders go here" back to the top level, a quick way
  back after navigating deep into a project.
- Internal: split `rendering.py` into `rendering.py` (the tab bar,
  syntax-highlight application, and the main render loop),
  `mouse.py` (mouse event dispatch), and `dialogs.py` (the centered
  overlay boxes' geometry and rendering) - and `autocomplete.py` into
  `autocomplete.py` (Python-specific completion), `c_autocomplete.py`
  (C/C++'s own comment-scanning and `#include` machinery), and
  `python_introspection.py` (the subprocess/jedi introspection
  engine). Also grouped autocomplete's various caches into one
  `SuggestionCaches` object instead of a dozen loose attributes, and
  removed a fair amount of small duplication across worktree.py,
  editing.py, tabs.py, run_panel.py, highlighting.py, commands.py,
  theme.py, and updater.py. `run_refactor.md` documents the similar
  (larger, deferred) cleanup still pending for `text_editor.py`'s own
  `run()` and the worktree/run-panel state that's entangled with it.

## 1.11.2 - 2026-09-17

- Redrew the welcome banner again: 1.11.1's mechanical downscale of
  the wide `Banner.txt` prototype turned out unreadable once shrunk
  down that far. Replaced with a hand-built block-letter wordmark
  spelling "MiniText" - capitals full height, lowercase at x-height,
  double-wide pixels for a bolder look - instead of derived from that
  prototype at all; `Banner.txt` stays as the original, unused
  reference.
- Added Ctrl+drag as a second way to multi-select worktree entries,
  alongside the existing Ctrl+click: holding Ctrl while dragging adds
  every entry the mouse passes over to the selection (never removes
  one already added, even if the drag crosses back over it) instead
  of starting the plain drag's "move this entry" gesture.
- Redesigned the move/delete confirmation box for more than one file:
  the file names used to be folded into the prompt itself as a comma-
  joined string that silently truncated once it got too long to fit
  on one line. They're now a separate, scrollable list under the
  prompt (mouse wheel to scroll, a "▲"/"▼" arrow when there's more
  above/below) - the prompt itself now just states the count, and the
  Yes/No buttons are unchanged.

## 1.11.1 - 2026-09-17

- Fixed Ctrl+click-selecting the worktree entry that was already the
  cursor showing no visible change at all - the multi-selection
  background and the cursor's own foreground color are now combined
  on that row instead of the cursor's indicator silently winning,
  which used to make it look like the click hadn't registered.
- Fixed the "Close Mini"/new-file-or-folder/confirm overlay boxes
  leaving a stale border or row behind when one replaced another in
  the same frame (e.g. "Close Mini" showing, then a new-file dialog
  opening over it): the full-redraw check only compared *whether* some
  box was showing, not *which* one, so a box-to-box transition never
  triggered the clear that a shown-to-hidden transition already did.
- Added a hover highlight (reverse video) to worktree rows as the
  mouse passes over them - previously only the per-row delete "×" gave
  any indication at all.
- Added visual feedback while dragging a worktree entry: the row the
  mouse is currently over is highlighted as the drop zone, and the
  status line now names the file being dragged, not just the
  destination.
- Redrew the welcome banner from the original wide prototype
  (`Banner.txt`, kept as-is) instead of the unrelated block-letter
  "MINI" wordmark 1.11.0 introduced as a placeholder - the new banner
  is a mechanical downscale (block-sampled, like an image resize) of
  that same prototype into a size that actually fits a typical
  terminal.

## 1.11.0 - 2026-09-16

- Fixed a crash (`AttributeError: module 'theme' has no attribute
  'WORD_MATCH_COLOR'`) the instant a worktree entry was Ctrl+click-
  selected: the multi-selection row background used a color key that
  doesn't exist as a plain attribute - `WORD_MATCH_COLOR` is a
  background color, only exposed as the `WORD_MATCH_START`/
  `WORD_MATCH_END` pair it actually needs to close itself with
  (`COLOR_RESET` alone, correct for the cursor's own foreground-only
  indicator, would have left the background bleeding into whatever
  came after it even without the crash).
- Fixed the worktree's per-entry delete "×" only ever revealing itself
  once the mouse was already exactly where it would be drawn (the
  last 2 columns of the row) - hovering *anywhere* on a row now
  reveals its "×"; clicking still only hits it in that same narrow
  zone as before.
- Fixed a y/n confirmation box (drag & drop with several or long file
  names, say) silently failing to appear at all when its prompt was
  wider than the available code area - it now clamps to fit and
  truncates the prompt text instead, the same way the new-file/new-
  folder dialog already truncates a long typed name; `_confirm` no
  longer blocks with nothing shown for it.
- Fixed Ctrl+click multi-selecting several worktree entries, then
  starting a drag with a plain click on one of them, silently
  collapsing the whole selection down to just that one entry before
  the drag could ever use it - moving or deleting several entries at
  once was effectively impossible. A plain click on an entry already
  part of the selection now preserves it; clicking anything else still
  clears it, unchanged.
- The worktree's delete (the per-row "×", or `Delete` on the selected
  entry) now deletes every entry in a Ctrl+click multi-selection
  together, with one confirmation, when the target is part of one -
  previously it only ever deleted the single entry, ignoring the rest
  of the selection.
- Added a welcome screen above the "Close Mini" button (the blank/
  unnamed/unmodified last-tab state): a small block-letter "MINI"
  banner and an "Open a file to start" subtitle, shown either way -
  mouse mode or not, though only the button itself is actually
  clickable. Degrades gracefully (button alone, no banner) on a
  terminal too small to fit the whole block.

## 1.10.0 - 2026-09-16

- Fixed a click in the code area or on a tab while in Insert mode
  forcing a switch to Visual mode - it now only moves the cursor,
  exactly like it already does in Visual mode itself; `Esc` remains
  the only way out of Insert. The worktree panel and the `:run`/
  `:lint`/`:cmd` output panel still lose focus on that same click,
  unchanged.
- Fixed Backspace treating a block of spaces inserted by Tab (the
  default, `INDENT_WITH_TABS=False`) as plain single characters
  instead of the one indentation unit it actually is: it now removes
  a whole `TAB_SIZE`-wide block at once when the cursor sits right
  after one, inside a line's own leading indentation - the same way
  Backspace on a real tab character already removed it whole. Spaces
  used for mid-line alignment, an uneven column, or mixed tabs/spaces
  are untouched, still removed one at a time as before.
- Fixed Enter after a line ending in `:` adding another indentation
  level on *every* subsequent Enter, as long as each new line also
  happened to end in `:` - a very common shape for a comment
  (`# steps:`, `# note:`, ...) or a docstring line (`:param x:`), not
  just real Python block openers. A trailing `:` now only indents when
  the line actually starts with a real block keyword (`if`/`elif`/
  `else`/`for`/`while`/`try`/`except`/`finally`/`with`/`def`/`class`/
  `match`/`case`/`default`) - a comment or docstring line ending in
  `:` no longer indents at all, while `if x:`, `else:`, `def foo():`,
  and the like are unaffected.
- Fixed the new-file/new-folder name dialog (and, incidentally, the
  "Close Mini" button) forcing a full-screen redraw on every single
  keystroke while open, instead of only when it actually appears or
  disappears - noticeable lag typing a name quickly. The dialog's own
  box was already repainted every frame regardless; only the
  unconditional full clear behind it was wasted work.
- The in-editor help screen (`:help`, and `mini --help`) now actually
  looks at the terminal's real size and can be scrolled (`Up`/`Down`,
  `Ctrl+Up`/`Ctrl+Down` a page at a time) instead of silently losing
  whatever didn't fit off the bottom on a short terminal, with a fixed
  footer line showing `Press q to exit` plus a `Lines X-Y of Z` hint
  whenever there's more to see.
- `MOUSE_ENABLED` is now `True` by default for a freshly installed
  `~/.minirc` - an existing install's own value (`True` or `False`,
  whichever it already had) is never touched by this, since the
  update mechanism that carries new settings into an existing
  `~/.minirc` only ever adds a key that's genuinely missing, never
  overwrites one already there.
- Added `AUTOSAVE` to `~/.minirc` (default `False`): with it and
  `MOUSE_ENABLED` both on, the current file saves itself - no
  confirmation, no status prompt beyond the usual "Saved to ..." -
  every time a click lands in the code area or tab bar, or Insert
  mode is entered or left (`i`/`Esc`), as long as the buffer already
  has a name. A brand-new, never-yet-named buffer is never
  auto-named.
- `~/.minirc`'s generated color sections (`[base]`/`[dark]`/`[light]`)
  are no longer 18 unexplained `KEY=value` lines in a row: a legend
  above them now says what each key actually paints, the sections
  themselves are grouped (Editor / Selection and matching / Syntax /
  Suggestions and tabs) with a one-line label per group, and each
  section reminds you whether it's the one `THEME=` actually
  activates.
- `mini --update` and `make install` now recover on their own from a
  remote history rewrite (a force-push after a mistaken commit, say)
  that used to leave `git pull --ff-only` failing the exact same way
  forever - previously the only fix was uninstalling and reinstalling
  by hand. Recovery only ever runs after confirming the installed
  checkout has no uncommitted changes of its own to lose.
- `:refresh` now also re-lists the worktree panel (previously it only
  reloaded `~/.minirc`), and `:w`/`:wq` on a brand-new, never-before-
  saved buffer now shows the file it just created in the worktree
  panel immediately instead of only after some other action happened
  to refresh the listing.
- Added a hover-only delete "×" to each worktree entry (mouse mode
  only) - appears at the right edge of whichever row the mouse is
  actually over, clicking it asks for confirmation the same way
  pressing `Delete` on the selected entry already does.
- A single click on a directory in the worktree panel (once it's
  already focused) now expands/collapses it directly, instead of
  needing a first click to select and a second to activate - a file
  still needs that second click to open, unchanged.
- Added Ctrl+click multi-selection in the worktree panel: toggles that
  one entry in/out of a selection (shown with its own background
  color), independent of the normal single-entry cursor; a plain
  click always clears it first. Used by drag & drop (below) to move
  every selected entry together.
- Added drag & drop in the worktree panel (mouse mode only): dragging
  an entry onto a directory moves it inside, after confirming;
  dragging it onto a file moves it to that file's own parent directory
  instead; dropping an entry on itself (including a plain click with
  no real drag) is always a silent no-op. Dragging a Ctrl+click-
  selected entry moves the whole selection together.
- Every y/n confirmation (closing a modified tab, deleting a worktree
  entry) now draws as a centered box with clickable "Yes"/"No"
  buttons in mouse mode, the same "own box in the code area" treatment
  the new-file/new-folder name dialog already had - `y`/`n`/`Esc` still
  work exactly as before either way, so a keyboard-only session sees
  no change at all.
- Internal: added a `tests/` directory (not installed, development
  only) with a small dependency-free test suite (`python3
  tests/run_all.py`) covering the bug fixes and additions above that
  don't need a real terminal to verify.

## 1.9.2 - 2026-09-15

- Fixed the tab-bar × and name-dialog × (see 1.9.0) not actually
  turning red on hover for everyone - they used `LINE_LENGTH_ERROR_COLOR`,
  which is themeable via `~/.minirc` and isn't guaranteed to be red at
  all. Both now use a fixed ANSI red instead, independent of theme.
- Fixed the "Close Mini" button and the new-file/new-folder name
  dialog leaving stale border/text on screen after being dismissed (by
  confirming, cancelling, or clicking their own ×) whenever the
  buffer's own text underneath happened not to change - they're
  overlays outside the normal per-row redraw tracking, so closing one
  now forces a full redraw, the same way the suggestion dropdown
  already does.
- The name dialog's × is now bold, so it doesn't get lost against the
  box's own border.
- The one unnamed tab with no file behind it now reads "MiniText"
  instead of "no name", and never gets a × - even with unsaved scratch
  text typed into it - since there's no real file there to close.
- The "Close Mini" button now highlights on hover too, the same cue
  the worktree panel's own buttons already use.
- Fixed the name dialog's cursor sitting one column short, on top of
  the last typed character, instead of right after it.

## 1.9.0 - 2026-09-15

- `mini --update`'s messages now show the installed version instead
  of a commit hash - "Already up to date (version X)." and "Mini
  updated to version X." - matching what `mini --version` itself
  reports, rather than a hash with no meaning to whoever's reading it.
- An update no longer prints `git pull`/`install.sh`'s own raw output
  while it runs; a spinner (`| / - \`) next to "Updating..." shows
  instead. That output is still printed, in full, if either step
  fails - nothing is lost, just hidden while there's nothing to act on.
- Added hover-highlighting to the worktree panel's `+ New file`/
  `+ New folder` buttons (`MOUSE_ENABLED` on): mousing over one shows
  it in the current-line color, the same cue a selected worktree entry
  already uses.
- Replaced the worktree panel's "Close current tab" button with a "×"
  on each tab in the tab bar itself, `MOUSE_ENABLED`-only (a keyboard-
  only session has no mouse to click it with, and `:q` already closes
  the current tab), with its own margin on either side so it doesn't
  sit flush against the tab's own border, and turning red as the mouse
  passes over it. Clicking it closes that tab - even one that isn't
  the active one - prompting to save first if it's modified, exactly
  like `:q` already does.
- Closing the last open tab (`:q`, the new tab-bar ×, or the new
  "Close Mini" button below) no longer exits Mini outright - it resets
  to a blank, unnamed buffer instead, the same state `mini` with no
  file argument starts in. Only closing a tab already in that exact
  state actually exits, so `:q` (or × / "Close Mini") a second time
  still quits normally.
- Added a "Close Mini" button, shown only with `MOUSE_ENABLED` on and
  only once down to that one blank/unnamed/unmodified tab - the only
  way left to quit with just a mouse, now that closing the last tab no
  longer does that on its own. It's centered within the code area
  itself (after the gutter, and no wider than the file's own `MAX_COLS`
  when that's on) rather than across the whole terminal, the same span
  the new name dialog below is centered within too.
- `Ctrl+F`/`Ctrl+D` and the worktree panel's `+ New file`/
  `+ New folder` buttons now prompt for the new name in a box of their
  own, centered in the code area, instead of on the status line at the
  bottom - with `MOUSE_ENABLED` on, it has a "×" in its own top-right
  corner (turning red on hover, same as a tab's own ×) to cancel by
  clicking; `Esc` still cancels it too either way.

## 1.8.3 - 2026-09-15

- Fixed the mouse wheel (see "Mouse") acting as a selector after a
  click: a plain click arms `selection_anchor` (so a *drag* right
  after it can select), but the wheel handlers moved the cursor
  without ever clearing it, unlike plain keyboard movement - so
  scrolling after any click silently turned into "extend a selection
  from where I clicked" instead of plain navigation. The wheel now
  always clears any armed/active selection first, the same as a
  plain (non-`Ctrl`) arrow key already does.
- Added `:refresh`, which re-reads `~/.minirc` and applies it live -
  colors, `MAX_COLS`/`INDENT_WITH_TABS`/`TAB_SIZE` (plain and per-
  `[filetype:...]`), and `MOUSE_ENABLED` - without restarting Mini or
  losing any open buffer/tab/undo state. A toggled `MOUSE_ENABLED`
  resends the terminal's mouse-tracking escape sequence immediately,
  and the screen does a full redraw right after so no row is left
  showing colors from before the reload.
- Added Tab-completion to `:cmd`'s command line, shell-style, against
  file and folder names in the same directory `:cmd` itself runs in
  (the file's own folder, or the worktree root with no file open).
  Repeated Tabs cycle through every match in place and wrap around; a
  token that already contains a `/` is left alone rather than
  completed against the directory it points into.
- Added highlight-other-occurrences: whenever the current selection
  spans exactly one whole word - however it got selected: a
  double-click, a mouse drag once released, or `Ctrl`+movement - every
  other case-sensitive whole-word match of it elsewhere in the file is
  highlighted with the new `WORD_MATCH_COLOR`. It's recomputed fresh
  every render rather than tracked as its own state, so it appears and
  disappears together with the selection itself, with nothing to
  explicitly clear. Double-clicking a word now also selects it (it
  previously just moved the cursor there, like a single click).

## 1.8.0 - 2026-09-15

- Added three buttons along the bottom of the worktree panel with
  `MOUSE_ENABLED` on - `+ New file`, `+ New folder`,
  `x Close current tab` - the exact same actions as `Ctrl+F`/
  `Ctrl+D`/`:q`, reused directly rather than reimplemented, including
  `:q`'s own save-before-closing prompt for the close button (an
  unsaved buffer is never silently discarded just because it was a
  click). They take their own rows out of the panel's file list only
  when actually shown, so the panel's layout is unchanged with the
  mouse off.
- Fixed answering "no" to "Save changes before closing this tab?"
  (`:q` on a modified buffer) leaving the prompt's own leftover text
  on the status line with no confirmation of what actually happened -
  it now shows "Closed without saving". Declining to delete a
  worktree entry ("Delete file 'x'? (y/n)", `Delete` key) had the same
  gap; it now shows "Cancelled". Answering "yes" to either already
  showed a real confirmation ("Saved to ...") and is unchanged.
- Corrected the README: opening a file from the worktree while the
  current buffer has unsaved changes was documented as asking whether
  to save them first, but never actually did - it opens the new file
  in its own tab, leaving the modified one untouched, exactly as safe
  but without ever needing to ask.

## 1.7.1 - 2026-09-15

- Clicking a tab in the tab bar (with `MOUSE_ENABLED` on) now switches
  to it directly, the same "a click always means take me there now"
  reasoning a code-area click already follows - releasing the
  worktree/`:run` panel's focus and switching to Visual mode first,
  same as that does too.
- Added `ACTIVE_TAB_COLOR` to `~/.minirc`: the active tab now has its
  own distinct color instead of matching the editor's own background,
  which in practice made it hard to tell which tab was actually open
  at a glance. An existing `~/.minirc` gets it added automatically
  (with a sensible default per theme) on the next `mini --update`/
  reinstall, the same way any other new color already is.
- A one-off status message (`Saved`, `Cancelled`, `Created <path>`,
  `Nothing to undo`, ...) now clears itself after a few seconds,
  instead of sitting on the status line indefinitely until some later
  message happened to overwrite it - including while the editor is
  otherwise sitting idle with no keys being pressed at all.

## 1.7.0 - 2026-09-15

- Added mouse support, off by default (`MOUSE_ENABLED=True` in
  `~/.minirc` to turn it on): clicking in the code area places the
  cursor there and switches to Visual mode (from Insert, Command,
  Search, or with the worktree/`:run` panel focused - a click always
  means "take me there now"); click-and-drag selects, the same as
  `Ctrl` + an arrow key; the scroll wheel moves the cursor a few lines
  at a time. Clicking the worktree panel focuses it and selects the
  entry under the cursor; clicking that same entry again (while
  already focused there) activates it - opens the file, or expands/
  collapses the directory - the "first click selects, second click
  opens" a mouse-driven file explorer is expected to have; its own
  scroll wheel moves the selection instead. Scrolling over the
  `:run`/`:lint`/`:cmd` panel scrolls it, same as `Up`/`Down` already
  do there. Off by default because enabling it hands click-and-drag
  over to Mini, so the terminal's own native text selection (and its
  copy shortcut) stops working with it while Mini has focus - most
  terminals let you hold `Shift` while dragging to get it back on
  demand, a terminal feature Mini doesn't control either way.
- The mode bar now shows "Mode: Worktree" while the worktree panel is
  focused, instead of whatever Visual/Insert/Command mode it's
  layered on top of underneath - clearer now that a click can move
  focus there without a deliberate `w` first.
- Removed the placeholder line number Mini used to draw one row past
  the end of the file (meant as a visual "this is where the file
  ends" cue) - real usage found it more distracting than orienting.
  Only the file's own real lines are drawn now. `PLACEHOLDER_COLOR`
  (the setting that colored it) is gone from `~/.minirc` accordingly;
  a leftover one in an existing file is simply never read anymore,
  not an error.

## 1.6.3 - 2026-09-15

- `mini --help` now reads like a short man page instead of a flat
  list mixing everything together: separate `NAME`, `DESCRIPTION`,
  `USAGE` (the three invocation forms - `mini`, `mini <file>`,
  `mini <directory>`), and `OPTIONS` (the `--flag` forms) sections.

## 1.6.2 - 2026-09-15

- Added Move mode in Visual mode (`m` to toggle): while active, `j`/
  `k`/`Up`/`Down` trade the current line's place with its neighbor
  above/below, repeatably, without pressing `m` again for each move -
  the closest practical equivalent to "hold a key and move lines
  around" a terminal program can actually detect, since there's no
  way to see a key being held down independently of others over a
  plain terminal connection the way a GUI can. With an active
  selection, the same keys move every line it spans as one block,
  trading places with whichever single line sits immediately above/
  below the whole block - the selection follows the move. A no-op at
  either edge of the file; every other key while active (`m`/`Esc`
  aside, either of which exits) is ignored rather than falling
  through to its usual meaning. Each move is its own undoable edit.
  The mode bar shows `(Move: ...)` as a reminder while it's on.

## 1.6.1 - 2026-09-15

- Added `a`/`f`/`s`/`d` in Visual mode, jumping to the start/end of
  the current line and the start/end of the file respectively - the
  same destinations `:a`/`:f`/`:b`/`:e` already jump to, just without
  going through `:`. `Ctrl+a`/`Ctrl+f`/`Ctrl+s`/`Ctrl+d` make the same
  four jumps while extending the selection, the same idea as `Ctrl` +
  an arrow key already does for plain movement. `Ctrl+d` now also
  reaches Visual mode - previously it was swallowed unconditionally
  outside the worktree panel (where it creates a new directory);
  Insert/Command/Search and every other context are unaffected, still
  swallowing it exactly as before.
- Added `mini --help`: usage for every command-line form `mini`
  accepts, plus a short description of the program, shown the same
  way (and dismissed the same way, `q`) as the in-editor `:help`
  screen - `:help` itself is unchanged, and still the place for the
  full in-editor command/keybinding reference.
- Any other `mini --something` (a typo'd or unrecognized flag) is now
  rejected outright ("not a valid command... use 'mini --help'")
  instead of being treated as a file name to open or, on save,
  silently create - a stray typo in a flag was never actually meant
  to create a file literally named that.

## 1.6.0 - 2026-09-15

- Added elastic tabstops: a tab typed after a line's own indentation
  now lines up, purely visually (the buffer still stores one literal
  tab character, never real spaces), with the same tab on every
  vertically-adjacent line that has one in the same position -
  `int` + `Tab` + `c;` above `size_t` + `Tab` + `l;` renders as a
  neatly aligned two-column table, re-aligning itself as lines are
  added, removed, or edited. A line without a tab there ends the
  block. Leading (indentation) tabs are unaffected, still expanding to
  `TAB_SIZE` columns exactly as before.
- Added `MAX_COLS_ENABLED` to `~/.minirc` (default `True`): turns the
  `MAX_COLS` ruler and its `●` too-long marker off entirely when set
  to `False`. The `●` marker a broken `#include`/`import` line gets is
  unaffected either way - unrelated check, same marker.
- Added an open-ended `[filetype:.ext]` dictionary to `~/.minirc`:
  overrides `MAX_COLS_ENABLED`/`MAX_COLS`/`INDENT_WITH_TABS`/
  `TAB_SIZE` for files with that extension, only for the keys a
  section actually sets - anything it leaves out still falls back to
  the plain top-level default. Entirely user-managed: add a
  `[filetype:.ext]` section for any extension you want your own
  settings for (not limited to the languages Mini highlights), remove
  one to go back to the default. An existing `~/.minirc` gets
  `MAX_COLS_ENABLED` added automatically on the next `mini --update`/
  reinstall, the same way any other new setting already is; the new
  dictionary itself needs nothing added, since an empty one (no
  `[filetype:...]` sections at all) is already its correct default
  state.

## 1.5.0 - 2026-09-14

- `:lint` now falls back to `flake8`/`mypy` bundled in Mini's own
  private virtualenv (installed alongside jedi - see "Installation")
  when a project has neither on its own `PATH` - previously `:lint`
  just failed outright in that case. A project's own `flake8`/`mypy`,
  wherever they are, are still always used ahead of Mini's. `mypy` is
  now always run with `--python-executable` pointed at the project's
  own resolved interpreter, regardless of which `mypy` binary actually
  runs it - so falling back to Mini's copy still resolves the
  project's real imports correctly (a "missing library stubs" note
  for an untyped dependency, say) instead of flagging every
  third-party import as unresolvable just because Mini's own
  virtualenv doesn't happen to have it installed. `flake8` needs no
  such flag - it's pure AST-based static analysis, never dependent on
  what's actually importable.

## 1.4.1 - 2026-09-14

- Fixed `Enter` accepting the highlighted entry of an open suggestion
  dropdown instead of inserting a newline - so finishing a perfectly
  valid, complete line that still happened to have 2+ matches open
  (`import re` also matches `reprlib`/`readline`/`resource`) no
  longer silently rewrites what you already typed the moment you
  press Enter to move on. `Enter` now always inserts a newline,
  dropdown or not; `Tab` remains the way to accept a suggestion.
- Fixed C/C++ `#include` completion inserting a duplicated, broken
  filename once a header name's own `.` had been typed (accepting
  `foo.h` after typing `foo.` produced `foo.foo.h`): ghost text and
  Tab-accept measured "what's already typed" using the same word-only
  scan as ordinary code completion, which stops at a `.` - a header
  name almost always has one. They now use the real text since the
  opening quote/bracket in this context instead.
- `#include <...>` (a system header) now waits for 2 typed characters
  before searching, the same as ordinary word completion - it used to
  search as soon as `<` was typed, filtering every header name in
  every one of the compiler's own include directories (easily
  thousands) on each keystroke, which could visibly lag. A local
  `#include "..."` is unaffected - too few candidates for this to
  matter, and being instant there mirrors Python's own local-module
  completion after `import`/`from`.

## 1.4.0 - 2026-09-14

- The startup update check now actually offers to update, instead of
  just pointing at `mini --update`: finding a newer commit prompts
  "Update now? (y/n)" right there (before the editor opens, so
  there's no unsaved buffer at risk) - accepting pulls, reinstalls
  (the exact same path `mini --update`/`install.sh` already use, so
  Mini's own jedi virtualenv gets created or updated too), and
  relaunches straight into the new version; declining, or a failed
  update, falls through to opening the editor normally on whatever
  was already installed. `mini --update` itself is unchanged.
- Python completion is now backed by `jedi` when it's available,
  replacing Mini's own regex/`ast`-based type inference for
  `name.<TAB>` and `from module import <TAB>` whenever it can answer -
  falling back to the exact same heuristics as before whenever it
  can't (not installed, or it genuinely finds nothing), so nothing
  regresses without it. This also covers cases the old heuristics
  explicitly gave up on: a chained call (`make().attr`), a subscript
  (`items[0].attr`), a function's own return type, and more.
  `make install` now creates a private virtualenv for Mini itself
  (`$LIBDIR/venv`) and installs `jedi` into it - never into the
  system Python or any project's own virtualenv - so this stays true
  to "no external dependencies" from the *system's* point of view; a
  dev checkout run directly with `python3 main.py` (no such venv)
  simply runs without it, exactly as before. Re-running the installer
  (which `mini --update` already does) leaves an already-working venv
  alone - no network call, no reinstall - and only (re)creates or
  reinstalls it if it's missing or broken; if venv creation or the
  `pip install` itself fails outright (no network, no `python3-venv`
  package, ...), Mini falls back to running on the system `python3`
  exactly as before, with no jedi-powered extras.
- Fixed `from module import ClassName` (and plain `from module import
  <TAB>`) never finding a module's or class's real members when that
  module needed something only installed in the edited project's own
  virtualenv, not Mini's: the introspection subprocess always ran
  with Mini's own interpreter regardless of which project was open,
  instead of the same resolved interpreter `:run`/`:lint` already
  use. Independent of the jedi work above - fixes this for a Mini
  running without jedi too.
- Fixed C/C++ completion silently hiding a name declared in an
  `#include`d header whenever any word already in the buffer happened
  to share the same prefix: buffer words and header words were tried
  as separate pools in a fixed order, and the first pool with any
  match at all won outright, discarding the other entirely. In real
  code, where some buffer word shares a common prefix (`get_`,
  `init_`, ...) with practically anything, this made header-declared
  names rarely surface at all. Both pools are now merged before
  matching.

## 1.3.0 - 2026-09-14

- A Python `import`/`from ... import ...` line that would actually
  fail now gets the same `●` marker as an overly long line, checked
  for real in an isolated subprocess (the same way `from X import`
  completion already works) - using the project's own resolved
  interpreter (an active `VIRTUAL_ENV`, a project `.venv`, or Mini's
  own as a last resort), never Mini's own outright, so a package
  only installed in the project's virtualenv isn't wrongly flagged.
  A plain top-level standard-library import is trusted without
  spawning anything.

## 1.2.5 - 2026-09-14

- An `#include` that doesn't actually resolve (a local header not
  found next to the file, or a system one not found in the
  compiler's own include directories) now gets the same `●` marker
  `MAX_COLS` uses for an overly long line, in the same gutter spot.
  Never shown for a `<...>` include with no `gcc`/`clang`/`cc` on
  `PATH` at all, for the same reason `#include <...>` completion
  itself already stays silent then.

## 1.2.4 - 2026-09-14

- Fixed C/C++ completion not looking inside a file's own `#include`s:
  a name declared in a locally-included header (`#include "mine.h"`)
  or a real system one (`#include <stdio.h>`) is now actually offered
  while typing elsewhere in the file - previously `#include` itself
  only ever offered header *names*, never what's declared inside
  them. Each header is read and word-scanned the same way the
  buffer's own words already are, cached for the rest of the session.

## 1.2.3 - 2026-09-14

- Fixed quote-matching splitting a docstring's coloring apart when
  the cursor landed on one of its own three-quote delimiters (it has
  no notion of a triple-quote as one unit, so it would pair up two
  of the docstring's own quote characters instead) - it now leaves a
  same-line triple-quoted string alone entirely.

## 1.2.2 - 2026-09-14

- Triple-quoted Python strings (`"""..."""`/`'''...'''`) are now
  colored as comments (`COMMENT_COLOR`) instead of as regular
  strings, matching how they're actually used - a docstring - far
  more often than not. Same single-line-only reach as everything
  else here: one that doesn't close on the line it starts isn't
  colored at all, same as before.

## 1.2.1 - 2026-09-14

- Fixed a real display bug: a line longer than the terminal's width
  used to overflow into the next screen row at column 1 (the
  terminal's own line-wrap, not Mini's), landing under the gutter
  instead of the text and getting stomped by whatever was drawn on
  that row next. Long lines now soft-wrap onto as many extra rows as
  needed, with each continuation row's gutter area left blank so the
  text still starts right where it should - visibly the same line,
  continued. Selection, bracket-matching, and the cursor all
  correctly follow a line across its wrap points.
- Comments are now colored (a new `COMMENT_COLOR` setting) instead of
  sharing the plain text color, for both Python's `#` and C/C++'s
  `//` and `/* */`.

## 1.2.0 - 2026-09-14

- Added syntax highlighting and autocompletion for C (`.c`/`.h`) and
  C++ (`.cpp`/`.hpp`/`.cc`/`.hh`/`.cxx`/`.hxx`): keywords, built-in
  type names, preprocessor directives, and string/char literals
  colored; word-based buffer completion plus C/C++'s own keyword
  vocabulary as a fallback - much shallower than the Python side, no
  type inference or macro awareness, just words and keywords.
  `#include "..."` completes local headers next to the file being
  edited; `#include <...>` completes real system header names, found
  by asking the actual `gcc`/`clang`/`cc` on `PATH` for its include
  search directories.

## 1.1.7 - 2026-09-14

- Performance: fixed two remaining sources of Insert-mode lag on
  large files. Autocompletion's buffer-word matching now uses binary
  search over a cached sorted list instead of scanning (and
  startswith-testing) every unique word in the file on each
  keystroke. Rendering is now differential - a screen row is only
  re-sent to the terminal when its own text actually changed since
  the last frame, and the blanket full-screen clear on every render
  is gone - so typing on one line, the common case, now only ever
  redraws that one row instead of the whole screen (roughly an 85%
  cut in bytes written per keystroke in testing). A resize, leaving
  the help screen, or the suggestion dropdown appearing/closing still
  triggers one full redraw, to never leave stale content on screen.

## 1.1.6 - 2026-09-14

- The update check now runs at most once every 4 hours instead of
  once a day. A session that stays open past that mark keeps checking
  in the background on the same schedule for as long as it's open,
  opening a new tab to announce an update if it finds one - previously
  only the check that ran once before the editor opened could ever
  notice.

## 1.1.5 - 2026-09-14

- Internal: split the single ~2600-line `text_editor.py` into
  focused modules by concern (`rendering.py`, `editing.py`,
  `commands.py`, `tabs.py`, `worktree.py`, `run_panel.py`,
  `autocomplete.py`, `highlighting.py`, `venv_detect.py`,
  `terminal.py`), composed back together as mixins on the
  `TextEditor` class in a much smaller `text_editor.py`. No behavior
  change - see the "Project structure" table in the README.

## 1.1.3 - 2026-09-14

- Added `Ctrl+H` in the worktree panel, toggling whether hidden
  files/directories (name starting with `.`) are shown - hidden by
  default, at every depth.
- Added `INDENT_WITH_TABS` (default `False`) and `TAB_SIZE` (default
  `4`) to `~/.minirc`: auto-indent, the bracket-splitting Enter, and
  the Tab key now insert spaces by default instead of always a tab
  character, and the display width of an actual tab character in the
  buffer follows `TAB_SIZE` instead of a hardcoded 4.
- Fixed auto-indent to carry over a line's *real* leading whitespace
  verbatim - it used to only recognize literal tab characters, so a
  space-indented line (now Mini's own default) would lose its
  indentation entirely on Enter instead of carrying it over.
- An update (`mini --update`, or re-running `make install`) now adds
  any setting or color key a newer Mini introduced but an existing
  `~/.minirc` doesn't have yet, appending it with its default value -
  every existing value, comment, and custom section is left exactly
  as it was. Previously a missing key only ever fell back to an
  invisible in-code default, never actually appearing in the file.
- The installer now also adds `~/.local/bin` to `~/.hellishrc`'s
  `PATH` (if present), alongside `~/.bashrc`/`~/.zshrc`/`~/.profile`.

## 1.1.2 - 2026-09-14

- Added `:cmd <text>`, running `text` as a `bash -c` command in the
  same output panel as `:run`/`:lint` (Ctrl+C, scrolling, and all).
  Unlike `:run`/`:lint`, it never forces a save of the current buffer
  and doesn't require it to have a file at all.

## 1.1.1 - 2026-09-14

- The `:run`/`:lint` output panel can now be scrolled independently of
  the live output (`Up`/`Down` a line at a time, `Ctrl+Up`/`Ctrl+Down`
  a page at a time) instead of only ever showing the tail end, and it
  keeps up to 10000 lines instead of 2000. Scrolling up freezes the
  view in place as more output arrives below it (`tail -f`-style);
  scrolling back down to the bottom resumes following it live.

## 1.1.0 - 2026-09-14

- `:run` and `:lint` now use a project's own virtualenv instead of
  always running Mini's own Python: an already-activated `VIRTUAL_ENV`
  wins outright, otherwise Mini looks for a `.venv`, `venv`, `env`, or
  `.env` directory starting at the file being edited and walking up to
  the worktree root. `:lint`'s `flake8`/`mypy` come from that same
  environment.
- Renamed the save/close commands to match vim's convention: `:s` is
  now `:w` (save), `:x` is now `:q` (close/exit), and `:sx`/`:xs` are
  now `:wq`/`:qw` - the `!` forced variants follow the same renaming
  (`:w!`, `:q!`, `:wq!`, `:qw!`). Since `:w` was already the worktree
  panel's visibility toggle, that command moved to `:tree`.
- Fixed a real slowdown when typing quickly in Insert mode: building
  the autocompletion word list used to rescan every line of the whole
  buffer on every keystroke. It's now cached per line, and the cache
  is invalidated precisely (only where a line's own text could have
  changed) instead of guessed at, so a fast typing burst on a large
  file no longer re-scans the entire file for each character.
- Fixed a similar slowdown with the worktree panel open: its
  directory listing used to be rebuilt from disk on every single
  keystroke anywhere in the editor while the panel was visible. It's
  now cached and only rebuilt when something that actually changes the
  listing happens (expanding/collapsing a directory, creating or
  deleting an entry, or showing/focusing the panel again).
- The undo/redo history is now a capped queue instead of a plain list,
  avoiding an ever more expensive trim step in long editing sessions.

## 1.0.1 - 2026-09-14

- General performance improvements.

## 1.0.0 - 2026-09-13

- `from module import ...` and `name.` autocompletion now cover every
  case consistently (imported classes, local files, packages and
  their submodules).

## 0.2.2 - 2026-09-13

- Minor visual bug fix.

## 0.2.1 - 2026-09-13

- Updated theme colors.
- `name.attr` suggestions also trigger right after a `.`, without
  needing to type any letters first, when the name's type is known.

## 0.2.0 - 2026-09-13

- Added `:lint`, running `flake8` + `mypy` on the current file in the
  same output panel `:run` uses.
- Fixed and improved word-based autocompletion; added multi-match
  suggestion dropdowns (previously only a single inline suggestion was
  possible).
- Added `--config` and `:config`, to open `~/.minirc` as a tab.
- Added `--uninstall`.
- Translated the editor's on-screen text to English.

## 0.1.0 - 2026-09-13

First versioned release, adding self-update support (`mini --update`)
on top of the editor's initial functionality: modal (Visual/Insert)
editing, tabs, the worktree file panel, `:run`, bracket/quote matching
and auto-closing, and auto-indentation.
