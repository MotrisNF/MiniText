# Changelog

Notable changes to Mini, release by release. The version number here
matches `VERSION` (what `mini --version` prints).

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
