#!/usr/bin/env bash
# Undo plugin/install.sh. Leaves omarchy-eq itself, its measurements and its
# profiles alone -- this removes the Omarchy wiring, not the tool.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINDIR="$HOME/.local/bin"
MENU="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/extensions/omarchy-menu.jsonc"
MARKER="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-eq/plugin.wired"

for f in "$HERE"/bin/*; do
  dest="$BINDIR/$(basename "$f")"
  # Only remove a shim that is still ours, byte for byte. Anything the user has
  # edited is theirs now.
  if [[ -f $dest ]] && cmp -s "$f" "$dest"; then
    rm -f "$dest"; echo "removed: $dest"
  elif [[ -f $dest ]]; then
    echo "kept (locally modified): $dest"
  fi
done

rm -f "$MARKER"

if [[ -f $MENU ]] && cmp -s "$HERE/menu/omarchy-eq.jsonc" "$MENU"; then
  rm -f "$MENU"; echo "removed: $MENU"
elif [[ -f $MENU ]] && grep -q '"eq\.' "$MENU"; then
  echo "note: $MENU has EQ entries mixed with your own -- remove the \"eq.*\" keys by hand."
fi

echo "done. 'omarchy-eq reset' removes the EQ itself, if that is what you wanted."
