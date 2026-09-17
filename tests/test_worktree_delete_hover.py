"""Covers bugs_conocidos.md: 'En el modo mouse enabled, los archivos
deben tener un aspa a su derecha al pasar el raton por encima, que al
hacer click sobre ella preguntara si se desea eliminar'."""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import theme  # noqa: E402
from worktree import (  # noqa: E402
    WorktreePanelMixin, WORKTREE_WIDTH, _DELETE_HOVER_COLOR,
)


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


class FakePanel(WorktreePanelMixin):
    def __init__(self, root):
        self.worktree_root = root
        self.worktree_root_collapsed = False
        self.worktree_show_hidden = True
        self.worktree_expanded = set()
        self.worktree_cursor = 0
        self.worktree_scroll = 0
        self._worktree_entries_cache = None
        self._hovered_worktree_delete = None
        self._hovered_worktree_rename = None
        self._hovered_worktree_row = None
        self.worktree_selected_entries = set()
        self._hovered_worktree_button = None
        self._worktree_drag_origin = None


def test_hit_test_only_matches_last_two_columns_of_a_real_entry_row():
    theme.MOUSE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        # entries[0] is the root itself (never hit-testable - see
        # _worktree_icon_hit_test); entries[1] is a.txt.
        assert fake._worktree_delete_hit_test(1, WORKTREE_WIDTH - 1) == 1
        assert fake._worktree_delete_hit_test(1, WORKTREE_WIDTH - 2) == 1
        assert fake._worktree_delete_hit_test(1, WORKTREE_WIDTH - 3) is None
        assert fake._worktree_delete_hit_test(0, WORKTREE_WIDTH - 1) is None


def test_hit_test_disabled_without_mouse():
    theme.MOUSE_ENABLED = False
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        assert fake._worktree_delete_hit_test(1, WORKTREE_WIDTH - 1) is None
    theme.MOUSE_ENABLED = True


def test_delete_cross_only_shown_on_the_hovered_row():
    theme.MOUSE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        b_path = os.path.join(tmp, "b.txt")
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        # The cross reveals for the whole row (any column), tracked by
        # path (_hovered_worktree_row) - separate from the narrow
        # click hit-test (_hovered_worktree_delete, unset here).
        fake._hovered_worktree_row = b_path
        lines = [_strip_ansi(line) for line in fake._worktree_body_lines(10)]
        assert all(len(line) == WORKTREE_WIDTH for line in lines)
        assert "×" not in lines[1]
        assert "×" in lines[2]


def test_hover_reveal_is_not_limited_to_the_edge_columns():
    """Covers the actual bug report: the cross used to only reveal
    itself once the mouse was already exactly where it would be
    drawn. Hovering the row's own first column (far from the "×"
    zone) must be enough to reveal it - only clicking still needs the
    narrow zone (see test_hit_test_only_matches_last_two_columns...).
    """
    theme.MOUSE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        a_path = os.path.join(tmp, "a.txt")
        open(a_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        entry = fake._worktree_entry_at_row(1)
        assert entry == (a_path, False)
        fake._hovered_worktree_row = entry[0]
        lines = [_strip_ansi(line) for line in fake._worktree_body_lines(10)]
        assert "×" in lines[1]


def test_hovered_row_gets_a_reverse_video_highlight():
    """Covers bugs_conocidos.md: 'es necesario que se resalten
    minimamente para dar feedback al usuario' - hovering a file (mouse
    mode) now paints its row in reverse video, not just the delete ×.
    """
    theme.MOUSE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
        b_path = os.path.join(tmp, "b.txt")
        open(b_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._hovered_worktree_row = b_path
        lines = fake._worktree_body_lines(10)
        assert lines[2].startswith("\x1b[7m")
        assert "\x1b[7m" not in lines[1]  # a.txt (the cursor) is untouched


def test_icons_only_take_their_own_color_precisely_hovered():
    """Covers the follow-up request: the ✎/× icons used to always show
    their full rename/delete color as soon as the row was hovered at
    all - they should only actually turn that color when the mouse is
    precisely over that one icon's own narrow zone (see
    _worktree_rename_hit_test/_worktree_delete_hit_test), blending
    into the row's own color otherwise, the same way `_tab_bar_line`'s
    own × already behaves."""
    theme.MOUSE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        a_path = os.path.join(tmp, "a.txt")
        open(a_path, "w", encoding="utf-8").close()
        fake = FakePanel(tmp)
        fake._hovered_worktree_row = a_path

        lines = fake._worktree_body_lines(10)
        assert theme.CURRENT_LINE_INDICATOR_COLOR not in lines[1]
        assert _DELETE_HOVER_COLOR not in lines[1]

        fake._hovered_worktree_rename = 1
        lines = fake._worktree_body_lines(10)
        assert theme.CURRENT_LINE_INDICATOR_COLOR in lines[1]
        assert _DELETE_HOVER_COLOR not in lines[1]

        fake._hovered_worktree_rename = None
        fake._hovered_worktree_delete = 1
        lines = fake._worktree_body_lines(10)
        assert theme.CURRENT_LINE_INDICATOR_COLOR not in lines[1]
        assert _DELETE_HOVER_COLOR in lines[1]


TESTS = [
    test_hit_test_only_matches_last_two_columns_of_a_real_entry_row,
    test_hit_test_disabled_without_mouse,
    test_delete_cross_only_shown_on_the_hovered_row,
    test_hover_reveal_is_not_limited_to_the_edge_columns,
    test_hovered_row_gets_a_reverse_video_highlight,
    test_icons_only_take_their_own_color_precisely_hovered,
]
