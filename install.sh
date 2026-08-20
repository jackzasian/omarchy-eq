#!/usr/bin/env bash
# Install omarchy-eq for the current user (no root required).
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WITH_OMARCHY=0

while (( $# )); do
  case "$1" in
    --omarchy) WITH_OMARCHY=1 ;;
    -h|--help)
      echo "usage: ./install.sh [--omarchy]"
      echo "  --omarchy   also install the Omarchy menu shim and print menu/hotkey setup"
      exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

for c in pactl pw-play pw-record python3; do
  command -v "$c" >/dev/null || { echo "$c is required" >&2; exit 1; }
done

install -d "$PREFIX/bin" "$PREFIX/share/omarchy-eq/lib"
# Only ship the library; tests and fixtures stay in the source tree.
install -m 0644 "$SRC"/lib/*.py "$SRC"/lib/*.tmpl "$PREFIX/share/omarchy-eq/lib/"
sed "s#^LIB=\"\$ROOT/lib\"#LIB=\"$PREFIX/share/omarchy-eq/lib\"#" \
    "$SRC/bin/omarchy-eq" > "$PREFIX/bin/omarchy-eq"
chmod 0755 "$PREFIX/bin/omarchy-eq"
echo "installed: $PREFIX/bin/omarchy-eq"

if (( WITH_OMARCHY )); then
  install -m 0755 "$SRC/omarchy/omarchy-eq-term" "$PREFIX/bin/omarchy-eq-term"
  echo "installed: $PREFIX/bin/omarchy-eq-term"
  if [[ -e $PREFIX/bin/omarchy-eq-tui ]]; then
    echo "note: $PREFIX/bin/omarchy-eq-tui is the old name for this shim."
    echo "      'omarchy-eq tui' is now the interactive UI. Remove the old file"
    echo "      once your menu no longer references it."
  fi

  MENU="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/extensions/omarchy-menu.jsonc"
  # Omarchy reads exactly one menu file (shell/plugins/menu/Menu.qml), so there
  # is no drop-in directory to install into. Never rewrite a user's menu.
  if [[ ! -e $MENU ]]; then
    install -d "$(dirname "$MENU")"
    install -m 0644 "$SRC/omarchy/omarchy-menu.jsonc" "$MENU"
    echo "installed: $MENU"
  elif grep -q 'omarchy-eq' "$MENU"; then
    echo "note: $MENU already has omarchy-eq entries."
    echo "      If they came from v1, re-copy them from $SRC/omarchy/omarchy-menu.jsonc --"
    echo "      the 'when' guards changed when state moved to XDG_STATE_HOME."
  else
    echo "next: merge $SRC/omarchy/omarchy-menu.jsonc into"
    echo "      $MENU   (it hot-reloads on save)"
  fi
  echo "next: add $SRC/omarchy/bindings.lua.snippet to ~/.config/hypr/bindings.lua"
fi

case ":$PATH:" in
  *":$PREFIX/bin:"*) ;;
  *) echo "note: $PREFIX/bin is not on your PATH" ;;
esac
echo
echo "next:  omarchy-eq measure && omarchy-eq measure --again \\"
echo "         && omarchy-eq generate && omarchy-eq apply"
