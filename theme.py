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

    [base]
    BACKGROUND_COLOR=235
    ...

    [dark]
    ...

    [light]
    ...

THEME picks which [section] is active - it can name any section in the
file, including ones the user adds themselves; sections that aren't
base/dark/light are just as valid. Each color value is an xterm
256-color palette number (0-255); whether a given key is used as a
foreground or a background is fixed (see _COLOR_KINDS below), not
something the user chooses.

~/.minirc.bak is a safety net, not something meant to be hand-edited:
whenever ~/.minirc loads and validates cleanly, it's mirrored into
~/.minirc.bak. If ~/.minirc is later missing a key, has an invalid
value, or fails to parse altogether, the missing pieces are recovered
from ~/.minirc.bak before falling back to the hardcoded defaults below,
so a typo in a hand-edited color never breaks the editor.
"""

import os

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
    "PLACEHOLDER_COLOR": "fg",
    "INACTIVE_TAB_COLOR": "bg",
}

DEFAULT_THEMES = {
    "base": {
        "BACKGROUND_COLOR": 235, "TEXT_COLOR": 252, "LINE_NUMBER_COLOR": 244,
        "CURRENT_LINE_INDICATOR_COLOR": 214, "BRACKET_MATCH_COLOR": 238,
        "KEYWORD_COLOR": 33, "DUNDER_COLOR": 11, "TYPE_COLOR": 2,
        "FUNCTION_COLOR": 5, "SUGGESTION_COLOR": 244, "PLACEHOLDER_COLOR": 244,
        "INACTIVE_TAB_COLOR": 232,
    },
    "dark": {
        "BACKGROUND_COLOR": 233, "TEXT_COLOR": 250, "LINE_NUMBER_COLOR": 240,
        "CURRENT_LINE_INDICATOR_COLOR": 208, "BRACKET_MATCH_COLOR": 236,
        "KEYWORD_COLOR": 39, "DUNDER_COLOR": 221, "TYPE_COLOR": 78,
        "FUNCTION_COLOR": 176, "SUGGESTION_COLOR": 240, "PLACEHOLDER_COLOR": 240,
        "INACTIVE_TAB_COLOR": 236,
    },
    "light": {
        "BACKGROUND_COLOR": 253, "TEXT_COLOR": 235, "LINE_NUMBER_COLOR": 246,
        "CURRENT_LINE_INDICATOR_COLOR": 166, "BRACKET_MATCH_COLOR": 250,
        "KEYWORD_COLOR": 18, "DUNDER_COLOR": 94, "TYPE_COLOR": 22,
        "FUNCTION_COLOR": 90, "SUGGESTION_COLOR": 246, "PLACEHOLDER_COLOR": 246,
        "INACTIVE_TAB_COLOR": 250,
    },
}
DEFAULT_SETTINGS = {
    "THEME": "base", "SHOW_NUMBER_LINE": True, "SHOW_LINE_INDICATOR": True,
}


def _parse_bool(value, fallback):
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    return fallback


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
    for key in ("SHOW_NUMBER_LINE", "SHOW_LINE_INDICATOR"):
        for source in (primary, backup):
            if key in source:
                settings[key] = _parse_bool(source[key], settings[key])
                break
    for source in (primary, backup):
        if source.get("THEME"):
            settings["THEME"] = source["THEME"]
            break
    return settings


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
    return "\n".join(lines)


def _refresh_backup_if_valid(settings, primary_settings, primary_themes):
    fully_valid = (
        "THEME" in primary_settings
        and "SHOW_NUMBER_LINE" in primary_settings
        and "SHOW_LINE_INDICATOR" in primary_settings
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
    _refresh_backup_if_valid(settings, primary_settings, primary_themes)
    return settings, colors


def _ansi(key, value):
    prefix = "48" if _COLOR_KINDS[key] == "bg" else "38"
    return f"\x1b[{prefix};5;{value}m"


_settings, _colors = _load()

SHOW_NUMBER_LINE = _settings["SHOW_NUMBER_LINE"]
SHOW_LINE_INDICATOR = _settings["SHOW_LINE_INDICATOR"]

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

PLACEHOLDER_COLOR = _ansi("PLACEHOLDER_COLOR", _colors["PLACEHOLDER_COLOR"])
PLACEHOLDER_RESET = BASE_STYLE

INACTIVE_TAB_COLOR = _ansi(
    "INACTIVE_TAB_COLOR", _colors["INACTIVE_TAB_COLOR"]
)


if __name__ == "__main__":
    # Used by install.sh to seed a fresh ~/.minirc: `python3 theme.py`
    # prints the default config text (settings + base/dark/light).
    print(_default_rc_text())
