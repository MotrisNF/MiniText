# Changelog

Notable changes to Mini, release by release. The version number here
matches `VERSION` (what `mini --version` prints).

## Unreleased

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

- The update check now runs at most once every 4 hours instead of
  once a day. A session that stays open past that mark keeps checking
  in the background on the same schedule for as long as it's open,
  opening a new tab to announce an update if it finds one - previously
  only the check that ran once before the editor opened could ever
  notice.
- Internal: split the single ~2600-line `text_editor.py` into
  focused modules by concern (`rendering.py`, `editing.py`,
  `commands.py`, `tabs.py`, `worktree.py`, `run_panel.py`,
  `autocomplete.py`, `highlighting.py`, `venv_detect.py`,
  `terminal.py`), composed back together as mixins on the
  `TextEditor` class in a much smaller `text_editor.py`. No behavior
  change - see the "Project structure" table in the README.
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
- Added `:cmd <text>`, running `text` as a `bash -c` command in the
  same output panel as `:run`/`:lint` (Ctrl+C, scrolling, and all).
  Unlike `:run`/`:lint`, it never forces a save of the current buffer
  and doesn't require it to have a file at all.
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
