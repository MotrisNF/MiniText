"""Covers bugs_conocidos.md: 'Modo mouse_enable debe de ser True por
defecto ... sin que ese cambio afecte a cambios posteriores que pueda
realizar el usuario'."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import theme  # noqa: E402


def _with_temp_rc(content, test_body):
    tmpdir = tempfile.mkdtemp()
    rc_path = os.path.join(tmpdir, "minirc")
    with open(rc_path, "w", encoding="utf-8") as f:
        f.write(content)
    original_rc, original_backup = theme.RC_PATH, theme.BACKUP_PATH
    theme.RC_PATH, theme.BACKUP_PATH = rc_path, rc_path + ".bak"
    try:
        test_body(rc_path)
    finally:
        theme.RC_PATH, theme.BACKUP_PATH = original_rc, original_backup


def test_fresh_default_rc_has_mouse_enabled_true():
    assert "MOUSE_ENABLED=True" in theme._default_rc_text()


def test_complete_rc_is_untouched_by_migration():
    def body(rc_path):
        added = theme._migrate_rc_file(rc_path)
        assert added == [], added
    _with_temp_rc(theme._default_rc_text(), body)


def test_existing_explicit_false_is_never_overridden():
    def body(rc_path):
        added = theme._migrate_rc_file(rc_path)
        assert added == [], added
        with open(rc_path, encoding="utf-8") as f:
            content = f.read()
        assert "MOUSE_ENABLED=False" in content
        assert "MOUSE_ENABLED=True" not in content
    old_content = theme._default_rc_text().replace(
        "MOUSE_ENABLED=True", "MOUSE_ENABLED=False"
    )
    _with_temp_rc(old_content, body)


def test_truly_missing_key_adopts_new_default():
    def body(rc_path):
        added = theme._migrate_rc_file(rc_path)
        assert added == ["MOUSE_ENABLED"], added
        with open(rc_path, encoding="utf-8") as f:
            content = f.read()
        assert "MOUSE_ENABLED=True" in content
    content_without_key = "\n".join(
        line for line in theme._default_rc_text().splitlines()
        if not line.startswith("MOUSE_ENABLED")
    )
    _with_temp_rc(content_without_key, body)


TESTS = [
    test_fresh_default_rc_has_mouse_enabled_true,
    test_complete_rc_is_untouched_by_migration,
    test_existing_explicit_false_is_never_overridden,
    test_truly_missing_key_adopts_new_default,
]
