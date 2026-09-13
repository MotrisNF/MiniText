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
  (`__init__`, `__name__`, ...), built-in type names, and function
  calls/definitions, each in its own color.
- Autocompletion for `.py` files, drawing from words already used in
  the file plus Python's keywords and built-ins, and, after `import`
  or `from`, standard library modules as well as `.py` files and
  packages found next to the file being edited. `name.` after an
  assignment is type-aware: `patata = []` then `patata.app` only
  offers list methods (`append`, not `str`'s or `dict`'s), and
  `perro = Perro()` then `perro.la` offers `Perro`'s own methods -
  whether `Perro` is a class defined right in this file or one
  imported with `from module import Perro`. This only follows a
  single, literal `name = <expr>` line right before the cursor - no
  control flow, no return-type inference - and falls back to every
  builtin type's methods combined when nothing can be worked out. When
  the type is known this way, typing the `.` itself is enough to open
  the suggestions - no need to type any letters first, unlike every
  other completion context here, which needs at least 2.
  After `from module import `, it
  offers that module's actual members (`from sys import arg` suggests
  `argv`) - found by really importing the module in an isolated,
  short-lived subprocess, so this also works for your own local
  files, not just the standard library. A single match shows as
  inline "ghost text" (`Tab` accepts it); two or more open a dropdown
  below the cursor - `Up`/`Down` move through it, `Tab` or `Enter`
  accepts the highlighted entry, `Esc` dismisses it without leaving
  Insert mode. A module's names starting with a single underscore are
  offered too (only `__dunder__` names are hidden), since a small
  local file's real API is often just that. Suggestions never trigger
  inside a string or a comment, so typing free-form text there doesn't
  get treated as Python code.
- Matching-bracket and matching-quote highlighting, for `()`, `[]`,
  `{}`, `'` and `"`, in either direction and across lines.
- Auto-closing of brackets and quotes - only when the spot to the
  right is empty, whitespace, or another closing character, so typing
  one in the middle of existing text doesn't insert a stray partner -
  with smart backspace: deleting an opening character removes its
  auto-inserted counterpart too, but only if nothing was typed between
  them.
- Auto-indentation on Enter, carrying over the current line's
  indentation and adding one level after a trailing colon. Pressing
  Enter right between a matching pair of brackets (`foo(|)`) instead
  splits into three lines - the opening line, an empty line indented
  one level further where the cursor lands, and the closing bracket
  on its own line back at the original indentation.
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
- A theme system with three built-in palettes (`base`, `dark`,
  `light`), fully configurable through a plain-text config file, with
  an automatic backup that protects against invalid edits.
- Resize-aware rendering and a clean terminal handoff: the editor uses
  the terminal's alternate screen buffer, so nothing it draws leaks
  into your shell's scrollback.

## Requirements

- Linux or another Unix-like system with a terminal that supports
  ANSI escape sequences and 256 colors.
- Python 3.10 or newer, with no additional packages.

## Installation

From the project directory:

```sh
make install
```

This installs the `mini` command for the current user:

- The source files are copied to `~/.local/share/mini`.
- A launcher script is installed at `~/.local/bin/mini`.
- `~/.local/bin` is added to your `PATH` in `~/.bashrc`, `~/.zshrc`,
  and `~/.profile` (whichever exist), if it isn't there already.
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
```

The editor starts in Visual mode. Type `:help` at any time to see the
full command reference from inside the editor.

### Updating

An installed Mini (via `make install`) checks once a day, the first
time it's opened that day, whether the repository it was installed
from has new commits - a silent, non-blocking check that never delays
startup if there's no network. If it's behind, a one-line banner shows
before the editor opens (dismissed by pressing any key) pointing you
at `mini --update`, which pulls the latest changes and reinstalls
automatically. Running `mini --update` directly always re-checks,
regardless of when it last checked. This only works for a `make
install`-created install, not for running `python3 main.py` straight
from a checkout.

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
| `i`                       | Enter Insert mode                       |
| `w`                       | Focus the worktree panel (shows it first if hidden) |
| `/text`, Enter            | Search for `text`                       |
| `n`                       | Repeat the last search                  |
| `Ctrl+Z`                  | Undo                                    |
| `Ctrl+Y`                  | Redo                                    |
| `Tab` / `Shift+Tab`       | Switch to the next / previous tab       |

### Insert mode

| Key         | Action                                                    |
|-------------|------------------------------------------------------------|
| `Tab`       | Accept the current autocompletion suggestion, if any (otherwise inserts a tab) |
| `Enter`     | New line, auto-indented - or, while a suggestion dropdown is open, accepts the highlighted entry instead |
| `Up` / `Down` | Move the cursor - or, while a suggestion dropdown is open, move the highlighted entry instead |
| Backspace   | Delete backward; also removes an auto-closed bracket/quote pair if nothing was typed inside it |
| Delete      | Delete forward (the character under the cursor)            |
| `Esc`       | Dismiss the suggestion dropdown if one is open, otherwise return to Visual mode |

### Commands (type `:` from Visual mode, then Enter)

| Command       | Action                                              |
|---------------|-------------------------------------------------------|
| `:s`          | Save                                                 |
| `:x`          | Close the current tab (asking to save first if needed); exits if it's the last tab |
| `:sx`, `:xs`  | Save and close the current tab (or exit if it's the last one) |
| `:s!`         | Save every open tab, no confirmation                 |
| `:x!`         | Exit immediately, discarding unsaved changes in every tab |
| `:sx!`, `:xs!` | Save every open tab, then exit                      |
| `:l <n>`      | Jump to line `n`                                     |
| `:b`          | Jump to the beginning of the file                    |
| `:e`          | Jump to the end of the file                          |
| `:a`          | Jump to the start of the current line                |
| `:f`          | Jump to the end of the current line                  |
| `:d`          | Delete the current selection                         |
| `:d <n>`      | Delete line `n`                                      |
| `:c`          | Copy the selection, or the current line if none is selected |
| `:cl <n>`     | Copy line `n`                                        |
| `:v`          | Paste at the cursor                                  |
| `:vl <n>`     | Paste as a new line before line `n`                  |
| `:u`          | Undo                                                 |
| `:r`          | Redo                                                 |
| `:w`          | Toggle the worktree panel's visibility                |
| `:run`        | Run this file and show its output below the code (also `:terminal`) |
| `:help`       | Show the in-editor help screen                       |

### Running a file

`:run` (or `:terminal`) saves the current `.py` file, runs it with
`python3`, and splits the code area horizontally to show its output
live underneath as it prints. It uses a real pty for the child
process, so `input()` works: type while the panel is focused and
press Enter, exactly like a normal terminal. Ctrl+C sends an
interrupt to the running program (it does not affect Mini itself).
`Esc` unfocuses the panel while the program is still running, leaving
it going in the background - the output keeps updating even without
pressing anything - and closes the panel once you press `Esc` after
it has finished. Basic ANSI colors in the program's output are shown
as-is; cursor movement and other escape sequences are stripped, so
full-screen interactive programs (`curses` apps, `less`, and the
like) aren't supported here - only plain print-style output.

### Worktree panel

Focusing the panel with `w` shows it if it was hidden; leaving focus
(`v`, `Esc`, `:`, or `i`) hides it again in that case, restoring
whatever visibility it had before. If you showed it with `:w` instead,
it stays visible after you leave focus - `:w` is the "keep it open"
toggle, `w` is "let me look at it for a moment". `mini .` (or
`mini <dir>`) starts with the panel shown and focused, as it always
did.

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
except to refresh its backup copy.

```ini
THEME=base
SHOW_NUMBER_LINE=True
SHOW_LINE_INDICATOR=True

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

[dark]
...

[light]
...
```

- `THEME` selects the active section: `base`, `dark`, `light`, or any
  section name you add yourself.
- `SHOW_NUMBER_LINE` and `SHOW_LINE_INDICATOR` toggle the line-number
  gutter and the `->` current-line marker.
- Every color is an xterm 256-color palette number (0-255); a chart
  such as <https://www.ditig.com/256-colors-cheat-sheet> is a
  convenient reference.

If a value in `~/.minirc` is missing or invalid, Mini falls back to
`~/.minirc.bak` (a copy of the last known-good configuration), and
finally to its built-in defaults, so a mistake while editing the file
never prevents the editor from starting.

## Project structure

| File            | Purpose                                                  |
|-----------------|-------------------------------------------------------------|
| `main.py`       | Command-line entry point                                    |
| `text_editor.py`| The editor itself: terminal handling, rendering, key handling, editing commands, and the worktree explorer |
| `theme.py`      | Loads and validates `~/.minirc`, and resolves the active theme into ANSI color codes |
| `updater.py`    | `mini --update` and the once-a-day update check on startup    |
| `install.sh`    | Installs or uninstalls Mini and its default configuration    |
| `Makefile`      | `make install` / `make uninstall` wrappers around `install.sh` |
| `VERSION`       | Current version, printed by `mini --version`                 |

## Limitations

Mini is intentionally small. Some notable limitations:

- Syntax highlighting and autocompletion only apply to files with a
  `.py` extension.
- Completing names after `from module import `, or completing
  `name.` when `name` was assigned an imported class, actually
  imports that module (in an isolated subprocess, not Mini's own
  process) to see what it contains. For your own local files this
  means their top-level code really runs - the same as if you
  executed them - the first time you complete from them in a session;
  results are then cached until you restart Mini, even if the file
  changes again. A class defined right in the file being edited is
  read with `ast` instead (never executed), but only when the buffer
  currently parses as valid Python - a mid-edit syntax error just
  means no class-specific suggestions until it's valid again.
- Type-aware `name.` completion only recognizes `name` as whatever a
  single, literal `name = <expr>` assignment line before the cursor
  looks like - it doesn't track reassignment through branches or
  loops, return types of your own functions, or `module.Class(...)`
  written with the module name inline (only a `Class` imported
  directly via `from module import Class`).
- Syntax highlighting colors each line independently, without
  awareness of multi-line strings (a triple-quoted string spanning
  several lines won't be colored as one block). Bracket/quote
  matching itself does search across lines.
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
