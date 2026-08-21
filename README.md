# omarchy-eq

Measure your laptop speakers with their own microphone, derive an EQ from the
measurement, and A/B the result live.

Laptop speakers are small, sealed and mounted in a chassis that resonates. They
share a family of problems — no output below a few hundred Hz, a honky low-mid
resonance, and a dip exactly where speech intelligibility lives — but the
specifics differ per machine. `omarchy-eq` measures *your* machine instead of
applying somebody else's curve.

Built for [Omarchy](https://omarchy.org) but it only needs PipeWire, so it works
on any modern Linux desktop.

## Install

```bash
git clone https://github.com/jackzasian/omarchy-eq
cd omarchy-eq && ./install.sh --omarchy
```

No root required. Everything lives under `~/.local` and `~/.config/pipewire`.
Drop `--omarchy` if you are not on Omarchy. An Arch `PKGBUILD` is included.

**Requires** PipeWire + `pactl`, and `python3` (stdlib only — no numpy/scipy).
The optional mic chain needs `noise-suppression-for-voice`.

## Use

```bash
omarchy-eq calibrate     # the whole thing: measure twice, derive, apply, play
```

That is the one command. It sweeps from where the laptop is, asks you to move
it, sweeps again, derives the profiles, installs them, and puts your music back
on. About 7 minutes, most of it audible. The steps are also available
separately (`measure`, `measure --again`, `generate`, `apply`).

Then listen. All profiles load **at once** as separate sinks, so switching is
instant and happens mid-playback — restarting PipeWire between settings destroys
your memory of the previous one, which makes honest A/B impossible.

```bash
omarchy-eq ab flat       # reference: no EQ
omarchy-eq ab balanced   # switch, mid-song
omarchy-eq ab            # cycle to the next profile
omarchy-eq tui           # see the curve, switch profiles
```

Bind `omarchy-eq ab` to a key for one-handed comparison. Each switch shows a
notification naming the active profile and its curve.

| Command | |
|---|---|
| `omarchy-eq devices` | list outputs and what each one has |
| `omarchy-eq ab list\|status` | show profiles / what's active |
| `omarchy-eq tui` | measured curve + EQ curve + profile switcher |
| `omarchy-eq import <file.txt>` | import an Equalizer APO / AutoEQ preset |
| `omarchy-eq export` | print the measured curve as plain text |
| `omarchy-eq mic enable\|disable` | RNNoise capture chain |
| `omarchy-eq doctor` | audio state + diagnosis |
| `omarchy-eq reset` | remove everything, restore raw output |

## One EQ per output

Every output device gets its own measurement, its own profiles and its own set
of sinks (`eq_<device>_<profile>`). `omarchy-eq devices` shows what you have:

```
  TAG        KIND        MEASURE  PROFILES             DEVICE
* builtin    builtin     yes      3  (2 runs, 19 pts)  Built-in Audio Analog Stereo
  bt8ae6     headphones  no       1  (imported)        Nothing Ear (open) [aac]
  sonos      stream      no       -                    Sonos Roam
```

Every command acts on whichever output you are currently using, or on
`--device <tag>` if you say so. Switching headphones on and running
`omarchy-eq ab` just works on the headphones.

**Not everything can be measured.** The measurement plays a tone and records it
on the laptop's own microphone, so it only means anything when the sound is in
the room and arrives promptly:

- **Speakers** (built-in, USB, analog) — measurable. This is the interesting case.
- **Headphones and headsets** — the laptop mic cannot hear them. Measuring is
  refused; import an [AutoEQ](https://autoeq.app) preset for your model instead.
- **Network outputs** (Sonos, RAOP) — their buffering puts the tone outside the
  recording window, so a measurement would be noise. Import-only.

```bash
omarchy-eq import ~/Downloads/"Nothing Ear ParametricEQ.txt" --device bt8ae6
omarchy-eq apply
```

Devices that are not connected are skipped by `apply` — a filter chain pinned to
an absent sink does nothing useful. Reconnect and re-run `omarchy-eq apply`.

## Why two measurements

Measure once and you are not measuring your speaker. You are measuring
**speaker × microphone × room geometry**, and nothing in a single pass can tell
those apart.

The dominant artifact is comb filtering: sound reaches the mic directly *and*
after bouncing off the desk, and at frequencies where the two paths cancel you
get a null 20 dB deep that has nothing to do with the driver. Correcting one is
worse than doing nothing — it boosts a frequency the speaker reproduces fine.

Three things push back on this:

- **Warble tones.** Every test tone sweeps ±1/6 octave rather than sitting at one
  frequency. A comb null is narrow and fixed; a tone that moves cannot fall
  entirely into one.
- **A noise floor pass.** Silence is recorded first, and any tone that fails to
  rise 10 dB above the floor is marked *unknown* rather than recorded as a real
  measurement of quietness.
- **Two positions.** A comb null moves when the microphone moves. The driver does
  not. So `measure --again` runs the whole sweep from a second position and keeps
  only what both runs agree on — anything differing by more than 6 dB between
  them is discarded as geometry.

You can skip `--again`, and the tool will work. It will also tell you that every
point is single-confidence, and it is more likely to hit its safety clamps.

## What it will not do

Corrections are clamped on purpose: highpass 80–300 Hz, cuts and boosts ≤6 dB,
shelves ≤3 dB, and only 65 % of the measured deviation is applied. An
uncalibrated near-field measurement systematically overstates deviation, and
fully inverting it produces a harsh, over-EQ'd result. If a parameter lands on
its clamp, `generate` says so — that is the measurement telling you it ran off
the end of what this tool will attempt.

It also refuses to correct above 8 kHz when the measurement reads *hotter* there
than the midband. No small sealed driver is brighter than its own midrange, so
that reading is the microphone's own resonance, and "correcting" it would cut
real treble.

## Importing headphone presets

```bash
omarchy-eq import ~/Downloads/HD650\ ParametricEQ.txt
omarchy-eq apply
```

Equalizer APO / [AutoEQ](https://autoeq.app) parametric presets map onto the same
biquads PipeWire already implements, so an import is exact — no resampling and no
approximation. `Preamp:` becomes a real broadband gain stage. Download the
**ParametricEQ** variant; fixed-band `GraphicEQ` files are not parametric and are
rejected with a message saying so.

Imported profiles survive `omarchy-eq generate`.

## Omarchy integration

`./install.sh --omarchy` installs the terminal shim and, if you have no menu
extension yet, the menu file. Omarchy reads a single user-owned menu file, so if
you already have one the installer prints what to merge rather than rewriting it.

**Menu.** [`omarchy/omarchy-menu.jsonc`](omarchy/omarchy-menu.jsonc) merges into
`~/.config/omarchy/extensions/omarchy-menu.jsonc` (it hot-reloads on save). This
adds a **Speaker EQ** submenu listing every profile, plus the clean-mic toggle,
the curve view, re-measure and diagnostics. Two niceties come from the menu
format itself:

- `"checked"` puts a checkmark on the profile that is **currently active**
- `"when"` hides the profile rows until a measurement actually exists

Terminal rows go through [`omarchy/omarchy-eq-term`](omarchy/omarchy-eq-term),
which exists so `measure` gets a real TTY for its prompt and holds output open
afterwards. (It was called `omarchy-eq-tui` before `omarchy-eq tui` became the
actual interactive UI.)

**Hotkey.** Add [`omarchy/bindings.lua.snippet`](omarchy/bindings.lua.snippet)
to `~/.config/hypr/bindings.lua` for `SUPER+ALT+E` to cycle profiles. Check the
key is free first with `omarchy menu keybindings --print`, and if it is taken,
`hl.unbind` it before rebinding.

If you write your own menu icons, use **literal glyphs** rather than `\uXXXX`
escapes. Nerd Font icons are outside the BMP, so an escape needs a correct
surrogate pair and a wrong one is easy to write and awkward to spot.

## Where things live

```
~/.local/state/omarchy-eq/devices/<sink>/response.json   measurements
~/.local/state/omarchy-eq/devices/<sink>/profiles.json   derived + imported
~/.local/state/omarchy-eq/devices/<sink>/response.previous.json   the last one
~/.config/pipewire/pipewire.conf.d/99-omarchy-eq.conf    generated, do not edit
```

A new measurement keeps the one it replaces as `response.previous.json` — a
sweep costs minutes, so nothing throws one away silently.

State is keyed by output device, and lives under `XDG_STATE_HOME` — separate from
the installed library. Measurements from before v2 migrate automatically.

## Development

```bash
python -m unittest discover -s tests -t tests
```

No test dependencies; the suite is stdlib `unittest`, same as the library. The
interesting tests are the ones pinning down *why* the code is shaped the way it
is — that `goertzel` badly underreads a warble (which is why `band_level` exists),
that the music profile can never end up less airy than balanced, and that a
measurement disagreeing between positions gets thrown away.
