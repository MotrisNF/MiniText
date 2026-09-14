#!/usr/bin/env bash
set -euo pipefail

MARK_BEGIN="# >>> mini PATH >>>"
MARK_END="# <<< mini PATH <<<"

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
  git -C "$libdir/src" pull --ff-only --quiet
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

wrapper="$(mktemp)"
cat > "$wrapper" <<EOF
#!/usr/bin/env bash
exec python3 "$libdir/src/main.py" "\$@"
EOF
install -m 0755 "$wrapper" "$bindir/mini"
rm -f "$wrapper"
echo "  Installed at $bindir/mini"

if [ ! -e "$HOME/.minirc" ]; then
  python3 "$libdir/src/theme.py" > "$HOME/.minirc"
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
  migration_report="$(python3 "$libdir/src/theme.py" --migrate "$HOME/.minirc")"
  if [ -n "$migration_report" ]; then
    echo "  $migration_report"
  fi
fi

add_to_path "$bindir"
echo "Done. Run: mini [file]"
