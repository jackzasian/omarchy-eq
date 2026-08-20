#!/usr/bin/env bash
# Install omarchy-eq for the current user (no root required).
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v pactl    >/dev/null || { echo "pipewire-pulse (pactl) is required" >&2; exit 1; }
command -v pw-play  >/dev/null || { echo "pipewire (pw-play) is required" >&2; exit 1; }
command -v python3  >/dev/null || { echo "python3 is required" >&2; exit 1; }

install -d "$PREFIX/bin" "$PREFIX/share/omarchy-eq/lib"
install -m 0644 "$SRC"/lib/* "$PREFIX/share/omarchy-eq/lib/"
sed "s#^LIB=\"\$ROOT/lib\"#LIB=\"$PREFIX/share/omarchy-eq/lib\"#" \
    "$SRC/bin/omarchy-eq" > "$PREFIX/bin/omarchy-eq"
chmod 0755 "$PREFIX/bin/omarchy-eq"

echo "installed: $PREFIX/bin/omarchy-eq"
case ":$PATH:" in
  *":$PREFIX/bin:"*) ;;
  *) echo "note: $PREFIX/bin is not on your PATH" ;;
esac
echo
echo "next:  omarchy-eq measure && omarchy-eq generate && omarchy-eq apply"
