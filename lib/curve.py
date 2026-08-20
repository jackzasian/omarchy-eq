#!/usr/bin/env python3
"""Frequency response of a generated filter chain. Pure stdlib.

Lets the TUI draw what the EQ actually does, and makes the EQ itself testable
without a running PipeWire.
"""
import json
import math
import sys

import biquad

SR = 48000


def log_axis(lo=20.0, hi=20000.0, n=64):
    step = (math.log10(hi) - math.log10(lo)) / (n - 1)
    return [10.0 ** (math.log10(lo) + i * step) for i in range(n)]


def chain_response(filters, freqs, sr=SR):
    """Combined |H(f)| in dB. Sections are in series, so dB add."""
    out = []
    for f in freqs:
        total = 0.0
        for filt in filters:
            c = filt["control"]
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
