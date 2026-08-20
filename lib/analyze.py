#!/usr/bin/env python3
"""Signal analysis for omarchy-eq. Pure stdlib - no numpy/scipy required.

Two ways to measure the level of a test tone:

  goertzel  single-bin DFT. Exact for a *pure* sine, and it rejects broadband
            noise far better than plain RMS. Kept for the `tone` mode.

  band      cascaded bandpass then RMS, for *warble* tones. A warble spreads
            its energy over a 1/3-octave span, which is the whole point -- a
            comb-filter null is narrow, so a swept tone cannot be annihilated
            by one. But that also means a single Goertzel bin no longer sees
            most of the energy. Summing bins is not viable either: a
            1/3-octave band at 16 kHz spans ~4000 DFT bins and each Goertzel
            is O(n). Filtering once is O(n) for the entire band.

Both return dBFS, but on *different references*: goertzel reports the tone's
peak amplitude, band_level reports RMS. For a sine those differ by 3.01 dB. That
is harmless because the derivation only ever looks at the shape of one curve
measured one way -- but never mix the two within a single measurement.
"""
import math
import struct
import sys
import wave

import biquad

# Warble spans +/-1/6 octave. Q=2.0 is a little wider than that, so the sweep
# edges are only ~0.8 dB down; two stages then buy ~26 dB of rejection a decade
# away. The small edge loss is identical at every frequency, so it biases the
# absolute level but not the *shape* of the measured response -- which is all
# the derivation uses.
BAND_Q = 2.0
BAND_STAGES = 2
WARBLE_OCT = 1.0 / 6.0


def read_mono(path):
    """Return (samples, samplerate) taking channel 0 of a PCM wav."""
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM")
        n, ch, sr = w.getnframes(), w.getnchannels(), w.getframerate()
        raw = w.readframes(n)
    if n == 0:
        return [], sr
    data = struct.unpack("<%dh" % (n * ch), raw)
    return ([data[i * ch] for i in range(n)] if ch > 1 else list(data)), sr


def dbfs(v):
    return -120.0 if v <= 0 else 20 * math.log10(v / 32768.0)


def rms(samples):
    if not samples:
        return -120.0
    return dbfs(math.sqrt(sum(s * s for s in samples) / len(samples)))


def peak(samples):
    return dbfs(max((abs(s) for s in samples), default=0))


def goertzel(samples, sr, freq):
    """Magnitude in dBFS at `freq`. O(n), single-bin DFT."""
    n = len(samples)
    if n == 0:
        return -120.0
    k = int(0.5 + n * freq / sr)
    w = 2 * math.pi * k / n
    coeff = 2 * math.cos(w)
    s1 = s2 = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2, s1 = s1, s0
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return dbfs(math.sqrt(max(power, 0.0)) * 2 / n)


def band_level(samples, sr, fc, q=BAND_Q, stages=BAND_STAGES, settle=0.05):
    """dBFS of the energy in a ~1/3-octave band centred on `fc`.

    `settle` discards the leading fraction of the filtered signal so the
    biquads' startup transient does not count as signal. At the lowest
    frequencies the transient is the longest, which is exactly where the
    measurement is most fragile.
    """
    if not samples:
        return -120.0
    sig = samples
    coeffs = biquad.design("bandpass", fc, sr, q)
    for _ in range(max(1, stages)):
        sig = biquad.process(coeffs, sig)
    skip = int(len(sig) * settle)
    return rms(sig[skip:] or sig)


def main():
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: analyze.py {tone <file> <hz>|band <file> <hz>|"
            "floor <file> <hz>...|level <file>}")
    mode, path = sys.argv[1], sys.argv[2]
    samples, sr = read_mono(path)
    if mode == "tone":
        print("%.2f" % goertzel(samples, sr, float(sys.argv[3])))
    elif mode == "band":
        print("%.2f" % band_level(samples, sr, float(sys.argv[3])))
    elif mode == "floor":
        # Batch: one process measures the noise floor in every band at once.
        for a in sys.argv[3:]:
            print("%s %.2f" % (a, band_level(samples, sr, float(a))))
    elif mode == "level":
        print("%.2f %.2f" % (rms(samples), peak(samples)))
    else:
        raise SystemExit("unknown mode: %s" % mode)


if __name__ == "__main__":
    main()
