# omarchy-eq

Measure your laptop speakers with their own microphone, derive an EQ from the
measurement, and A/B the result live. Headphones get the same treatment from
measured presets instead — imported, or fetched from the AutoEq database — and
every output keeps its own EQ, switched automatically as you plug things in.

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

No root required. Everything lives under `~/.local` and `~/.config`.
Drop `--omarchy` if you are not on Omarchy. An Arch `PKGBUILD` is included.

**Requires** PipeWire + `pactl`, and `python3` (stdlib only — no numpy/scipy;
`fetch` talks to the AutoEq database with `urllib`). A systemd user session
supervises the filter chains and the watcher; without one, `apply --static`
falls back to the pre-v3 drop-in. The optional mic chain needs
`noise-suppression-for-voice`.

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
| `omarchy-eq autoswitch enable` | follow the output device automatically |
| `omarchy-eq route enable` | send each app's audio to the profile that suits it |
| `omarchy-eq fetch [model]` | search the AutoEq database and import a preset |
| `omarchy-eq ab list\|status` | show profiles / what's active |
| `omarchy-eq tui` | measured curve + EQ curve + profile switcher |
| `omarchy-eq import <file>` | import a preset: any AutoEq format, or a `.wav` impulse response |
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

## Switching outputs automatically

```bash
omarchy-eq autoswitch enable
```

A user service watches PipeWire and, when the output changes, puts the new one
on **the profile you last used there**. Plug in your headphones and they come
back on their own correction; unplug them and the speakers come back on theirs.

`omarchy-eq ab` records every switch you make, per device. A profile you chose
yourself is *pinned*, and nothing automatic overrides it.

The watcher is deliberately dull. `omarchy-eq autoswitch once` — the whole of
its reaction to an event — is a no-op whenever nothing needs doing, because
PipeWire emits an event for the tool's *own* `set-default-sink`. A watcher that
acted on that would chase its own tail forever.

What it picks, in order: the profile you last used there, if it still exists;
`voice` when the device is a Bluetooth headset in its call profile; otherwise
`balanced`; otherwise nothing, and it says why.

**A Bluetooth headset is two outputs.** In A2DP it is a wideband stereo sink.
Switch it to the headset profile for a call and BlueZ tears that sink down and
publishes a mono one at 8 or 16 kHz. Same hardware, different response — so
they get separate tags (`bt8ae6` and `bt8ae6hs`), separate measurements and
separate EQ. Correcting the call profile with a curve derived from A2DP would
be boosting treble the link never carries.

## Following the application, not just the device

Auto-switching answers "what am I listening *through*". This answers "what am I
listening *to*", which is a different question:

```bash
omarchy-eq route enable
```

Streams are then sent to the profile that suits them — **individually**. Spotify
plays through `music` while a video call plays through `voice`, at the same
time. That costs nothing to arrange, because every profile is already its own
sink; the streams simply get pointed somewhere else.

Three signals, most specific first:

- **What is actually playing.** Spotify's MPRIS track id distinguishes
  `/track/` from `/episode/`, which is the only way to tell a song from a
  podcast — both arrive on one stream with identical properties otherwise. A
  podcast gets the speech curve and goes back to the music curve afterwards.
- **The application.** `omarchy-eq route rule <app> <profile>` writes your own;
  the built-ins cover the obvious music and conferencing apps. `-` as the
  profile means "leave this app alone", which is different from removing the
  rule — removing it restores the built-in you were trying to suppress.
- **`media.role`.** PipeWire's own hint, where an app sets one. Notification
  blips (`event`) and pro audio (`production`) are deliberately left alone.

Anything nothing matches stays on whatever your default is. That is the common
case and it stays uneventful: routing is for the few streams where the right
answer is knowable, not a licence to move everything.

**It does not fight you.** Move a stream yourself and it stays moved — the
watcher notices it is no longer where it put it and backs off, right up until
the correct answer genuinely changes, which is the whole point of noticing a
song turning into a podcast.

`omarchy-eq route status` shows the rules and what it would do right now,
without doing it.

**Seeing it happen.** Routing deliberately leaves the default sink alone — that
is what lets two apps use two profiles at once — so `ab status` and the menu
checkmark, which both report the *default*, sit unchanged while the audio moves
around behind them. That is indistinguishable from routing being broken. The bar
widget therefore reports where the audio actually is: whatever is playing, not
whatever is default. `omarchy-eq route playing` prints the same thing.

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

## Applying without stopping the music

`apply` does not restart PipeWire. The filter chains live in
`~/.config/omarchy-eq/chains.conf`, loaded by a second small `pipewire -c`
process supervised as `omarchy-eq-chains.service` — the arrangement PipeWire's
own `filter-chain.conf` is built for. Reloading them restarts one short-lived
process and leaves every stream playing.

That is not a nicety, it is what makes the rest of this possible. Until v3 the
chains were a drop-in that the audio daemon read at startup, so installing an EQ
meant restarting the daemon and killing every stream on the machine. Doing that
each time you plugged in headphones would be worse than having no EQ at all.

Upgrading is automatic: the first `apply` deletes the old drop-in and restarts
PipeWire exactly once. On a system with no systemd user session, `apply
--static` keeps the old behaviour.

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

## Presets for headphones

The laptop mic cannot hear your headphones, so they get a *measured* preset
instead of a measurement. [AutoEq](https://autoeq.app) publishes about 6300 of
them. Fetch one by name:

```bash
omarchy-eq fetch "HD 650"
omarchy-eq apply
```

With no argument it searches for whatever is plugged in right now, which is
usually what you want. `--pick N` skips the prompt, `--device D` targets another
output, `--format` chooses the shape (below).

The catalogue index is fetched once and cached under `~/.cache/omarchy-eq` for a
week, so searching after that is local and instant. Nothing is fetched unless
you ask.

If you already have a file, `import` takes it:

```bash
omarchy-eq import ~/Downloads/"Nothing Ear ParametricEQ.txt" --device bt8ae6
```

### The four formats

AutoEq publishes every correction four ways, and its
["Choosing an Equalizer App"](https://github.com/jaakkopasanen/AutoEq/wiki/Choosing-an-Equalizer-App)
page is really a guide to which of them your software can eat. PipeWire can eat
all four, so all four are accepted — but they do not promise the same thing.

| Format | |
|---|---|
| `ParametricEQ.txt` | **Exact.** Every line is a biquad PipeWire already implements, so importing is a parse and a name map. Prefer this one. |
| `FixedBandEQ.txt` | Exact too — the same syntax with the frequencies pinned to fixed bands. |
| `GraphicEQ.txt` | **Approximate.** A sampled target curve, not a filter description, so it is *fitted* onto a bank of peaking filters. The worst-case error is printed and stored. `--bands N` buys a closer fit (default 10). Real presets land under 1 dB. |
| `.wav` impulse response | **Most accurate.** Run through PipeWire's `convolver`; an FIR can draw a response a biquad bank cannot. The file is copied into the device's state directory, because a chain pointing at `~/Downloads` breaks the first time you tidy up. |

GraphicEQ used to be rejected outright, with a message telling you to go and
find the parametric version. That is a fine answer right up until the only file
you have is this one.

AutoEq's impulse responses are **minimum phase** — their energy is at the very
front, so they delay nothing. (The HD 650's 4800-tap response has half its
energy inside the first three samples.) A linear-phase response of the same
length really would cost half its length in latency, so `import` measures where
the energy actually is rather than reporting length as latency.

### Fitting a curve, and the sample rate trap

Worth its own note, because getting it wrong is invisible. A biquad's shape near
Nyquist comes partly from bilinear warping, and a fit will exploit that if you
let it: fitted at 48 kHz alone, these presets came in under 1 dB of error *at
48 kHz* and missed by 6 dB when the graph ran at 96.

The obvious fix — fit for every common rate — is just as wrong, because every
rate in the list is a constraint the fit has to satisfy. Fitting for 44.1, 48
and 96 when the graph only ever runs at 48 **tripled** the error at 48.

So the rate list is not a constant. It comes from PipeWire's own
`clock.allowed-rates`, which is `[ 48000 ]` on a stock install and longer on a
machine set up for bit-perfect playback. The rates a profile was fitted at are
stored with it, and `doctor` says so if that setting changes afterwards.

### Letting it set up new devices by itself

```bash
omarchy-eq autoswitch enable --fetch
```

Off by default. With it on, an output the tool has never seen gets looked up in
the AutoEq catalogue and configured unattended — which means **sending the name
of hardware you own to github.com**. That should be a choice, not something that
starts happening when you plug in headphones.

The matcher refuses to guess. It declines on a weak name match, and it declines
on an *ambiguous* one — two different products scoring within a hair of each
other is a coin flip, and silently EQ-ing someone's headphones from a coin flip
is the failure mode worth engineering against. Several sources measuring the
same model is not ambiguity; that is one answer with a source to pick.

In practice it matches `WH-1000XM4 (Bluetooth Stereo)` to Sony WH-1000XM4, and
it declines on `Nothing Ear (open)` — the catalogue has the different product
`Nothing ear`, and installing that curve would be wrong.

Imported and fetched profiles survive `omarchy-eq generate`.

## Omarchy integration

There are two ways in. As an **Omarchy plugin**, which is the tidy one:

```bash
omarchy plugin add https://github.com/jackzasian/omarchy-eq.git --enable
~/.config/omarchy/plugins/jackzasian.eq/install.sh
```

That adds the menu entries, a profile picker that lists whatever the current
output actually has, and optional hotkeys. See [`plugin/README.md`](plugin/README.md).
The second step is separate because Omarchy reads a single user-owned menu file:
entries have to be merged into yours, and that is not something to do silently.

Or by hand, which is what the rest of this section describes.

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
~/.local/state/omarchy-eq/devices/<sink>/ir/*.wav        imported impulse responses
~/.local/state/omarchy-eq/config.json                    remembered profile per device
~/.config/omarchy-eq/chains.conf                         generated, do not edit
~/.config/systemd/user/omarchy-eq-chains.service         loads the chains
~/.config/systemd/user/omarchy-eq-autoswitch.service     the watcher
~/.cache/omarchy-eq/autoeq-index.md                      AutoEq catalogue, weekly
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

### Verifying by hand

`generate` and `apply` are not read-only. A bare `omarchy-eq generate` rewrites
`profiles.json` for the *real* device under `~/.local/state/omarchy-eq/`, and
`apply` overwrites the live `99-omarchy-eq.conf` and restarts PipeWire. Neither
asks first, and `generate` keeps no backup of the profiles it replaces.

So point them at a scratch state directory:

```bash
XDG_STATE_HOME=$(mktemp -d) omarchy-eq generate --device builtin
```

Seed that directory with a copy of the real `response.json` first if you want to
generate against a genuine measurement:

```bash
scratch=$(mktemp -d); dev=<sink-name>
mkdir -p "$scratch/omarchy-eq/devices/$dev"
cp ~/.local/state/omarchy-eq/devices/$dev/response.json \
   "$scratch/omarchy-eq/devices/$dev/"
XDG_STATE_HOME=$scratch omarchy-eq generate --device builtin
```

`generate` being deterministic from `response.json` is not a licence to run it on
live state: it only reproduces the installed profiles if they were generated from
the *current* `response.json`. If a measurement has landed since the last
`generate`, the on-disk profiles are stale and a "harmless" re-run will silently
replace them with different numbers — leaving `profiles.json` out of step with the
`99-omarchy-eq.conf` that is actually loaded.

`doctor` also runs a health check over the installed profiles: a convolution
profile whose impulse response was deleted, a curve fitted for sample rates that
no longer apply, a poor fit, a remembered profile a later `generate` removed.
Each of those fails quietly otherwise — the profile keeps its name and simply
stops being what it claims to be.

`doctor`, `ab status`, `devices` and `export` are read-only and safe to run
against live state. To render the config without installing it, call the library
directly rather than using `apply`:

```bash
# Tab-separated, and device labels contain spaces -- split on tabs, not words.
mapfile -t args < <(PYTHONPATH=lib python3 lib/state.py render-args | tr '\t' '\n')
PYTHONPATH=lib python3 lib/render.py "${args[@]}"            # standalone form
PYTHONPATH=lib python3 lib/render.py --fragment "${args[@]}" # the pre-v3 drop-in
```
