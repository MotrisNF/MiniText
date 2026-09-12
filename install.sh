#!/usr/bin/env bash
set -euo pipefail

MARK_BEGIN="# >>> mini PATH >>>"
MARK_END="# <<< mini PATH <<<"

rc_files() {
  for f in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
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

sources="main.py text_editor.py theme.py"

for source in $sources; do
  if [ ! -f "$srcdir/$source" ]; then
    echo "$source not found next to install.sh. Nothing to install."
    exit 1
  fi
done

mkdir -p "$libdir" "$bindir"
for source in $sources; do
  install -m 0644 "$srcdir/$source" "$libdir/$source"
done
echo "  Installed sources at $libdir"

wrapper="$(mktemp)"
cat > "$wrapper" <<EOF
#!/usr/bin/env bash
exec python3 "$libdir/main.py" "\$@"
EOF
install -m 0755 "$wrapper" "$bindir/mini"
rm -f "$wrapper"
echo "  Installed at $bindir/mini"

if [ ! -e "$HOME/.minirc" ]; then
  python3 "$libdir/theme.py" > "$HOME/.minirc"
  cp "$HOME/.minirc" "$HOME/.minirc.bak"
  echo "  Created $HOME/.minirc (base/dark/light themes, edit freely)"
elif [ ! -e "$HOME/.minirc.bak" ]; then
  cp "$HOME/.minirc" "$HOME/.minirc.bak"
  echo "  Created $HOME/.minirc.bak from your existing $HOME/.minirc"
fi

add_to_path "$bindir"
echo "Done. Run: mini [file]"
