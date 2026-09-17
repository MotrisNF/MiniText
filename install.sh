#!/usr/bin/env bash
set -euo pipefail

MARK_BEGIN="# >>> mini PATH >>>"
MARK_END="# <<< mini PATH <<<"
# jedi backs Python completion (autocomplete.py's _get_jedi); flake8
# and mypy back :lint as a fallback for a project that has neither of
# its own (run_panel.py's _lint_environment) - never used to run the
# file being edited itself, which always goes through its own
# resolved interpreter (venv_detect.py) exactly as before.
MINI_VENV_PACKAGES="jedi>=0.19,<0.21 flake8 mypy"

# Mini's own private virtualenv, used only for the optional extras
# above. Idempotent: an already-working venv (directory present,
# every package importable) is left alone - no network call, no
# reinstall - so a routine `mini --update` (which re-runs this whole
# script) stays fast. A broken or missing one is (re)created/
# reinstalled; if that fails outright (no network, no python3-venv
# package, ...), Mini falls back to running on the system python3,
# and :lint falls back to whatever's on the system PATH - every one
# of these is an enhancement, never a hard requirement.
ensure_mini_venv() {
  local venv_dir="$1" venv_python="$1/bin/python3"
  if [ ! -x "$venv_python" ]; then
    if python3 -m venv "$venv_dir" >/dev/null 2>&1; then
      echo "  Created Mini's own virtualenv at $venv_dir"
    else
      echo "  Could not create a virtualenv (python3-venv missing?)" \
        "- continuing on the system python3, without jedi/lint extras."
      return
    fi
  fi
  if ! "$venv_python" -c "import jedi, flake8, mypy" >/dev/null 2>&1; then
    if "$venv_python" -m pip install --quiet \
      --disable-pip-version-check $MINI_VENV_PACKAGES >/dev/null 2>&1
    then
      echo "  Installed jedi/flake8/mypy (completion + :lint fallback)" \
        "into Mini's own virtualenv"
    else
      echo "  Could not install jedi/flake8/mypy (no network?)" \
        "- Mini will still work, just without those extras."
    fi
  fi
}

rc_files() {
  for f in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" \
    "$HOME/.hellishrc"; do
    [ -e "$f" ] && printf '%s\n' "$f"
  done
}

add_to_path() {
  local bindir="$1"
  local line="case \":\$PATH:\" in *\":$bindir:\"*) ;; *) export PATH=\"$bindir:\$PATH\" ;; esac"
  local present_now=0 changed=0
  case ":$PATH:" in *":$bindir:"*) present_now=1 ;; esac
  while IFS= read -r rc; do
    if grep -qF "$MARK_BEGIN" "$rc"; then continue; fi
    printf '\n%s\n%s\n%s\n' "$MARK_BEGIN" "$line" "$MARK_END" >> "$rc"
    changed=1
    echo "  PATH added to $rc"
  done < <(rc_files)
  if [ "$present_now" -eq 0 ] && [ "$changed" -eq 1 ]; then
    echo "  Open a new terminal (or 'source' your rc file) for 'mini' to be available."
  fi
}

remove_from_path() {
  local rc tmp
  while IFS= read -r rc; do
    grep -qF "$MARK_BEGIN" "$rc" || continue
    tmp="$(mktemp)"
    awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
      $0 == b { skip = 1; next }
      $0 == e { skip = 0; next }
      skip != 1 { print }
    ' "$rc" > "$tmp"
    # collapse trailing blank lines the removal may have left behind
    sed -e :a -e '/^\n*$/{$d;N;ba}' "$tmp" > "$rc"
    rm -f "$tmp"
    echo "  PATH entry removed from $rc"
  done < <(rc_files)
}

if [ "${1:-}" = "--uninstall" ]; then
  libdir="${2:?usage: install.sh --uninstall <libdir> <bindir>}"
  bindir="${3:?usage: install.sh --uninstall <libdir> <bindir>}"
  if [ -e "$bindir/mini" ]; then rm -f "$bindir/mini"; echo "  Removed $bindir/mini"; fi
  if [ -d "$libdir" ]; then rm -rf "$libdir"; echo "  Removed $libdir"; fi
  if [ -e "$HOME/.minirc" ]; then rm -f "$HOME/.minirc"; echo "  Removed $HOME/.minirc"; fi
  if [ -e "$HOME/.minirc.bak" ]; then rm -f "$HOME/.minirc.bak"; echo "  Removed $HOME/.minirc.bak"; fi
  remove_from_path
  echo "Uninstalled."
  echo "  If this shell still finds an old 'mini', run 'hash -r' (or open a new terminal)."
  exit 0
fi

libdir="${1:?usage: install.sh <libdir> <bindir>}"
bindir="${2:?usage: install.sh <libdir> <bindir>}"

srcdir="$(cd "$(dirname "$0")" && pwd)"

if ! git -C "$srcdir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "install.sh must be run from inside the Mini git repository."
  exit 1
fi

remote_url="$(git -C "$srcdir" remote get-url origin 2>/dev/null || true)"

mkdir -p "$libdir" "$bindir"

# A leftover from an older, copy-based install (no .git) gets replaced.
if [ -d "$libdir/src" ] && [ ! -d "$libdir/src/.git" ]; then
  rm -rf "$libdir/src"
fi

if [ -d "$libdir/src/.git" ]; then
  if ! git -C "$libdir/src" pull --ff-only --quiet; then
    # A remote history rewrite (a force-push after a mistaken commit,
    # say) leaves a fast-forward pull failing permanently, the same
    # way every single future update would - resync to the remote
    # branch tip instead of requiring a manual uninstall/reinstall to
    # recover (mirrors updater.py's own _recover_non_fast_forward, for
    # `mini --update`).
    branch="$(git -C "$libdir/src" rev-parse --abbrev-ref HEAD)"
    git -C "$libdir/src" fetch --quiet origin "$branch"
    git -C "$libdir/src" reset --hard --quiet "origin/$branch"
  fi
  echo "  Updated existing install at $libdir/src"
else
  git clone --quiet "$srcdir" "$libdir/src"
  if [ -n "$remote_url" ]; then
    git -C "$libdir/src" remote set-url origin "$remote_url"
  fi
  echo "  Installed sources at $libdir/src"
fi

cat > "$libdir/env" <<EOF
LIBDIR=$libdir
BINDIR=$bindir
EOF

venv_dir="$libdir/venv"
ensure_mini_venv "$venv_dir"
if [ -x "$venv_dir/bin/python3" ]; then
  python_for_wrapper="$venv_dir/bin/python3"
else
  python_for_wrapper="python3"
fi

wrapper="$(mktemp)"
cat > "$wrapper" <<EOF
#!/usr/bin/env bash
exec "$python_for_wrapper" "$libdir/src/mini/main.py" "\$@"
EOF
install -m 0755 "$wrapper" "$bindir/mini"
rm -f "$wrapper"
echo "  Installed at $bindir/mini"

if [ ! -e "$HOME/.minirc" ]; then
  python3 "$libdir/src/mini/theme.py" > "$HOME/.minirc"
  cp "$HOME/.minirc" "$HOME/.minirc.bak"
  echo "  Created $HOME/.minirc (base/dark/light themes, edit freely)"
else
  if [ ! -e "$HOME/.minirc.bak" ]; then
    cp "$HOME/.minirc" "$HOME/.minirc.bak"
    echo "  Created $HOME/.minirc.bak from your existing $HOME/.minirc"
  fi
  # Carries any setting/color key a newer Mini added over the years
  # into an existing ~/.minirc, so it doesn't just silently fall back
  # to an invisible in-code default forever.
  migration_report="$(python3 "$libdir/src/mini/theme.py" --migrate "$HOME/.minirc")"
  if [ -n "$migration_report" ]; then
    echo "  $migration_report"
  fi
fi

add_to_path "$bindir"
echo "Done. Run: mini [file]"
