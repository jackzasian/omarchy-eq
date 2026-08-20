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
cd omarchy-eq && ./install.sh
```

No root required. Everything lives under `~/.local` and `~/.config/pipewire`.

**Requires** PipeWire + `pactl`, and `python3` (stdlib only — no numpy/scipy).
The optional mic chain needs `noise-suppression-for-voice`.

## Use

```bash
omarchy-eq measure     # play tones, record on the internal mic (~60s, audible)
omarchy-eq generate    # derive EQ profiles from the measurement
omarchy-eq apply       # install them as PipeWire sinks
```

Then listen. All profiles load **at once** as separate sinks, so switching is
instant and happens mid-playback — restarting PipeWire between settings destroys
your memory of the previous one, which makes honest A/B impossible.

```bash
omarchy-eq ab flat       # reference: no EQ
omarchy-eq ab balanced   # switch, mid-song
omarchy-eq ab            # cycle to the next profile
```

Bind `omarchy-eq ab` to a key for one-handed comparison. Each switch shows a
notification naming the active profile and its curve.

| Command | |
|---|---|
| `omarchy-eq ab list\|status` | show profiles / what's active |
| `omarchy-eq mic enable\|disable` | RNNoise capture chain |
| `omarchy-eq doctor` | audio state + diagnosis |
| `omarchy-eq reset` | remove everything, restore raw output |

## Profiles

Three are generated from one measurement:

- **balanced** — the measured correction, for general use
- **voice** — calls and video: higher high-pass, more presence
- **music** — keeps low-mid warmth, adds air

## How it measures

A stepped sine sweep, 50 Hz–16 kHz at 1/3-octave spacing, analysed with a
[Goertzel filter](https://en.wikipedia.org/wiki/Goertzel_algorithm) rather than
an FFT. Goertzel evaluates a single known bin in O(n) with no dependencies, and
rejects broadband room noise far better than a plain RMS reading — which matters
because the microphone is centimetres from the speaker in a noisy chassis.

## How it derives EQ — and what it deliberately won't do

**It does not invert the measured curve.** A single-position, near-field
measurement taken with an uncalibrated mic inside the chassis is full of sharp
nulls from comb filtering and mic placement. Those move if you tilt the lid.
Inverting them means trying to fill a 30 dB hole that isn't really there, which
sounds far worse than no EQ at all.

So the tool corrects only broad, physically plausible trends:

1. **Smooth** the curve over ~1 octave — wide enough to reject single-point
   artifacts, narrow enough not to smear a real resonance.
2. **Reject nulls** when computing band levels. Nulls are sharp *downward*
   excursions, so the lowest 40% of points in a band are discarded before
   averaging. Without this the midband reference gets dragged down and every
   correction is inflated to its clamp.
3. **Partial correction** (65%). Near-field measurement systematically
   overstates deviation; room-correction software applies the same discount.
4. **Clamp** everything: high-pass 80–300 Hz, cuts and boosts ≤6 dB, shelf ≤3 dB.

The high-pass is the biggest single win. Content below the driver's usable range
produces no audible output but still consumes excursion and amplifier headroom,
so removing it cleans up everything above it.

## Caveats

The measurement is **relative, not calibrated**. It captures the speaker, the
chassis, the mic's own response and the path between them, all at once. It is
good enough to find your rolloff point and gross resonances — which is what EQ
needs — and not good enough to publish as a frequency response plot.

Results depend on the surface the laptop sits on and the lid angle. Measure in
the position you actually use.

## Notes for hacking on it

Two things that cost me real debugging time, documented so they don't cost you any:

- **LADSPA ports are `Input`/`Output`; PipeWire's builtin biquads use `In`/`Out`.**
  Mixing them up makes the pipewire daemon abort at startup and crash-loop into
  systemd's rate limit.
- **Filter-chain outputs must be pinned** with `target.object` +
  `node.dont-reconnect`. Otherwise WirePlumber re-routes each chain to whatever
  the current default sink is — which chains the EQs into each other as soon as
  one becomes the default.

## License

MIT
