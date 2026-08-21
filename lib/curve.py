#!/usr/bin/env python3
"""Frequency response of a generated filter chain. Pure stdlib.

Lets the TUI draw what the EQ actually does, and makes the EQ itself testable
without a running PipeWire.

Convolution profiles are drawn too, from the impulse response itself rather than
from a filter description -- there isn't one. Evaluating the DFT at just the
frequencies being plotted costs one pass per point, which for 64 points and a
5000-tap response is nothing, and it means a convolution profile is a line on the
same axes as every other profile instead of a blank panel and an apology.
"""
import json
import math
import os
import struct
import sys
import wave

import biquad

SR = 48000


def log_axis(lo=20.0, hi=20000.0, n=64):
    step = (math.log10(hi) - math.log10(lo)) / (n - 1)
    return [10.0 ** (math.log10(lo) + i * step) for i in range(n)]


def read_ir(path, channel=0):
    """[samples] for one channel of a WAV impulse response, normalised to +/-1."""
    with wave.open(path, "rb") as w:
        n, ch, sw, rate = (w.getnframes(), w.getnchannels(),
                           w.getsampwidth(), w.getframerate())
        raw = w.readframes(n)
    fmt = {1: "b", 2: "h", 4: "i"}.get(sw)
    if not fmt or not n:
        raise ValueError("unsupported WAV sample format in %s" % path)
    full = struct.unpack("<%d%s" % (n * ch, fmt), raw[:n * ch * sw])
    scale = float(1 << (8 * sw - 1))
    return [v / scale for v in full[min(channel, ch - 1)::ch]], rate


def ir_response(samples, freqs, sr):
    """|H(f)| in dB of an impulse response, by direct DFT at the plot points.

    A full FFT would give every bin and we want 64 of them, so evaluating the
    sum directly is both simpler and cheaper here. Goertzel would shave a
    constant factor off it and buy nothing at this size.
    """
    out = []
    for f in freqs:
        w = 2.0 * math.pi * f / sr
        re = im = 0.0
        for n, x in enumerate(samples):
            a = w * n
            re += x * math.cos(a)
            im -= x * math.sin(a)
        out.append(20.0 * math.log10(max(math.hypot(re, im), 1e-9)))
    return out


def chain_response(filters, freqs, sr=SR):
    """Combined |H(f)| in dB. Sections are in series, so dB add."""
    # A convolution profile is one node and no filter description; its response
    # has to come out of the file it points at.
    conv = next((f for f in filters if f.get("label") == "convolver"), None)
    if conv is not None:
        cfg = conv.get("config") or conv.get("config_l") or {}
        path = cfg.get("filename", "")
        if not os.path.exists(path):
            raise FileNotFoundError(
                "impulse response is missing: %s\n"
                "Re-import it, or drop the profile." % path)
        samples, ir_sr = read_ir(path, int(cfg.get("channel", 0)))
        return list(zip(freqs, ir_response(samples, freqs, ir_sr)))

    out = []
    for f in freqs:
        total = 0.0
        for filt in filters:
            c = filt.get("control") or {}
            if filt["label"] == "linear":
                # broadband gain stage (APO preamp): flat, so add it once
                total += 20.0 * math.log10(max(float(c.get("mult", 1.0)), 1e-9))
                continue
            co = biquad.design(filt["label"], c["Freq"], sr,
                               c.get("Q", 0.707), c.get("Gain", 0.0))
            total += biquad.magnitude_db(co, f, sr)
        out.append((f, total))
    return out


def main():
    data = json.load(open(sys.argv[1]))
    name = sys.argv[2]
    for f, g in chain_response(data["profiles"][name]["filters"], log_axis()):
        print("%.1f %.2f" % (f, g))


if __name__ == "__main__":
    main()
