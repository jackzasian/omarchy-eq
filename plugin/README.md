# Speaker EQ — an Omarchy plugin

Menu entries, shims and a hotkey for [omarchy-eq](https://github.com/jackzasian/omarchy-eq):
measured per-device PipeWire EQ, automatic per-output switching, and AutoEq
preset import.

The plugin is the *desktop wiring*. The tool itself is a separate install — the
plugin will tell you if it is missing.

## Install

```bash
omarchy plugin add https://github.com/jackzasian/omarchy-eq.git --enable
~/.config/omarchy/plugins/jackzasian.eq/install.sh
```

The second step is separate on purpose. Omarchy copies a plugin folder into
place, but the menu is a single user-owned file that every extension shares, so
entries have to be *merged* into it rather than dropped alongside it. That is
not something to do behind your back: if you already have a menu file, the
installer prints what to add and changes nothing.

Remove it again with `uninstall.sh`, which also only deletes shims that are
still byte-for-byte ours. Anything you edited stays.

## What the entries do

| Entry | |
|---|---|
| Switch Profile | pick from the profiles this output actually has |
| Cycle Profile | next profile, no prompt (also `Super+Alt+E`) |
| Auto-switch per Output | follow the output device and restore its last profile |
| Fetch Preset (AutoEq) | search ~6300 measured presets for the connected device |
| Import Preset File | ParametricEQ / FixedBandEQ / GraphicEQ `.txt`, or a `.wav` impulse response |
| Clean Mic (RNNoise) | toggle the noise-suppressed capture chain |
| Curve & Profiles | the measured response and each EQ curve, in a TUI |
| Outputs | every sink, and what each one has |
| Re-measure Speakers | two-position measurement, then rebuild (~7 min, audible) |
| Audio Diagnostics | audio state, service state, and a profile health check |
| Remove EQ | delete the profiles and restore raw output |

**Switch Profile is a shim rather than a row per profile**, and that is the one
design decision here worth explaining. Profiles are per-device and open-ended:
`flat` plus whatever was generated, imported or fetched, which for headphones
means keys like `sennheiser_hd_650`. A menu file is static, so four hardcoded
rows stopped being the whole picture the moment presets could be fetched.
`omarchy-eq-profile` asks the tool what exists on the current output and shows
that, with the active one marked.

The rows that only exist in omarchy-eq v3 are gated on `omarchy-eq help`
mentioning the subcommand, not on a version string — on an older install they
quietly do not appear, instead of appearing and failing.

## Hotkeys

Optional, and not installed automatically — check the keys are free first with
`omarchy menu keybindings --print`, then add to `~/.config/hypr/bindings.conf`:

```
source = ~/.config/omarchy/plugins/jackzasian.eq/hypr/bindings.conf
```

That binds `Super+Alt+E` to cycle and `Super+Alt+Shift+E` to the picker.

## Requirements

`omarchy-eq` on PATH, plus `omarchy-eq-term` from its own `./install.sh
--omarchy` for the rows that need a real terminal. The picker uses `gum` or
`fzf`; the file chooser uses `zenity` or `gum`. All are already present on a
stock Omarchy.
