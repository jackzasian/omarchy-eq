# Speaker EQ — an Omarchy plugin

Per-device PipeWire equalisation for [Omarchy](https://omarchy.org): a bar item
showing which EQ profile your audio is actually going through, a menu for
switching, automatic per-output switching, and per-application routing.

It is the desktop front end for [omarchy-eq](https://github.com/jackzasian/omarchy-eq),
which does the actual work — measuring speakers, deriving corrections, importing
[AutoEq](https://autoeq.app) headphone presets. The plugin will tell you if the
tool is missing.

---

## Install

```bash
omarchy plugin add https://github.com/jackzasian/omarchy-eq.git --enable
~/.config/omarchy/plugins/jackzasian.eq/plugin/install.sh
```

The second step is separate on purpose. Omarchy copies a plugin folder into
place, but the menu is a **single user-owned file** that every extension shares,
so entries have to be merged into yours rather than dropped alongside it. If you
already have a menu file, the installer prints what to add and changes nothing.

`--enable` turns the bar widget on. Without it the plugin installs but stays
*disabled* and nothing appears — enable it later with:

```bash
omarchy plugin enable jackzasian.eq right     # left | center | right
```

Remove it with `plugin/uninstall.sh`, then `omarchy plugin remove jackzasian.eq`.
The uninstaller only deletes shims that are still byte-for-byte ours; anything
you edited stays.

---

## How it works

Three mechanisms that people conflate. They answer different questions and can
be used independently.

### 1. Profiles are separate sinks, all loaded at once

`omarchy-eq apply` creates one PipeWire sink per profile — `eq_builtin_flat`,
`eq_builtin_balanced`, `eq_builtin_music`, and so on — and they all exist
simultaneously. Switching is just moving a stream, so it happens mid-song with
no gap.

This is also why two applications can use two different profiles at the same
time: nothing has to be swapped, the streams just point at different sinks.

Since v3 these are loaded by a small `pipewire -c` process supervised as
`omarchy-eq-chains.service`, **not** by a `pipewire.conf.d` drop-in. Reloading
them restarts one short-lived process instead of the audio server, which is what
makes automatic switching bearable — otherwise plugging in headphones would kill
every stream on the machine.

### 2. Auto-switch follows the output **device**

`omarchy-eq autoswitch enable` starts a watcher on `pactl subscribe`. When the
output changes, the new device is put on **the profile you last used there**.

It reacts to `sink` (devices appearing), `card` (a Bluetooth headset flipping
between A2DP and its call profile) and `server` (the default moving). It
deliberately ignores stream events — those fire constantly and do not change
which *device* you are on.

Preference order: your last choice there → `voice` if the device is a Bluetooth
headset in its call profile → `balanced` → nothing, with a reason.

### 3. Routing follows the **application**

`omarchy-eq route enable` sends each stream to the profile that suits it —
individually. Spotify on `music` while a video call is on `voice`, at the same
time.

Three signals, most specific first:

| Signal | What it is |
|---|---|
| Content | Spotify's MPRIS track id distinguishes `/track/` from `/episode/` — the only way to tell a song from a podcast, since both arrive as one stream with identical properties |
| App rule | `application.name` or the process binary, matched against your rules then the built-ins |
| `media.role` | PipeWire's own hint, where an app sets one |

Anything unmatched stays on the default. Notification blips (`role = event`) and
pro audio (`role = production`) are deliberately left alone.

**Routing needs the autoswitch watcher running** — that is the process that
applies it. `route enable` says so if it is not.

### Why the bar shows what it shows

Routing deliberately does **not** touch the default sink; that is precisely what
lets two apps use two profiles at once. So `omarchy-eq ab status` and the menu
checkmark — which both report the *default* — sit unchanged while your audio
moves around behind them.

The bar therefore reports **where the audio actually is**: whatever is playing,
falling back to the default only when nothing is. The popup's *Playing through*
section lists each application and its profile. That list is ground truth; check
it first when something looks wrong.

---

## Configuring it for your setup

Everything below is per-machine. Nothing here assumes the hardware it was
developed on.

### Which outputs exist

```bash
omarchy-eq devices
```

```
  TAG        KIND        MEASURE  PROFILES             DEVICE
* builtin    builtin     yes      3  (2 runs, 19 pts)  Built-in Audio Analog Stereo
  bt8ae6     headphones  no       1  (imported)        Nothing Ear (open) [aac]
  bt8ae6hs   headphones  no       -                    Nothing Ear (open)
  sonos      stream      no       -                    Sonos Roam
```

Every output has its own measurement, profiles, sinks and remembered choice. The
`TAG` is what you pass to `--device`, and it is stable across reconnects.

**A Bluetooth headset appears twice.** `bt8ae6` is A2DP; `bt8ae6hs` is the
headset/call profile, which is 8 or 16 kHz mono. They are genuinely different
sinks with different responses, so they get separate EQ. Correcting the call
profile with a curve derived from A2DP would boost treble the link never
carries.

### Getting profiles onto each output

**Speakers** — measure them. This is the case the tool exists for:

```bash
omarchy-eq calibrate            # ~7 minutes, audible
```

**Headphones** — the laptop microphone cannot hear them, so measuring is
refused. Use a measured preset instead:

```bash
omarchy-eq fetch                        # searches AutoEq for the connected device
omarchy-eq fetch "HD 650" --pick 1      # or by name, non-interactively
omarchy-eq import ~/Downloads/preset.txt
omarchy-eq apply
```

`import` accepts all four AutoEq formats — `ParametricEQ.txt` (exact, prefer it),
`FixedBandEQ.txt` (also exact), `GraphicEQ.txt` (fitted onto biquads, reports its
error) and `.wav` impulse responses (run through PipeWire's convolver).

**Network outputs** (Sonos, RAOP) — import only. Their buffering puts a test tone
outside the recording window, so a measurement would be noise.

### Application routing rules

```bash
omarchy-eq route status                 # rules, and what it would do right now
omarchy-eq route rule obs music         # send OBS to the music profile
omarchy-eq route rule spotify -         # leave Spotify alone entirely
omarchy-eq route rule spotify           # remove the rule (restores the built-in)
```

The three-way distinction matters: **removing** a rule restores the built-in one,
which for a built-in app is exactly what you were trying to stop. `-` stores an
exemption.

Match against whatever `application.name` or `application.process.binary`
reports. To find out what an app calls itself:

```bash
pactl list sink-inputs | grep -E 'application.name|application.process.binary'
```

Rules live in `~/.local/state/omarchy-eq/config.json` under `routing.apps`, and
a profile name only takes effect if that output actually has a profile by that
name.

### Unattended AutoEq lookup

```bash
omarchy-eq autoswitch enable --fetch
```

Off by default, and worth understanding before turning on: an output the tool has
never seen gets looked up in the AutoEq catalogue and configured automatically,
which means **sending the name of hardware you own to github.com**.

The matcher refuses to guess. It declines on a weak name match *and* on an
ambiguous one — two different products scoring within a hair of each other is a
coin flip, and silently EQ-ing your headphones from a coin flip is worse than
doing nothing. In practice it matches `WH-1000XM4 (Bluetooth Stereo)` to Sony
WH-1000XM4 and declines on `Nothing Ear (open)`, because the catalogue only has
the different product `Nothing ear`.

### Sample rates

If you have changed PipeWire's `clock.allowed-rates` for bit-perfect playback,
re-import any `GraphicEQ` presets. Those are *fitted*, and a fit is only valid at
the rates it was made for — a biquad's shape near Nyquist depends on the sample
rate. `omarchy-eq doctor` warns when a profile's fitted rates no longer match the
graph.

### Hotkeys

Not installed automatically. Check the keys are free first:

```bash
omarchy menu keybindings --print
```

Then add to `~/.config/hypr/bindings.conf`:

```
source = ~/.config/omarchy/plugins/jackzasian.eq/plugin/hypr/bindings.conf
```

`Super+Alt+E` cycles profiles; `Super+Alt+Shift+E` opens the picker.

---

## The menu entries

| Entry | |
|---|---|
| Switch Profile | pick from the profiles *this output* has |
| Cycle Profile | next profile, no prompt |
| Auto-switch per Output | follow the device, restore its last profile |
| Fetch Preset (AutoEq) | search ~6300 measured presets for the connected device |
| Import Preset File | any AutoEq format, or a `.wav` impulse response |
| Clean Mic (RNNoise) | toggle the noise-suppressed capture chain |
| Curve & Profiles | measured response and each EQ curve, in a TUI |
| Outputs | every sink and what it has |
| Re-measure Speakers | two-position measurement, then rebuild |
| Audio Diagnostics | audio state, services, and a profile health check |
| Remove EQ | delete the profiles, restore raw output |

*Switch Profile* is a shim rather than one row per profile, because profiles are
per-device and open-ended — a fetched preset gets a key like
`sennheiser_hd_650`. A static menu file cannot express that, so it asks the tool
what exists on the current output.

Rows that need omarchy-eq v3 are gated on `omarchy-eq help` mentioning the
subcommand rather than on a version string, so an older install hides them
instead of offering an entry that fails.

---

## Troubleshooting

**Nothing on the bar.** The plugin is probably installed but disabled — that is
the default without `--enable`:

```bash
omarchy-plugin-list | grep jackzasian.eq
omarchy plugin enable jackzasian.eq right
```

**A change to the QML did nothing.** Quickshell caches the *failed* compilation
and keeps replaying the old error at the old line numbers, so a fixed file can
still report a problem at a line that is now blank. `omarchy-restart-shell` is
what proves a fix; clearing `~/.cache/quickshell/qmlcache` is not enough.

**The menu is missing the v3 rows.** Your menu file predates them and the
installer will not overwrite it. Merge from
`~/.config/omarchy/plugins/jackzasian.eq/plugin/menu/omarchy-eq.jsonc`.

**Routing seems to do nothing.** Check ground truth first:

```bash
omarchy-eq route playing          # where each app's audio actually is
omarchy-eq route status           # rules, and what it would do now
journalctl --user -u omarchy-eq-autoswitch.service -f
```

Two expected behaviours that look like failures: routing does not change the
default sink, and it will not move a stream you moved yourself — it backs off
until the correct answer genuinely changes.

**Profiles vanished after reconnecting a device.** `apply` skips outputs that are
not connected, since a chain pinned to an absent sink does nothing. Reconnect and
run `omarchy-eq apply`.

**Everything sounds wrong.** `omarchy-eq ab flat` is the reference — no EQ at
all. `omarchy-eq reset` removes the lot and restores raw output; measurements and
profiles are kept.

---

## Requirements

`omarchy-eq` on PATH, plus `omarchy-eq-term` from its `./install.sh --omarchy`
for the rows that need a real terminal. The picker uses `gum` or `fzf`; the file
chooser uses `zenity` or `gum`; `playerctl` is needed for Spotify content
detection. All are present on a stock Omarchy.

Licensed MIT, same as omarchy-eq.
