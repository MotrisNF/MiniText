# Changelog

Notable changes to Mini, release by release. The version number here
matches `VERSION` (what `mini --version` prints).

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
  the current tab). Clicking it closes that tab - even one that isn't
  the active one - prompting to save first if it's modified, exactly
  like `:q` already does.
- Closing the last open tab (`:q`, the new tab-bar ×, or the new
  "Close Mini" button below) no longer exits Mini outright - it resets
  to a blank, unnamed buffer instead, the same state `mini` with no
  file argument starts in. Only closing a tab already in that exact
  state actually exits, so `:q` (or × / "Close Mini") a second time
  still quits normally.
- Added a centered "Close Mini" button, shown only with `MOUSE_ENABLED`
  on and only once down to that one blank/unnamed/unmodified tab - the
  only way left to quit with just a mouse, now that closing the last
  tab no longer does that on its own.

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
