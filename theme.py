"""Mini's theme/config loader.

Reads ~/.minirc (created by install.sh with sensible defaults on first
install) and exposes the resolved ANSI color codes and editor settings
as module attributes, so the rest of the editor keeps doing
`theme.KEYWORD_COLOR`, `theme.SHOW_NUMBER_LINE`, etc. without knowing
anything about the config file format.

~/.minirc layout::

    THEME=base
    SHOW_NUMBER_LINE=True
    SHOW_LINE_INDICATOR=True
    MAX_COLS_ENABLED=True
    MAX_COLS=79
    INDENT_WITH_TABS=False
    TAB_SIZE=4

    [base]
    BACKGROUND_COLOR=235
    ...

    [dark]
    ...

    [light]
    ...

    [filetype:.js]
    MAX_COLS=100
    INDENT_WITH_TABS=False
    TAB_SIZE=2

THEME picks which [section] is active - it can name any section in the
file, including ones the user adds themselves; sections that aren't
base/dark/light are just as valid. Each color value is an xterm
256-color palette number (0-255); whether a given key is used as a
foreground or a background is fixed (see _COLOR_KINDS below), not
something the user chooses.

A `[filetype:EXT]` section (EXT including the leading dot, e.g.
`.js`) overrides MAX_COLS_ENABLED/MAX_COLS/INDENT_WITH_TABS/TAB_SIZE
for files with that extension - only the keys it actually sets; any
key it leaves out still falls back to the plain top-level default
above. This dictionary is entirely user-opt-in and freely extensible:
there's no fixed list of "known" extensions - add a `[filetype:.ext]`
section for any extension you want your own settings for, and delete
one to go back to the default. See `settings_for(file_name)` below.

~/.minirc.bak is a safety net, not something meant to be hand-edited:
whenever ~/.minirc loads and validates cleanly, it's mirrored into
~/.minirc.bak. If ~/.minirc is later missing a key, has an invalid
value, or fails to parse altogether, the missing pieces are recovered
from ~/.minirc.bak before falling back to the hardcoded defaults below,
so a typo in a hand-edited color never breaks the editor.

Whenever a Mini update adds a setting or color key that an existing
~/.minirc doesn't have yet, install.sh calls `_migrate_rc_file` (via
`python3 theme.py --migrate <path>`) to append it - with its default
value - right into that file, so it stays visible and editable
instead of silently living only as an in-code fallback forever.
"""

import os
import sys

RC_PATH = os.path.expanduser("~/.minirc")
BACKUP_PATH = os.path.expanduser("~/.minirc.bak")

# Which SGR channel a color key controls: "fg" -> \x1b[38;5;Nm,
# "bg" -> \x1b[48;5;Nm. Fixed by key name, not user-configurable.
_COLOR_KINDS = {
    "BACKGROUND_COLOR": "bg",
    "TEXT_COLOR": "fg",
    "LINE_NUMBER_COLOR": "fg",
    "CURRENT_LINE_INDICATOR_COLOR": "fg",
    "BRACKET_MATCH_COLOR": "bg",
    "KEYWORD_COLOR": "fg",
    "DUNDER_COLOR": "fg",
    "TYPE_COLOR": "fg",
    "FUNCTION_COLOR": "fg",
    "SUGGESTION_COLOR": "fg",
    "ACTIVE_TAB_COLOR": "bg",
    "INACTIVE_TAB_COLOR": "bg",
    "RULER_COLOR": "fg",
    "LINE_LENGTH_ERROR_COLOR": "fg",
    "STRING_COLOR": "fg",
    "DECLARATION_COLOR": "fg",
    "COMMENT_COLOR": "fg",
}

DEFAULT_THEMES = {
    "base": {
        "BACKGROUND_COLOR": 235, "TEXT_COLOR": 252, "LINE_NUMBER_COLOR": 244,
        "CURRENT_LINE_INDICATOR_COLOR": 214, "BRACKET_MATCH_COLOR": 238,
        "KEYWORD_COLOR": 33, "DUNDER_COLOR": 11, "TYPE_COLOR": 2,
        "FUNCTION_COLOR": 5, "SUGGESTION_COLOR": 244,
        "ACTIVE_TAB_COLOR": 240, "INACTIVE_TAB_COLOR": 232,
        "RULER_COLOR": 238,
        "LINE_LENGTH_ERROR_COLOR": 196, "STRING_COLOR": 117,
        "DECLARATION_COLOR": 203, "COMMENT_COLOR": 108,
    },
    "dark": {
        "BACKGROUND_COLOR": 233, "TEXT_COLOR": 250, "LINE_NUMBER_COLOR": 240,
        "CURRENT_LINE_INDICATOR_COLOR": 208, "BRACKET_MATCH_COLOR": 236,
        "KEYWORD_COLOR": 39, "DUNDER_COLOR": 221, "TYPE_COLOR": 78,
        "FUNCTION_COLOR": 176, "SUGGESTION_COLOR": 240,
        "ACTIVE_TAB_COLOR": 242, "INACTIVE_TAB_COLOR": 236,
        "RULER_COLOR": 236,
        "LINE_LENGTH_ERROR_COLOR": 196, "STRING_COLOR": 117,
        "DECLARATION_COLOR": 203, "COMMENT_COLOR": 102,
    },
    "light": {
        "BACKGROUND_COLOR": 253, "TEXT_COLOR": 235, "LINE_NUMBER_COLOR": 246,
        "CURRENT_LINE_INDICATOR_COLOR": 166, "BRACKET_MATCH_COLOR": 250,
        "KEYWORD_COLOR": 18, "DUNDER_COLOR": 94, "TYPE_COLOR": 22,
        "FUNCTION_COLOR": 90, "SUGGESTION_COLOR": 246,
        "ACTIVE_TAB_COLOR": 231, "INACTIVE_TAB_COLOR": 250,
        "RULER_COLOR": 249,
        "LINE_LENGTH_ERROR_COLOR": 160, "STRING_COLOR": 25,
        "DECLARATION_COLOR": 160, "COMMENT_COLOR": 101,
    },
}
# flake8/pycodestyle's own default max-line-length, reused here so a
# fresh install's ruler lines up with what flake8 would flag anyway.
DEFAULT_MAX_COLS = 79
DEFAULT_INDENT_WITH_TABS = False
DEFAULT_TAB_SIZE = 4
DEFAULT_SETTINGS = {
    "THEME": "base", "SHOW_NUMBER_LINE": True, "SHOW_LINE_INDICATOR": True,
    "MAX_COLS_ENABLED": True, "MAX_COLS": DEFAULT_MAX_COLS,
    "INDENT_WITH_TABS": DEFAULT_INDENT_WITH_TABS, "TAB_SIZE": DEFAULT_TAB_SIZE,
    "MOUSE_ENABLED": False,
}
# Keys a [filetype:.ext] section may override - same names and same
# parsing as their top-level counterparts in DEFAULT_SETTINGS, just
# scoped to one extension instead of applying to every file.
_FILETYPE_BOOL_KEYS = ("MAX_COLS_ENABLED", "INDENT_WITH_TABS")
_FILETYPE_INT_KEYS = ("MAX_COLS", "TAB_SIZE")
FILETYPE_SECTION_PREFIX = "filetype:"


def _parse_bool(value, fallback):
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    return fallback


def _parse_positive_int(value, fallback):
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _parse_rc(path):
    """Returns (settings, themes) parsed from `path` - two dicts of raw
    strings, or ({}, {}) if the file is missing or unreadable."""
    settings = {}
    themes = {}
    section = None
    try:
        with open(path, "r", encoding="utf-8") as file:
            lines = file.readlines()
    except OSError:
        return settings, themes
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            themes.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if section is None:
            settings[key] = value
        else:
            themes[section][key] = value
    return settings, themes


def _resolve_settings(primary, backup):
    settings = dict(DEFAULT_SETTINGS)
    for key in (
        "SHOW_NUMBER_LINE", "SHOW_LINE_INDICATOR", "MAX_COLS_ENABLED",
        "INDENT_WITH_TABS", "MOUSE_ENABLED",
    ):
        for source in (primary, backup):
            if key in source:
                settings[key] = _parse_bool(source[key], settings[key])
                break
    for key in ("MAX_COLS", "TAB_SIZE"):
        for source in (primary, backup):
            if key in source:
                settings[key] = _parse_positive_int(
                    source[key], settings[key]
                )
                break
    for source in (primary, backup):
        if source.get("THEME"):
            settings["THEME"] = source["THEME"]
            break
    return settings


def _resolve_filetype_overrides(primary_themes, backup_themes):
    """{extension: {key: value}} built from every `[filetype:EXT]`
    section found in either file - `primary` (~/.minirc) wins over
    `backup` key-by-key, the same priority every other setting here
    uses. Purely user-opt-in: an extension with no such section
    simply isn't a key in the returned dict, and a key a section
    doesn't set (or sets to something invalid) is left out of that
    extension's own dict too - either way, `settings_for` below falls
    back to the plain top-level default for whatever's missing."""
    overrides = {}
    for themes in (backup_themes, primary_themes):
        for section, values in themes.items():
            if not section.startswith(FILETYPE_SECTION_PREFIX):
                continue
            extension = section[len(FILETYPE_SECTION_PREFIX):].strip()
            if not extension:
                continue
            resolved = overrides.setdefault(extension.lower(), {})
            for key in _FILETYPE_BOOL_KEYS:
                if key in values:
                    parsed = _parse_bool(values[key], None)
                    if parsed is not None:
                        resolved[key] = parsed
            for key in _FILETYPE_INT_KEYS:
                if key in values:
                    parsed = _parse_positive_int(values[key], None)
                    if parsed is not None:
                        resolved[key] = parsed
    return overrides


def _valid_palette_number(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 255 else None


def _resolve_theme_colors(theme_name, primary_themes, backup_themes):
    fallback = DEFAULT_THEMES.get(theme_name, DEFAULT_THEMES["base"])
    resolved = {}
    for key in _COLOR_KINDS:
        value = None
        for themes in (primary_themes, backup_themes):
            candidate = _valid_palette_number(
                themes.get(theme_name, {}).get(key)
            )
            if candidate is not None:
                value = candidate
                break
        resolved[key] = fallback.get(key, 0) if value is None else value
    return resolved


def _is_theme_fully_valid(theme_name, themes):
    colors = themes.get(theme_name)
    if not colors:
        return False
    return all(
        _valid_palette_number(colors.get(key)) is not None
        for key in _COLOR_KINDS
    )


def _default_rc_text():
    lines = [
        "# Mini editor configuration.",
        "# THEME selects which [section] below is active: base, dark or",
        "# light - or a section name you add yourself.",
        f"THEME={DEFAULT_SETTINGS['THEME']}",
        f"SHOW_NUMBER_LINE={DEFAULT_SETTINGS['SHOW_NUMBER_LINE']}",
        f"SHOW_LINE_INDICATOR={DEFAULT_SETTINGS['SHOW_LINE_INDICATOR']}",
        "# MAX_COLS draws a ruler at that column (flake8's own default,",
        "# 79, by default here too) and flags lines that cross it;",
        "# MAX_COLS_ENABLED turns the ruler and the flagging off",
        "# entirely when set to False.",
        f"MAX_COLS_ENABLED={DEFAULT_SETTINGS['MAX_COLS_ENABLED']}",
        f"MAX_COLS={DEFAULT_SETTINGS['MAX_COLS']}",
        "# INDENT_WITH_TABS picks what auto-indent and Tab insert: a",
        "# tab character (True) or TAB_SIZE spaces (False).",
        f"INDENT_WITH_TABS={DEFAULT_SETTINGS['INDENT_WITH_TABS']}",
        f"TAB_SIZE={DEFAULT_SETTINGS['TAB_SIZE']}",
        "# MOUSE_ENABLED turns on click-to-place-cursor, click-and-drag",
        "# to select, the scroll wheel, and clicking in the worktree",
        "# panel - off by default because enabling it stops the",
        "# terminal's own click-drag text selection from working while",
        "# Mini has focus (most terminals let you hold Shift while",
        "# dragging to get that back on demand).",
        f"MOUSE_ENABLED={DEFAULT_SETTINGS['MOUSE_ENABLED']}",
        "",
        "# Each color below is an xterm 256-color palette number (0-255).",
        "# https://www.ditig.com/256-colors-cheat-sheet is a handy chart.",
    ]
    for theme_name in ("base", "dark", "light"):
        lines.append("")
        lines.append(f"[{theme_name}]")
        for key, value in DEFAULT_THEMES[theme_name].items():
            lines.append(f"{key}={value}")
    lines.append("")
    lines.append(
        "# [filetype:.ext] overrides MAX_COLS_ENABLED/MAX_COLS/"
        "INDENT_WITH_TABS/TAB_SIZE"
    )
    lines.append(
        "# for files with that extension - only the keys it sets; add "
        "or remove"
    )
    lines.append(
        "# sections freely, for any extension you want. Example "
        "(disabled - remove"
    )
    lines.append("# the leading # on each line to actually use it):")
    lines.append("# [filetype:.js]")
    lines.append("# MAX_COLS=100")
    lines.append("# INDENT_WITH_TABS=False")
    lines.append("# TAB_SIZE=2")
    lines.append("")
    return "\n".join(lines)


def _refresh_backup_if_valid(settings, primary_settings, primary_themes):
    fully_valid = (
        "THEME" in primary_settings
        and "SHOW_NUMBER_LINE" in primary_settings
        and "SHOW_LINE_INDICATOR" in primary_settings
        and "MAX_COLS_ENABLED" in primary_settings
        and "MAX_COLS" in primary_settings
        and "INDENT_WITH_TABS" in primary_settings
        and "TAB_SIZE" in primary_settings
        and "MOUSE_ENABLED" in primary_settings
        and _is_theme_fully_valid(settings["THEME"], primary_themes)
    )
    if not fully_valid:
        return
    try:
        with open(RC_PATH, "r", encoding="utf-8") as source:
            content = source.read()
        with open(BACKUP_PATH, "w", encoding="utf-8") as backup_file:
            backup_file.write(content)
    except OSError:
        pass


def _migrate_rc_file(path):
    """Adds any settings/color keys this version of Mini knows about
    but `path` doesn't have yet, appending each - with its default
    value - to whatever's already there. Every existing value,
    comment, and custom section is left exactly as it was; only
    genuinely missing keys are added, so an update never quietly
    drops something the user could see and tweak into an invisible
    in-code fallback. Returns the keys that were actually added (as
    "KEY" for a top-level setting, "section.KEY" for a color); doesn't
    touch the file at all when there was nothing missing."""
    try:
        with open(path, "r", encoding="utf-8") as file:
            lines = file.readlines()
    except OSError:
        return []

    section_starts = []
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section_starts.append((stripped[1:-1].strip(), index))
    first_section_line = (
        section_starts[0][1] if section_starts else len(lines)
    )

    def existing_keys(start, end):
        keys = set()
        for raw_line in lines[start:end]:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(("#", "[")):
                continue
            key = stripped.split("=", 1)[0].strip()
            if key:
                keys.add(key)
        return keys

    added = []

    # Section color keys first, working from the last section to the
    # first, so each section's own insertion point (its end) never
    # has to account for edits made to a section that comes after it.
    for position in range(len(section_starts) - 1, -1, -1):
        name, header_index = section_starts[position]
        if name not in DEFAULT_THEMES:
            continue  # a custom section has no known default to add
        end = (
            section_starts[position + 1][1]
            if position + 1 < len(section_starts) else len(lines)
        )
        section_keys = existing_keys(header_index + 1, end)
        for key in _COLOR_KINDS:
            if key in section_keys:
                continue
            lines.insert(end, f"{key}={DEFAULT_THEMES[name][key]}\n")
            end += 1
            added.append(f"{name}.{key}")

    # Top-level settings last, right before the first section header
    # (or at the end of the file if there are no sections at all) -
    # nothing before that point has been touched by the loop above.
    top_level_keys = existing_keys(0, first_section_line)
    for key in DEFAULT_SETTINGS:
        if key in top_level_keys:
            continue
        lines.insert(first_section_line, f"{key}={DEFAULT_SETTINGS[key]}\n")
        first_section_line += 1
        added.append(key)

    if added:
        with open(path, "w", encoding="utf-8") as file:
            file.writelines(lines)
    return added


def _load():
    primary_settings, primary_themes = _parse_rc(RC_PATH)
    backup_settings, backup_themes = _parse_rc(BACKUP_PATH)

    settings = _resolve_settings(primary_settings, backup_settings)
    known_themes = set(DEFAULT_THEMES) | set(primary_themes) | set(
        backup_themes
    )
    if settings["THEME"] not in known_themes:
        settings["THEME"] = "base"

    colors = _resolve_theme_colors(
        settings["THEME"], primary_themes, backup_themes
    )
    filetype_overrides = _resolve_filetype_overrides(
        primary_themes, backup_themes
    )
    _refresh_backup_if_valid(settings, primary_settings, primary_themes)
    return settings, colors, filetype_overrides


def settings_for(file_name):
    """The effective {MAX_COLS_ENABLED, MAX_COLS, INDENT_WITH_TABS,
    TAB_SIZE} for `file_name`, honoring its extension's own
    `[filetype:.ext]` section (~/.minirc) for whichever of those keys
    it actually sets - any key it doesn't set, an extension with no
    section at all, or no file name at all (an unsaved buffer), falls
    back to the plain top-level default (the same values the flat
    MAX_COLS/INDENT_WITH_TABS/... module attributes below expose)."""
    base = {
        "MAX_COLS_ENABLED": MAX_COLS_ENABLED, "MAX_COLS": MAX_COLS,
        "INDENT_WITH_TABS": INDENT_WITH_TABS, "TAB_SIZE": TAB_SIZE,
    }
    if not file_name:
        return base
    extension = os.path.splitext(file_name)[1].lower()
    override = _filetype_overrides.get(extension)
    if not override:
        return base
    return {**base, **override}


def _ansi(key, value):
    prefix = "48" if _COLOR_KINDS[key] == "bg" else "38"
    return f"\x1b[{prefix};5;{value}m"


_settings, _colors, _filetype_overrides = _load()

SHOW_NUMBER_LINE = _settings["SHOW_NUMBER_LINE"]
SHOW_LINE_INDICATOR = _settings["SHOW_LINE_INDICATOR"]
MAX_COLS_ENABLED = _settings["MAX_COLS_ENABLED"]
MAX_COLS = _settings["MAX_COLS"]
INDENT_WITH_TABS = _settings["INDENT_WITH_TABS"]
TAB_SIZE = _settings["TAB_SIZE"]
MOUSE_ENABLED = _settings["MOUSE_ENABLED"]

BACKGROUND_COLOR = _ansi("BACKGROUND_COLOR", _colors["BACKGROUND_COLOR"])
TEXT_COLOR = _ansi("TEXT_COLOR", _colors["TEXT_COLOR"])
BASE_STYLE = BACKGROUND_COLOR + TEXT_COLOR
COLOR_RESET = TEXT_COLOR

LINE_NUMBER_COLOR = _ansi("LINE_NUMBER_COLOR", _colors["LINE_NUMBER_COLOR"])
CURRENT_LINE_INDICATOR_COLOR = _ansi(
    "CURRENT_LINE_INDICATOR_COLOR", _colors["CURRENT_LINE_INDICATOR_COLOR"]
)

BRACKET_MATCH_START = _ansi(
    "BRACKET_MATCH_COLOR", _colors["BRACKET_MATCH_COLOR"]
)
BRACKET_MATCH_END = BACKGROUND_COLOR

KEYWORD_COLOR = _ansi("KEYWORD_COLOR", _colors["KEYWORD_COLOR"])
DUNDER_COLOR = _ansi("DUNDER_COLOR", _colors["DUNDER_COLOR"])
TYPE_COLOR = _ansi("TYPE_COLOR", _colors["TYPE_COLOR"])
FUNCTION_COLOR = _ansi("FUNCTION_COLOR", _colors["FUNCTION_COLOR"])

SUGGESTION_COLOR = _ansi("SUGGESTION_COLOR", _colors["SUGGESTION_COLOR"])
SUGGESTION_RESET = BASE_STYLE

SELECTION_START = "\x1b[7m"
SELECTION_END = "\x1b[27m"

ACTIVE_TAB_COLOR = _ansi("ACTIVE_TAB_COLOR", _colors["ACTIVE_TAB_COLOR"])
INACTIVE_TAB_COLOR = _ansi(
    "INACTIVE_TAB_COLOR", _colors["INACTIVE_TAB_COLOR"]
)

RULER_COLOR = _ansi("RULER_COLOR", _colors["RULER_COLOR"])
LINE_LENGTH_ERROR_COLOR = _ansi(
    "LINE_LENGTH_ERROR_COLOR", _colors["LINE_LENGTH_ERROR_COLOR"]
)
STRING_COLOR = _ansi("STRING_COLOR", _colors["STRING_COLOR"])
DECLARATION_COLOR = _ansi(
    "DECLARATION_COLOR", _colors["DECLARATION_COLOR"]
)
COMMENT_COLOR = _ansi("COMMENT_COLOR", _colors["COMMENT_COLOR"])


if __name__ == "__main__":
    # Used by install.sh: bare `python3 theme.py` seeds a fresh
    # ~/.minirc (settings + base/dark/light). `python3 theme.py
    # --migrate <path>` instead adds any keys this version knows
    # about that <path> doesn't have yet, for an existing ~/.minirc
    # being carried through an update.
    if len(sys.argv) >= 3 and sys.argv[1] == "--migrate":
        added_keys = _migrate_rc_file(sys.argv[2])
        if added_keys:
            print(
                "Added new setting(s) to your ~/.minirc: "
                + ", ".join(added_keys)
            )
    else:
        print(_default_rc_text())
