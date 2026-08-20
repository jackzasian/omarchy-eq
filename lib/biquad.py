#!/usr/bin/env python3
"""Biquad design, evaluation and filtering. Pure stdlib.

Shared by two callers that would otherwise each need their own copy:

  analyze.py  needs a *bandpass* to measure the energy of a warble tone. A
              per-bin Goertzel cannot do this -- a 1/3-octave band at 16 kHz
              spans ~4000 DFT bins, and one Goertzel per bin is O(n) each.
              Filtering once and taking RMS is O(n) total.

  curve.py    needs |H(f)| of the bq_* filters generate.py emits, so the TUI
              can draw what the EQ actually does.

Coefficients follow the Robert Bristow-Johnson audio EQ cookbook. The bandpass
uses the constant-0-dB-peak-gain form so a measured level stays meaningful in
absolute terms.
"""
import math

# generate.py emits PipeWire builtin labels; map them onto cookbook types.
LABELS = {
    "bq_lowpass": "lowpass",
    "bq_highpass": "highpass",
    "bq_bandpass": "bandpass",
    "bq_lowshelf": "lowshelf",
    "bq_highshelf": "highshelf",
    "bq_peaking": "peaking",
    "bq_notch": "notch",
    "bq_allpass": "allpass",
}


def design(kind, fc, sr, q=0.707, gain_db=0.0):
    """Return normalised (b0, b1, b2, a1, a2) for one biquad section."""
    if kind in LABELS:
        kind = LABELS[kind]
    # Nyquist guard: a filter cornered above sr/2 is meaningless, and tan()
    # blows up as w0 approaches pi.
    fc = max(1.0, min(float(fc), sr * 0.495))
    w0 = 2.0 * math.pi * fc / sr
    cos_w0, sin_w0 = math.cos(w0), math.sin(w0)
    q = max(1e-4, float(q))
    alpha = sin_w0 / (2.0 * q)
    A = 10.0 ** (gain_db / 40.0)          # amplitude, shelf/peaking only

    if kind == "peaking":
        b0, b1, b2 = 1 + alpha * A, -2 * cos_w0, 1 - alpha * A
        a0, a1, a2 = 1 + alpha / A, -2 * cos_w0, 1 - alpha / A
    elif kind == "lowpass":
        b0, b1, b2 = (1 - cos_w0) / 2, 1 - cos_w0, (1 - cos_w0) / 2
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == "highpass":
        b0, b1, b2 = (1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == "bandpass":
        # constant 0 dB peak gain
        b0, b1, b2 = alpha, 0.0, -alpha
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == "notch":
        b0, b1, b2 = 1.0, -2 * cos_w0, 1.0
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == "allpass":
        b0, b1, b2 = 1 - alpha, -2 * cos_w0, 1 + alpha
        a0, a1, a2 = 1 + alpha, -2 * cos_w0, 1 - alpha
    elif kind == "lowshelf":
        s = 2.0 * math.sqrt(A) * alpha
        b0 = A * ((A + 1) - (A - 1) * cos_w0 + s)
        b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
        b2 = A * ((A + 1) - (A - 1) * cos_w0 - s)
        a0 = (A + 1) + (A - 1) * cos_w0 + s
        a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
        a2 = (A + 1) + (A - 1) * cos_w0 - s
    elif kind == "highshelf":
        s = 2.0 * math.sqrt(A) * alpha
        b0 = A * ((A + 1) + (A - 1) * cos_w0 + s)
        b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
        b2 = A * ((A + 1) + (A - 1) * cos_w0 - s)
        a0 = (A + 1) - (A - 1) * cos_w0 + s
        a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
        a2 = (A + 1) - (A - 1) * cos_w0 - s
    else:
        raise ValueError("unknown filter type: %s" % kind)

    return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def magnitude_db(coeffs, f, sr):
    """|H(f)| in dB for one section, evaluated on the unit circle."""
    b0, b1, b2, a1, a2 = coeffs
    w = 2.0 * math.pi * f / sr
    c1, s1 = math.cos(-w), math.sin(-w)
    c2, s2 = math.cos(-2 * w), math.sin(-2 * w)
    nr, ni = b0 + b1 * c1 + b2 * c2, b1 * s1 + b2 * s2
    dr, di = 1.0 + a1 * c1 + a2 * c2, a1 * s1 + a2 * s2
    num = math.hypot(nr, ni)
    den = math.hypot(dr, di)
    if den == 0.0:
        return 0.0
    return 20.0 * math.log10(max(num / den, 1e-12))


def process(coeffs, samples):
    """Direct Form I, returned as a new list. O(n)."""
    b0, b1, b2, a1, a2 = coeffs
    x1 = x2 = y1 = y2 = 0.0
    out = []
    push = out.append
    for x in samples:
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        push(y)
        x2, x1 = x1, x
        y2, y1 = y1, y
    return out
