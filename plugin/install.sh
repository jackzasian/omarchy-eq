#!/usr/bin/env bash
# Wire the Speaker EQ plugin into Omarchy.
#
# The plugin itself is just a folder Omarchy copies into
# ~/.config/omarchy/plugins/. What needs wiring is everything that lives in
# files this plugin does not own:
#
#   the menu     Omarchy reads exactly one user menu file, so entries have to be
#                merged into it rather than dropped alongside it
#   the shims    the menu's actions call omarchy-eq-profile and friends, which
#                have to be somewhere on PATH
#
# Neither is ever overwritten. A user's menu file is theirs; if merging is not
# obviously safe this prints what to add and stops.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINDIR="$HOME/.local/bin"
MENU="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/extensions/omarchy-menu.jsonc"
MARKER="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy-eq/plugin.wired"
WIRE_ONLY=0

[[ ${1:-} == --wire-only ]] && WIRE_ONLY=1

say() { (( WIRE_ONLY )) || printf '%s\n' "$*"; }

# --wire-only is what the QML service runs at every shell start. It re-asserts
# wiring that already exists and does nothing at all otherwise -- a user who has
# never run this installer by hand never gets their menu file touched.
if (( WIRE_ONLY )) && [[ ! -f $MARKER ]]; then
  exit 0
fi

command -v omarchy-eq >/dev/null || {
  say "omarchy-eq is not on PATH."
  say "Install it first:  git clone https://github.com/jackzasian/omarchy-eq && cd omarchy-eq && ./install.sh"
  exit 1
}

mkdir -p "$BINDIR"
changed=0
for f in "$HERE"/bin/*; do
  dest="$BINDIR/$(basename "$f")"
  if [[ ! -f $dest ]] || ! cmp -s "$f" "$dest"; then
    install -m 0755 "$f" "$dest"; changed=1
    say "installed: $dest"
  fi
done

# The terminal shim ships with omarchy-eq proper, not with the plugin. Without
# it the rows that need a TTY (measure, fetch, the TUI) have nothing to open.
if ! command -v omarchy-eq-term >/dev/null; then
  say "note: omarchy-eq-term is missing -- run omarchy-eq's own ./install.sh --omarchy"
  say "      so the terminal rows (Re-measure, Fetch Preset, Curve) can open a TTY."
fi

if [[ ! -e $MENU ]]; then
  mkdir -p "$(dirname "$MENU")"
  install -m 0644 "$HERE/menu/omarchy-eq.jsonc" "$MENU"
  say "installed: $MENU"
  changed=1
elif grep -q '"eq\.' "$MENU" 2>/dev/null; then
  say "note: $MENU already has EQ entries; leaving it alone."
  say "      To take the v3 rows, re-copy them from $HERE/menu/omarchy-eq.jsonc"
else
  say ""
  say "Your menu file already exists, so it has not been modified. Merge the"
  say "entries from this file into it (it hot-reloads on save):"
  say "    $HERE/menu/omarchy-eq.jsonc"
  say "  ->  $MENU"
fi

mkdir -p "$(dirname "$MARKER")"
: > "$MARKER"

if (( WIRE_ONLY )); then
  (( changed )) && echo "re-wired $changed item(s)"
  exit 0
fi

cat <<TXT

Speaker EQ is wired.

  Super+Space  ->  Speaker EQ         the menu entries
  omarchy-eq-profile                  pick a profile for the current output

Optional hotkeys -- check the keys are free first with
'omarchy menu keybindings --print', then add to ~/.config/hypr/bindings.conf:
    source = $HERE/hypr/bindings.conf

Remove everything again with:  $HERE/uninstall.sh
TXT
