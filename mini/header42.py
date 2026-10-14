"""The 42-school header block `:header` inserts, and the login/campus
it needs, stored in `~/.mini42`.

That's deliberately its own file rather than a couple of keys in
`~/.minirc` (theme.py): it's an identity, not a setting, so it has no
sensible default to fall back to, nothing to migrate when a new key
appears, and a reason to be removable on its own - which `:clearuser`
does by just deleting it.

Every line of the block below is exactly 80 columns wide, which is the
whole point of it, so E501 is off for this file specifically rather
than per-line - every other check still applies.
"""

# flake8: noqa: E501

import os

CONFIG_PATH = os.path.expanduser("~/.mini42")


def save_config(user, campus):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(user + "\n")
        f.write(campus + "\n")


def load_config():
    """The saved (login, campus), or (None, None) if there's no
    config yet. A file that exists but is missing either line (hand
    edited, or truncated) reports None for that one, so `build_header`
    treats it as unconfigured instead of building a header with
    "None" in the email address."""
    if not os.path.exists(CONFIG_PATH):
        return None, None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()[0:2]
        return (
            lines[0] if len(lines) > 0 else None,
            lines[1] if len(lines) > 1 else None,
        )


def clear_config():
    if os.path.exists(CONFIG_PATH):
        os.remove(CONFIG_PATH)


def build_header(file_name):
    """The block's 11 lines for `file_name`, or None if there's no
    saved login/campus to build it from - `:header`'s cue to point at
    `:configuser` and leave the buffer alone."""
    user, campus = load_config()
    if user is None or campus is None:
        return None
    by: str = f"By: {user} <{user}@student.42{campus.lower()}.com>"
    return [
        "/* ************************************************************************** */",
        "/*                                                                            */",
        "/*                                                        :::      ::::::::   */",
        f"/*   {file_name.ljust(51)}:+:      :+:    :+:   */",
        "/*                                                    +:+ +:+         +:+     */",
        f"/*   {by.ljust(47)[:47]}+#+  +:+       +#+        */",
        "/*                                                +#+#+#+#+#+   +#+           */",
        f"/*   Created: 2026/10/03 12:54:32 by {user.ljust(8)}          #+#    #+#             */",
        f"/*   Updated: 2026/10/03 13:58:56 by {user.ljust(8)}         ###   ########.fr       */",
        "/*                                                                            */",
        "/* ************************************************************************** */",
    ]
