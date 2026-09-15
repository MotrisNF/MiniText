# Mini

Mini is a small terminal text editor written in pure Python, with no
external dependencies. It renders directly with ANSI escape sequences
in a raw-mode terminal, and includes syntax highlighting, inline
autocompletion, and a file explorer for Python files, while staying
usable as a general-purpose text editor for anything else.

## Features

- Modal editing (Visual and Insert modes), with text selection,
  copy/paste, undo/redo, and search.
- Line-oriented commands: jump to a line, copy or delete a specific
  line by number, and paste a line at a given position.
- Syntax highlighting for `.py` files: keywords, dunder names
  (`__init__`, `__name__`, ...), built-in type names, function
  calls/definitions, string literals (quotes included), and comments,
  each in its own color. `def` and `class` get a color of their own,
  separate from the rest of the keywords. A triple-quoted string
  (`"""..."""` or `'''...'''`) is treated as a comment - same color
  and all - rather than as a regular string, since that's how it's
  actually used (a docstring) far more often than not; quote-matching
  leaves it alone as that one block too, rather than pairing up two
  of its own three-quote delimiters (or splitting its coloring apart)
  depending on which quote the cursor happens to land on.
- Autocompletion for `.py` files, drawing from words already used in
  the file plus Python's keywords and built-ins, and, after `import`
  or `from`, standard library modules as well as `.py` files and
  directories found next to the file being edited - a directory
  counts whether or not it has an `__init__.py`, since Python can
  import a plain one as a namespace package too. `from a_package
  import ` offers both what that package's `__init__.py` actually
  defines and its submodules/subpackages (the `.py` files and
  directories inside it), together, since which one you mean depends
  on what you're about to type. `name.` after an
  assignment is type-aware: `patata = []` then `patata.app` only
  offers list methods (`append`, not `str`'s or `dict`'s), and
  `perro = Perro()` then `perro.la` offers `Perro`'s own methods -
  whether `Perro` is a class defined right in this file or one
  imported with `from module import Perro`. `self.` is its own case:
  it offers the enclosing class's own methods plus every attribute
  assigned anywhere in it as `self.attr = ...`, found by working out
  which `class ...:` contains the cursor rather than looking for an
  assignment (there isn't one - `self` is a parameter, never assigned
  itself). A string literal works the same way with no assignment at
  all: `"".up` (or `'x'.up`) offers `str`'s methods directly, since
  the dot right after a closing quote already says what it is. Beyond
  `self` and string literals, this only follows a single, literal
  `name = <expr>` line right before the cursor - no control flow, no
  return-type inference - and falls back to every builtin type's
  methods combined when nothing can be worked out. When
  the type is known this way, typing the `.` itself is enough to open
  the suggestions - no need to type any letters first, unlike every
  other completion context here, which needs at least 2.
  When `make install`'s own virtualenv for Mini has `jedi` in it (see
  "Installation" below), both `name.` and `from module import ` are
  tried through it first - real parsing and inference instead of
  Mini's own regex/`ast` heuristics, so it also covers a chained call
  (`make().attr`), a subscript (`items[0].attr`), or a return-type-
  dependent case the heuristics above give up on outright. Whenever
  jedi can't answer (not installed, or it genuinely finds nothing),
  the heuristics above run exactly as if jedi didn't exist, so nothing
  here is a hard requirement.
  After `from module import `, it
  offers that module's actual members (`from sys import arg` suggests
  `argv`) - found by really importing the module in an isolated,
  short-lived subprocess, so this also works for your own local
  files, not just the standard library. A single match shows as
  inline "ghost text" (`Tab` accepts it); two or more open a dropdown
  below the cursor - `Up`/`Down` move through it, `Tab` accepts the
  highlighted entry, `Esc` dismisses it without leaving Insert mode.
  `Enter` always inserts a newline, dropdown or not - it never doubles
  as an accept key, so finishing a line that happens to still have a
  dropdown open (`import re` matches `reprlib`/`readline`/... too)
  never silently rewrites what you already typed. A module's names
  starting with a single underscore are
  offered too (only `__dunder__` names are hidden), since a small
  local file's real API is often just that. Suggestions never trigger
  inside a string or a comment, so typing free-form text there doesn't
  get treated as Python code. An `import`/`from ... import ...` line
  that would actually fail - a module that can't be imported, or a
  name that doesn't really exist on it - gets the same `●` marker as
  an overly long line (see `MAX_COLS` below), checked the same way
  the completion above is: for real, in an isolated subprocess, using
  the same interpreter `:run`/`:lint` would actually use for this
  file (an active `VIRTUAL_ENV`, else a `.venv`/`venv`/`env`/`.env`
  found from the file up to the worktree root, else Mini's own) -
  never Mini's own interpreter outright, since a package only
  installed in the project's own virtualenv would otherwise be
  wrongly flagged as broken. A plain `import` of a top-level standard
  library module is trusted outright, without spawning anything.
- Syntax highlighting and autocompletion for `.c`/`.h` and
  `.cpp`/`.hpp`/`.cc`/`.hh`/`.cxx`/`.hxx` files too, in the same style
  as `.py` - keywords, built-in type names, preprocessor directives,
  string/char literals, and comments (both `//` and `/* */` - the
  same in C and C++) colored, plus word-based completion from
  the buffer and C's (or C++'s, with its own extra keywords like
  `class`/`namespace`/`template`) own vocabulary as a fallback. This
  is deliberately much shallower than the Python side: no type
  inference, no `self`/`->` awareness, no macro expansion - just
  words and keywords. `#include "..."` offers `.h`/`.hpp` files next
  to the one being edited, the same way Python offers local `.py`
  files after `import`; `#include <...>` instead offers real system
  header names, found by asking whichever of `gcc`/`clang`/`cc` is on
  `PATH` for its own include search directories (the same
  "introspect the real thing" approach as Python's module
  completion, one layer down) - needing none of them just means this
  one specific case offers nothing, the same as `:lint` finding
  neither a project's own `flake8`/`mypy` nor Mini's bundled fallback
  for them (see "Installation"). Beyond completing the `#include` line
  itself, every header a file's own `#include`s name - local or
  system, resolved the exact same way - actually gets read and
  word-scanned too, so a name declared in one of them (`#include
  "mine.h"` and it declares `mi_funcion`, or `#include <stdio.h>`
  and `printf`) is offered while typing anywhere else in the file,
  not just while completing the `#include` line. An `#include` that
  doesn't actually resolve - a local header not found next to the
  file, or a system one not found in the compiler's own include
  directories - gets the same `●` marker `MAX_COLS` uses for an
  overly long line, in the same gutter spot. With no `gcc`/`clang`/
  `cc` on `PATH` at all, a `<...>` include is never marked this way -
  there'd be no way to tell "doesn't exist" apart from "can't check",
  and marking every one would be worse than marking none.
- Matching-bracket and matching-quote highlighting, for `()`, `[]`,
  `{}`, `'` and `"`, in either direction and across lines.
- Auto-closing of brackets and quotes - only when the spot to the
  right is empty, whitespace, or another closing character, so typing
  one in the middle of existing text doesn't insert a stray partner -
  with smart backspace: deleting an opening character removes its
  auto-inserted counterpart too, but only if nothing was typed between
  them.
- Auto-indentation on Enter, carrying over the current line's actual
  indentation - whatever mix of tabs/spaces it already is - and
  adding one new level (a tab or `TAB_SIZE` spaces, per
  `INDENT_WITH_TABS`) after a trailing colon. Pressing Enter right
  between a matching pair of brackets (`foo(|)`) instead splits into
  three lines - the opening line, an empty line indented one level
  further where the cursor lands, and the closing bracket on its own
  line back at the original indentation.
- A worktree file explorer shown as a side panel next to the editor,
  for browsing, opening, creating, and deleting files and directories
  without leaving the terminal. Opening a file from the panel always
  gives it its own tab (switching to it instead if it's already
  open), so every file you open stays open; `Tab`/`Shift+Tab` cycle
  forward/backward between open tabs in Visual mode. A tab bar always
  sits at the very top of the
  screen, right above the code - the active tab shares the editor's
  own background, inactive tabs are drawn in a muted shade, separated
  by a thin vertical line.
- `:run` executes the current `.py` file and streams its output live
  in a split below the code, over a real pty so `input()` works;
  Ctrl+C interrupts the running program without affecting Mini.
  `:lint` runs `flake8` and `mypy` on it the same way.
- A configurable line-length ruler (`MAX_COLS`, default 79 - flake8's
  own default) drawn on every line that doesn't already reach it;
  going past it anyway marks that line with a `●` in the gutter. Can
  be turned off entirely (`MAX_COLS_ENABLED=False`) or overridden per
  file extension, along with `INDENT_WITH_TABS`/`TAB_SIZE`, through an
  open-ended `[filetype:.ext]` dictionary in `~/.minirc` - see
  "Configuration" below.
- Elastic tabstops: a tab typed after a line's own indentation lines
  up, purely visually, with the same tab on every adjacent line that
  has one in the same position - `int` + `Tab` + `c;` above `size_t` +
  `Tab` + `l;` renders as a neatly aligned two-column table, and stays
  aligned as lines are added, removed, or edited. See "Configuration"
  below for the details and one real interaction with Insert mode's
  autocompletion worth knowing about.
- A line too long for the terminal's width soft-wraps onto as many
  extra screen rows as it takes, instead of overflowing into the next
  row at column 1 (the terminal's own doing, not Mini's, and the
  usual way this looks broken) or getting cut off. A continuation
  row's gutter area is left blank rather than repeating the line
  number, so the text still starts right where a first row's text
  would - visibly still the same line, continued. This is purely
  about fitting on screen: moving with the arrow keys, search, and
  everything else still works a line at a time, not a screen-row at a
  time.
- A theme system with three built-in palettes (`base`, `dark`,
  `light`), fully configurable through a plain-text config file, with
  an automatic backup that protects against invalid edits.
- Resize-aware rendering and a clean terminal handoff: the editor uses
  the terminal's alternate screen buffer, so nothing it draws leaks
  into your shell's scrollback.

## Requirements

- Linux or another Unix-like system with a terminal that supports
  ANSI escape sequences and 256 colors.
- Python 3.10 or newer. No packages need to be installed by hand -
  Mini needs none to run, and `make install` manages its own private
  copies of the few optional extras it can use (see "Installation"
  below).

## Installation

From the project directory:

```sh
make install
```

This installs the `mini` command for the current user:

- The source files are copied to `~/.local/share/mini`.
- A private virtualenv for Mini itself is created at
  `~/.local/share/mini/venv`, with `jedi` (better Python completion -
  see the `name.`/`from module import` description above), `flake8`,
  and `mypy` (a fallback for `:lint` - see its own description below)
  installed into it - never into your system Python or any project's
  own virtualenv. Mini runs from this virtualenv rather than the
  system `python3` from here on, though it needs nothing in it to
  work at all. If it can't be created or the packages can't be
  installed (no network, no `python3-venv` package, ...), Mini falls
  back to the system `python3` instead, without those extras - either
  way the install still succeeds. Re-running the installer (as
  `mini --update` already does) leaves an already-working virtualenv
  alone rather than recreating it every time.
- A launcher script is installed at `~/.local/bin/mini`.
- `~/.local/bin` is added to your `PATH` in `~/.bashrc`, `~/.zshrc`,
  `~/.profile`, and `~/.hellishrc` (whichever exist), if it isn't
  there already.
- A default `~/.minirc` (and its backup, `~/.minirc.bak`) is created
  if you don't already have one. An existing `~/.minirc` is never
  overwritten.

Override the install locations if needed:

```sh
make install PREFIX=/custom/prefix
make install BINDIR=/custom/bin LIBDIR=/custom/lib/mini
```

To remove everything the installer created, including `~/.minirc` and
its backup:

```sh
make uninstall
```

## Usage

```sh
mini                # start with an empty, unnamed buffer
mini path/to/file.py  # open a file (created on save if it doesn't exist)
mini .               # open the worktree file explorer for a directory
mini path/to/dir     # same, for a specific directory
mini --version       # print the installed version
mini --update        # check for updates and install them if found
mini --config        # open ~/.minirc as a tab
mini --uninstall     # remove Mini and its configuration
mini --help          # show usage and a brief description (press q to exit)
```

The editor starts in Visual mode. Type `:help` at any time to see the
full command reference from inside the editor; `mini --help` shows the
command-line usage above instead, without opening the editor itself -
also dismissed with `q`. Any other `--something` is rejected outright
("not a valid command") instead of being treated as a file name to
open or create, since a stray typo in a flag (`mini --hlep`) almost
certainly wasn't meant to create a file literally called that.

### Updating

An installed Mini (via `make install`) checks the repository it was
installed from for new commits at most once every 4 hours - a silent,
non-blocking check that never delays startup if there's no network.
If it's behind when you open Mini, it asks right there, before the
editor opens - "Update now? (y/n)" - since there's no unsaved buffer
yet at that point for an update to put at risk. Answering `y` pulls
the latest changes, reinstalls (the same as `mini --update` below),
and relaunches straight into the new version; anything else (`n`,
Enter, Esc, ...) skips it and opens the editor normally, on whatever
was already installed. If a session stays open past that 4-hour mark
instead, a background check keeps running on that same schedule for
as long as Mini stays open; finding an update there opens a new,
unnamed tab announcing it (close it with `:q` like any other tab) -
nothing else about the session is disturbed, and updating from there
still means running `mini --update` yourself (or answering the prompt
on your next fresh launch) - a session already in progress, with
buffers open, is not the place to update out from under itself.
`mini --update` itself pulls the latest changes and reinstalls
automatically, always re-checking regardless of when it last checked,
whether or not it was already behind. This only works for a
`make install`-created install, not for running `python3 main.py`
straight from a checkout. See [CHANGELOG.md](CHANGELOG.md) for what an
update actually brings.

Either way, the reinstall step also carries your `~/.minirc` forward:
any setting or color key a newer Mini added that your file doesn't
have yet gets appended to it, with its default value, right next to
whatever's already there - every existing value, comment, and custom
section is left untouched. That way a new setting is something you
can actually see and tweak, not just an invisible fallback you'd
never know existed.

## Modes

- **Visual**: the default mode. Movement, selection, search, and all
  `:` commands happen here.
- **Insert**: for typing text. Enter it with `i` from Visual mode,
  leave it with `Esc`.
- **Worktree**: a file explorer panel for the working directory, shown
  down the left side of the screen next to the editor. Focus it with
  `w` from Visual mode; it stays visible while you go on editing.

## Key reference

### Movement and selection (Visual mode)

| Key                     | Action                                   |
|--------------------------|-------------------------------------------|
| Arrow keys, or `h`/`j`/`k`/`l` | Move left/down/up/right             |
| A number, then a move key | Repeat that move that many times (`5l` moves right 5 times). The number stays active for further taps of a move key too - handy if it auto-repeats a digit and a movement key together - until you type a new number or press a non-movement key |
| `Ctrl` + arrow key        | Extend the selection while moving       |
| `a` / `f`                 | Jump to the start / end of the current line |
| `s` / `d`                 | Jump to the start / end of the file     |
| `Ctrl+a` / `Ctrl+f` / `Ctrl+s` / `Ctrl+d` | Same jumps as `a`/`f`/`s`/`d`, extending the selection while moving - the same idea as `Ctrl` + arrow key, just to these four destinations instead |
| `m`                        | Toggle Move mode (see below)            |
| `i`                       | Enter Insert mode                       |
| `w`                       | Focus the worktree panel (shows it first if hidden) |
| `/text`, Enter            | Search for `text`                       |
| `n`                       | Repeat the last search                  |
| `Ctrl+Z`                  | Undo                                    |
| `Ctrl+Y`                  | Redo                                    |
| `Tab` / `Shift+Tab`       | Switch to the next / previous tab       |

### Move mode

`m` toggles Move mode - there's no way for a terminal program to
detect a key being *held down* alongside another one, so this is the
practical equivalent: press `m` once, then `j`/`k` or `Up`/`Down`
(as many times as you like, without pressing `m` again) trade the
current line's place with the line directly above/below it. With an
active selection, the same keys move every line the selection spans
as one block, trading places with whichever single line sits
immediately above/below the whole block - the selection follows the
move, still highlighting the same content. A no-op at either edge of
the file. Every other key while in Move mode (except `m` or `Esc`,
either of which exits back to plain Visual mode) is ignored rather
than falling through to its usual meaning; each move is a normal,
undoable edit (`Ctrl+Z` steps back through them one at a time). The
mode bar shows `(Move: ...)` while it's active as a reminder.

### Insert mode

| Key         | Action                                                    |
|-------------|------------------------------------------------------------|
| `Tab`       | Accept the current autocompletion suggestion, if any (otherwise inserts a tab) |
| `Enter`     | New line, auto-indented - always, even while a suggestion dropdown is open (use `Tab` to accept a suggestion instead) |
| `Up` / `Down` | Move the cursor - or, while a suggestion dropdown is open, move the highlighted entry instead |
| Backspace   | Delete backward; also removes an auto-closed bracket/quote pair if nothing was typed inside it |
| Delete      | Delete forward (the character under the cursor)            |
| `Esc`       | Dismiss the suggestion dropdown if one is open, otherwise return to Visual mode |

### Commands (type `:` from Visual mode, then Enter)

| Command       | Action                                              |
|---------------|-------------------------------------------------------|
| `:w`          | Save                                                 |
| `:q`          | Close the current tab (asking to save first if needed); exits if it's the last tab |
| `:wq`, `:qw`  | Save and close the current tab (or exit if it's the last one) |
| `:w!`         | Save every open tab, no confirmation                 |
| `:q!`         | Exit immediately, discarding unsaved changes in every tab |
| `:wq!`, `:qw!` | Save every open tab, then exit                      |
| `:l <n>`      | Jump to line `n`                                     |
| `:b`          | Jump to the beginning of the file (also plain `s` in Visual mode) |
| `:e`          | Jump to the end of the file (also plain `d` in Visual mode) |
| `:a`          | Jump to the start of the current line (also plain `a` in Visual mode) |
| `:f`          | Jump to the end of the current line (also plain `f` in Visual mode) |
| `:d`          | Delete the current selection                         |
| `:d <n>`      | Delete line `n`                                      |
| `:c`          | Copy the selection, or the current line if none is selected |
| `:cl <n>`     | Copy line `n`                                        |
| `:v`          | Paste at the cursor                                  |
| `:vl <n>`     | Paste as a new line before line `n`                  |
| `:u`          | Undo                                                 |
| `:r`          | Redo                                                 |
| `:tree`       | Toggle the worktree panel's visibility                |
| `:run`        | Run this file and show its output below the code (also `:terminal`) |
| `:lint`       | Run flake8 + mypy on this file, output shown the same way |
| `:cmd <text>` | Run `text` as a bash command, output shown the same way |
| `:help`       | Show the in-editor help screen                       |

### Running a file

`:run` (or `:terminal`) saves the current `.py` file, runs it, and
splits the code area horizontally to show its output live underneath
as it prints. It uses a real pty for the child process, so `input()`
works: type while the panel is focused and press Enter, exactly like
a normal terminal. Ctrl+C sends an interrupt to the running program
(it does not affect Mini itself).

`Esc` unfocuses the panel while the program is still running, leaving
it going in the background - the output keeps updating even without
pressing anything - and closes the panel once you press `Esc` after
it has finished. Basic ANSI colors in the program's output are shown
as-is; cursor movement and other escape sequences are stripped, so
full-screen interactive programs (`curses` apps, `less`, and the
like) aren't supported here - only plain print-style output.

The panel keeps up to 10000 lines and can be scrolled independently
of the live output: `Up`/`Down` move it a line at a time,
`Ctrl+Up`/`Ctrl+Down` a page at a time. Scrolling up leaves the view
exactly where it is even as more output keeps arriving below it (the
divider line shows which lines are on screen out of the total while
you're scrolled away from the bottom); scrolling back down to the
very bottom resumes following the output live, the same as when you
haven't scrolled at all.

Which `python3` runs the file: if the shell Mini was launched from
already has a virtualenv active (`VIRTUAL_ENV` is set), that one is
used outright; otherwise Mini looks for a virtualenv of its own
(`.venv`, `venv`, `env`, or `.env`) starting at the file's own
directory and walking up to the worktree root, and falls back to
Mini's own interpreter if none is found. The same resolution feeds
`:lint` too, so a project's own `flake8`/`mypy` are used ahead of
whatever's on the system `PATH`.

`:lint` saves the file and runs `flake8` then `mypy` on it in that
same output panel (so it's Ctrl+C-able and closes with `Esc` the same
way), deleting `.mypy_cache` once both finish. A project's own
`flake8`/`mypy` (found the same way as above) are always used first;
failing that, Mini's own bundled copies - installed into its private
virtualenv alongside jedi (see "Installation") - are tried as a
fallback, so `:lint` still works for a project with neither. `mypy`
is always told to resolve imports as the project's own interpreter
would (`--python-executable`), even when it's Mini's own bundled
`mypy` doing the checking - so falling back to it still means real
type-checking against what the project actually has installed,
instead of "cannot find module" for every third-party import Mini's
own virtualenv doesn't happen to have. If neither the project nor
Mini has them (no network at install time, say), `:lint` fails
outright, same as always.

`:cmd <text>` runs `text` as a `bash -c` command in that same panel -
for anything that isn't about running the current file itself
(installing a dependency, listing a directory, activating a venv for
that one command, ...). It never saves or requires the current
buffer to have a file at all: it runs next to the file being edited
if there is one, or at the worktree root otherwise. Its subprocess's
`PATH` gets the same virtualenv-first treatment as `:run`/`:lint`.
Each `:cmd` is its own isolated process like `:run` is - nothing it
does (`source some/venv/bin/activate` included) persists into a later
`:run` or `:cmd`, since that process is already gone by the time the
next one starts.

### Worktree panel

Focusing the panel with `w` shows it if it was hidden; leaving focus
(`v`, `Esc`, `:`, or `i`) hides it again in that case, restoring
whatever visibility it had before. If you showed it with `:tree`
instead, it stays visible after you leave focus - `:tree` is the
"keep it open" toggle, `w` is "let me look at it for a moment".
`mini .` (or `mini <dir>`) starts with the panel shown and focused,
as it always did.

Hidden files and directories (name starting with `.`) are hidden by
default, at every depth - `Ctrl+H` toggles showing them.

While the panel is visible, the status/command line and the mode bar
at the bottom start right where the panel ends, lining up with the
code above them instead of running under the panel.

| Key            | Action                                                     |
|----------------|---------------------------------------------------------------|
| Up / Down, or `j`/`k` | Move the selection                                      |
| `l`            | Expand a directory                                             |
| `h`            | Collapse a directory                                           |
| Enter          | Open a file as a tab (switching to it if already open), or expand/collapse a directory |
| Ctrl+F         | Create a new file (prompts for a name)                         |
| Ctrl+D         | Create a new directory (prompts for a name)                    |
| Ctrl+H         | Toggle showing hidden files/directories (names starting with `.`) |
| Delete         | Delete the selected file or directory, after confirming        |
| `v`, `Esc`     | Return focus to the editor                                     |
| `:`, `i`       | Return focus to the editor directly in Command or Insert mode  |

### Tabs

Every open file lives in its own tab, keeping its own undo history,
cursor position, and unsaved-changes state. Opening a file from the
worktree panel (with Enter) always gives it a tab of its own -
switching to it instead if it's already open - reusing an empty,
untouched buffer if that's what you started from, so you don't end
up with a stray blank tab. Switch between tabs with `Tab` in Visual
mode.

The tab bar is always shown, as the very first row of the screen -
even with a single tab open. Each tab is a colored block with the
file name (a filled circle before the name marks unsaved changes);
the active tab's block matches the editor's own background so it
reads as "in front", while inactive tabs use a visibly muted shade,
with a thin vertical line separating each one.

New files and directories are created inside whichever directory you
last expanded; collapsing a directory moves that target back up to
its parent. Opening a file while the current buffer has unsaved
changes asks whether to save them first.

## Configuration

Mini reads `~/.minirc` on startup. The installer creates one with
sensible defaults; you can edit it freely; it is never overwritten
except to refresh its backup copy - and to add any setting a newer
Mini introduces after an update, if your file doesn't have it yet
(see "Updating" above).

```ini
THEME=base
SHOW_NUMBER_LINE=True
SHOW_LINE_INDICATOR=True
MAX_COLS_ENABLED=True
MAX_COLS=79
INDENT_WITH_TABS=False
TAB_SIZE=4

[base]
BACKGROUND_COLOR=235
TEXT_COLOR=252
LINE_NUMBER_COLOR=244
CURRENT_LINE_INDICATOR_COLOR=214
BRACKET_MATCH_COLOR=238
KEYWORD_COLOR=33
DUNDER_COLOR=11
TYPE_COLOR=2
FUNCTION_COLOR=5
SUGGESTION_COLOR=244
PLACEHOLDER_COLOR=244
INACTIVE_TAB_COLOR=232
RULER_COLOR=238
LINE_LENGTH_ERROR_COLOR=196
STRING_COLOR=117
DECLARATION_COLOR=203
COMMENT_COLOR=108

[dark]
...

[light]
...

[filetype:.js]
MAX_COLS=100
INDENT_WITH_TABS=False
TAB_SIZE=2
```

- `THEME` selects the active section: `base`, `dark`, `light`, or any
  section name you add yourself.
- `SHOW_NUMBER_LINE` and `SHOW_LINE_INDICATOR` toggle the line-number
  gutter and the `->` current-line marker.
- `MAX_COLS` (default `79`, flake8's own default) draws a thin ruler
  at that column on every line - only where the line doesn't already
  reach it, so typing past it naturally overlaps and covers the ruler
  instead of the two fighting for the same spot. A line that's
  actually longer than `MAX_COLS` gets a `●` in `LINE_LENGTH_ERROR_COLOR`
  where its line number/marker would be, instead of the ruler - the
  same marker a C/C++ file's own unresolved `#include` gets, and a
  `.py` file's own broken `import`/`from ... import ...` line, all in
  that same spot. `MAX_COLS_ENABLED` (default `True`) turns both the
  ruler and the length flagging off entirely when set to `False` -
  the `●` marker for a broken `#include`/import still shows either
  way, since that's a different check with nothing to do with a
  line's length.
- `INDENT_WITH_TABS` (default `False`) picks what auto-indent, the
  bracket-splitting Enter, and the Tab key insert for one new level
  of indentation: a tab character (`True`) or `TAB_SIZE` spaces
  (`False`). It only affects newly-inserted indentation - a line's
  existing leading whitespace, whatever it already is, is always
  carried over verbatim by Enter. `TAB_SIZE` (default `4`) is also
  how wide an actual tab character displays as, wherever one appears
  in a line (typed, pasted, or already in a file you opened) - except
  an inline (non-leading) one; see "Elastic tabstops" below.
- A `[filetype:.ext]` section (the extension, dot included - `.js`,
  `.rs`, whatever you want) overrides `MAX_COLS_ENABLED`/`MAX_COLS`/
  `INDENT_WITH_TABS`/`TAB_SIZE` for files with that extension - only
  the keys it actually sets; anything it leaves out still falls back
  to the plain top-level default above. This is a fully open,
  user-extensible dictionary, not a fixed list of "known" languages:
  add a `[filetype:.ext]` section for any extension you want your own
  settings for, and delete one to go back to the default - Mini
  itself never writes one for you.
- Every color is an xterm 256-color palette number (0-255); a chart
  such as <https://www.ditig.com/256-colors-cheat-sheet> is a
  convenient reference. `RULER_COLOR` and `LINE_LENGTH_ERROR_COLOR`
  control the two `MAX_COLS` indicators above.

If a value in `~/.minirc` is missing or invalid, Mini falls back to
`~/.minirc.bak` (a copy of the last known-good configuration), and
finally to its built-in defaults, so a mistake while editing the file
never prevents the editor from starting. A `[filetype:...]` section
follows the same rule key-by-key: an invalid value for one of its
keys is simply left out, falling back to the top-level default for
that key alone, without affecting the section's other keys.

### Elastic tabstops

A tab character typed *after* a line's own indentation - not one of
the leading tabs/spaces that make up the indentation itself, one
later in the line - is treated as a column separator rather than
plain whitespace, "elastic tabstops" style: it's padded, purely for
display (the buffer still stores one literal tab character, never
real spaces), to line up with the same separator on every
vertically-adjacent line that also has one at that same position.
Typing `int` + `Tab` + `c;`, then `size_t` + `Tab` + `l;` on the next
line, renders as:

```
int    c;
size_t l;
```

Add a third, wider line the same way and the whole block re-aligns to
fit it - no manual re-alignment, ever. A line with no tab there (or a
blank line) ends the block; anything below it starts a new one. Only
that first separator has to line up for a whole line to become part
of one - it works the same way with two or more separators per line,
each column aligning independently of the others. Leading
(indentation) tabs are never affected - those still expand to
`TAB_SIZE` columns exactly as before, whether or not the line also has
elastic ones later on.

One real interaction to know about: `Tab` in Insert mode accepts the
current autocompletion suggestion when one is showing (see "Key
reference" below), *before* it ever inserts a literal tab character.
`int` alone already matches `int8_t`/`int16_t`/.../`intptr_t`, so
`Tab` right after typing it completes to one of those instead of
inserting the separator - press `Esc` first to dismiss the dropdown,
*then* `Tab`, to actually get the tab character in a case like that.

## Project structure

| File               | Purpose                                                  |
|--------------------|-------------------------------------------------------------|
| `main.py`          | Command-line entry point                                    |
| `text_editor.py`   | The `TextEditor` class itself: top-level state, `__init__`, and the main key-reading loop that routes each keypress to whichever mixin below handles it |
| `rendering.py`     | Turning editor state into the ANSI-escaped frame written to the terminal: the tab bar, bracket/quote matching, the help screen, `render()` |
| `editing.py`       | Core buffer mutations: cursor movement, undo/redo, selection, insert/backspace/delete, paste, auto-indenting Enter |
| `commands.py`      | The `:` command line: parsing, dispatch, save/close, line-numbered operations, search |
| `tabs.py`          | Multi-tab buffer lifecycle: switching tabs, reading files from disk |
| `worktree.py`      | The worktree file explorer panel: listing, expanding/collapsing, creating/deleting entries |
| `run_panel.py`     | `:run`/`:lint`/`:cmd`'s shared pty-backed output panel |
| `autocomplete.py`  | Word/keyword/module/type-aware suggestions for `.py`, and word/keyword/`#include` suggestions for C/C++ |
| `highlighting.py`  | Python and C/C++ syntax highlighting for one line at a time  |
| `languages.py`     | File-extension-to-language detection and the C/C++ keyword/type vocabularies |
| `venv_detect.py`   | Virtualenv detection for `:run`/`:lint`/`:cmd`                |
| `terminal.py`      | Raw terminal mode, key reading, and the resize/output wakeup plumbing |
| `theme.py`         | Loads and validates `~/.minirc`, and resolves the active theme into ANSI color codes |
| `updater.py`       | `mini --update` and the once-a-day update check on startup    |
| `install.sh`       | Installs or uninstalls Mini and its default configuration    |
| `Makefile`         | `make install` / `make uninstall` wrappers around `install.sh` |
| `VERSION`          | Current version, printed by `mini --version`                 |
| `CHANGELOG.md`     | What changed in each version                                 |

## Limitations

Mini is intentionally small. Some notable limitations:

- Elastic tabstops (see "Configuration") have no notion of strings or
  comments: a tab inside either of those is still treated as a column
  separator like any other, same as everything else here that colors
  or completes one line at a time without deeper parsing. A block's
  width is also recomputed from scratch on every single render with
  no cross-render cache, which is unnoticeable for the small,
  deliberate tables this feature is actually meant for, but means an
  unusually large single block (thousands of aligned lines) would
  cost more per keystroke than a typical file does.
- Syntax highlighting and autocompletion only apply to `.py`,
  `.c`/`.h`, and `.cpp`/`.hpp`/`.cc`/`.hh`/`.cxx`/`.hxx` files - a
  `.h` file is always treated as C, never C++, since there's no
  reliable way to tell them apart by name alone.
- The C/C++ side is word/keyword completion only - none of the
  Python side's type inference, `self`/`->` awareness, or macro
  expansion.
- Without jedi (see "Installation"), completing names after `from
  module import `, or completing `name.` when `name` was assigned an
  imported class, actually imports that module (in an isolated
  subprocess, using the project's own resolved interpreter - not
  necessarily Mini's own) to see what it contains. For your own local
  files this means their top-level code really runs - the same as if
  you executed them - the first time you complete from them in a
  session; results are then cached until you restart Mini, even if
  the file changes again. A class defined right in the file being
  edited is read with `ast` instead (never executed), but only when
  the buffer currently parses as valid Python - a mid-edit syntax
  error just means no class-specific suggestions until it's valid
  again. jedi, when available, replaces all of this with its own real
  analysis - it neither executes your modules nor needs `ast` fallback
  logic of its own, though it's still subject to the same "cached
  until Mini restarts" behavior here, for the same reason.
- Without jedi, type-aware `name.` completion only recognizes `name`
  as whatever a single, literal `name = <expr>` assignment line before
  the cursor looks like - it doesn't track reassignment through
  branches or loops, return types of your own functions, or
  `module.Class(...)` written with the module name inline (only a
  `Class` imported directly via `from module import Class`). jedi
  lifts all of these restrictions when it's available and can answer;
  Mini only falls back to this narrower heuristic when it can't.
- jedi runs in-process, synchronously, on Mini's own single-threaded
  key-reading loop - there's no timeout on it the way there is on the
  isolated-subprocess checks elsewhere. Its first use for a given
  import or class in a session can be noticeably slower than a plain
  buffer-word match (parsing/caching a large module or a cold
  environment probe); Mini itself doesn't cap this.
- Syntax highlighting colors each line independently, without
  awareness of multi-line constructs: a triple-quoted Python string,
  or a C/C++ `/* ... */` comment, spanning several lines won't be
  colored (or, for the comment, excluded from highlighting) as one
  block. Bracket/quote matching itself does search across lines.
- Undo/redo is granular: each keystroke that changes the text is its
  own undo step.
- Search is a plain, case-insensitive substring match; there is no
  regular-expression support.
- Module-name completion after `import`/`from` covers top-level
  standard library modules plus `.py` files and packages in the
  current file's own directory - not submodules, third-party
  packages, or the names inside a `from module import ...` clause.
- Only UTF-8 text files can be opened; a file that isn't valid UTF-8
  (a binary file, or text in another encoding) is refused with a
  status message instead of being loaded, so it can't be garbled by
  a lossy read-then-save.
- `:run` only knows how to run `.py` files with `python3`, and is not
  a full terminal emulator: it understands plain text and basic ANSI
  colors, but not cursor movement, so full-screen programs (`curses`
  apps, pagers, `ssh`, and the like) won't display correctly inside
  it.
- `:lint`'s "[Process finished with exit code N]" reflects the final
  `rm -rf .mypy_cache` step, not flake8's or mypy's own exit code -
  check the printed output itself for whether they found anything.
- `MAX_COLS`'s line-length check counts display columns (tabs count
  as the same 4 columns used everywhere else in Mini), while flake8's
  own E501 counts raw characters (a tab is 1) - the two only disagree
  when a line mixes tabs with long content, which is rare.
- A soft-wrapped line's `MAX_COLS` ruler is positioned assuming it
  falls within the first screen row of that line, which is normally
  true (`MAX_COLS` is usually smaller than a terminal's width) but
  could land oddly on an unusually narrow terminal. A single line
  that alone takes more screen rows than the whole editor area is
  tall still shows the cursor's own row correctly, but earlier rows
  of that same line scroll out of view above it rather than the view
  shrinking to show all of it at once.
- Virtualenv detection for `:run`/`:lint` only recognizes the Unix
  `bin/python3` (or `bin/python`) layout, matching Mini's own
  Linux/Unix-only reach - and treats a directory literally named
  `.env` as a virtualenv too, even though that name is more commonly
  used for environment-variable files elsewhere.
- A header's words, once read for completion, are cached for the
  rest of the session - editing that header file in another tab (or
  another program) isn't picked up until Mini is restarted. Removing
  an `#include` line can also leave that header's words still being
  offered for a little while: it's only actually forgotten the next
  time something forces a rescan (typing elsewhere after leaving the
  line the `#include` used to be on), not the instant it's deleted.
- Whether a Python `import` resolves is cached the same way (per
  interpreter, module, and names, for the rest of the session) - so
  `pip install`-ing a missing package in another terminal while Mini
  is open doesn't clear its `●` marker until Mini is restarted.
