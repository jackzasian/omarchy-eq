#!/usr/bin/env python3
"""Signal analysis for omarchy-eq. Pure stdlib - no numpy/scipy required.

Goertzel is used instead of a full FFT because we only ever need the magnitude
at one known tone frequency, and it rejects broadband room noise far better
than a plain RMS measurement.
"""
import math
import struct
import sys
import wave


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


def main():
    mode, path = sys.argv[1], sys.argv[2]
    samples, sr = read_mono(path)
    if mode == "tone":
        print("%.2f" % goertzel(samples, sr, float(sys.argv[3])))
    elif mode == "level":
        print("%.2f %.2f" % (rms(samples), peak(samples)))
    else:
        raise SystemExit("usage: analyze.py {tone <file> <hz>|level <file>}")


if __name__ == "__main__":
    main()
