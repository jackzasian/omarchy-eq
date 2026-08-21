#!/usr/bin/env python3
"""Fit an AutoEQ GraphicEQ curve onto a bank of biquads. Pure stdlib.

A GraphicEQ file is not a filter description -- it is an arbitrary target curve
sampled at ~127 log-spaced points:

    GraphicEQ: 20 -0.2; 21 -0.2; 22 -0.2; ...; 19871 -16.0

Nothing in PipeWire consumes that shape directly, so omarchy-eq used to reject
these files and tell you to fetch the parametric variant instead. That is a fine
answer right up until the only file you have is this one -- some sources publish
a GraphicEQ and nothing else, and a curve exported by hand from another tool is
almost always this shape.

So: fit it. Matching pursuit -- find where the residual is worst, add the one
filter that removes most of it, re-solve every gain, repeat. The result lands on
exactly the same biquads as every other profile, so the TUI can draw it and the
chain costs no more than an imported parametric preset.

Three things here were settled by measurement against real AutoEQ curves rather
than by taste, and each one is worth more than it looks:

  Re-fitting every round. Plain matching pursuit never revisits a filter it
  already placed, and the gains it picks in early rounds are wrong once later
  rounds change the residual. Filters in series add in dB, so with corners and Qs
  held fixed the optimal gains are an ordinary linear least-squares solve. Doing
  it eliminated gain-clamped filters outright: before, one or two filters per
  preset sat pinned at the +/-12 dB limit, which is the fit saying it wanted
  something it could not have.

  Fitting at the rates the graph may actually run at -- and only those. This is
  the big one, and it cuts both ways. A biquad's shape near Nyquist comes partly
  from bilinear-transform warping, and a single-rate fit will happily exploit
  that: fitted at 48 kHz alone, these presets came in under 1 dB of error there
  and then missed by 6 dB at 96 kHz. But padding the rate list "to be safe" is
  just as wrong, because every rate in it is a constraint the fit must satisfy --
  fitting for 44.1/48/96 when the graph only ever runs at 48 tripled the error at
  48. So the rate list is not a constant: it comes from PipeWire's own
  clock.allowed-rates, which is [ 48000 ] on a stock install and longer on a
  machine set up for bit-perfect playback. `fitted_rates` goes into the profile
  so `doctor` can notice if that setting changes afterwards.

  Bells only, no shelves. Shelf candidates seemed obviously right -- headphone
  curves are mostly a bass lift and a treble tilt, and AutoEQ's own parametric
  presets are built from LSC + HSC + peaks. Measured across three headphones they
  made the fit consistently *worse*, so they are not here.

This is an approximation and says so: `fit` reports the worst remaining error, so
a curve with a genuinely un-bell-shaped feature is visibly a bad fit rather than
a quiet one.
"""
import math
import re
import sys

import biquad

SR = 48000.0
DEFAULT_N = 10             # AutoEQ's own parametric presets use 10
# Q values to try per band. Wide enough for a broad tilt, narrow enough for the
# ear-canal resonance peaks that dominate in-ear curves.
QS = (0.5, 0.7, 1.0, 1.4, 2.0, 3.0, 4.5, 7.0)
# Fallback only. Real callers pass devices.allowed_rates(); see the docstring
# for why a longer list is not a safer one.
RATES = (48000.0,)
MAX_GAIN = 12.0            # per filter; beyond this a "fit" is a fantasy
SHAPE_REF_DB = 6.0         # gain the unit bell is measured at, see _shape
RIDGE = 1e-3               # see _refit

HEADER_RE = re.compile(r"^\s*GraphicEQ\s*:\s*(?P<body>.*)$", re.I | re.S)


def parse(text):
    """[(freq, gain_db)] from a GraphicEQ file, sorted and de-duplicated."""
    m = HEADER_RE.match(text.strip())
    body = m.group("body") if m else text
    pts = {}
    for chunk in body.replace("\n", " ").split(";"):
        parts = chunk.split()
        if len(parts) < 2:
            continue
        try:
            f, g = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if f > 0:
            pts[f] = g
    return sorted(pts.items())


def _weights(freqs):
    """Log-spacing weights, so a dense region does not dominate the fit.

    AutoEQ's own grid is close to log-spaced already, but a hand-made file is
    often not -- 31 fixed ISO bands plus a cluster of extra points around a
    problem area would otherwise pull the whole fit towards that cluster.
    """
    lg = [math.log10(f) for f in freqs]
    out = []
    for i in range(len(lg)):
        lo = lg[i] - lg[i - 1] if i else lg[1] - lg[0]
        hi = lg[i + 1] - lg[i] if i + 1 < len(lg) else lg[-1] - lg[-2]
        out.append((lo + hi) / 2.0)
    total = sum(out) or 1.0
    return [w / total for w in out]


def _shape(fc, q, freqs, rates, ref=SHAPE_REF_DB):
    """One filter's response per unit of gain, over every (rate, freq) pair.

    Flattened rate-major so it lines up with the stacked target and weights --
    fitting across rates is then the same least-squares problem, just taller.

    Measured at a real gain rather than derived analytically: a peaking filter's
    dB response is only approximately proportional to its gain, and taking the
    shape at a representative gain keeps the least-squares step honest.
    """
    ref = ref if abs(ref) > 0.05 else SHAPE_REF_DB
    out = []
    for sr in rates:
        co = biquad.design("peaking", fc, sr, q, ref)
        out.extend(biquad.magnitude_db(co, f, sr) / ref for f in freqs)
    return out


def _stack(values, n):
    """Repeat a per-frequency vector once per rate."""
    return list(values) * n


def _wrms(residual, weights):
    return math.sqrt(sum(w * r * r for r, w in zip(residual, weights)))


def _solve(a, b):
    """Gaussian elimination with partial pivoting. None if singular.

    Small and square -- there are never more than a few dozen filters -- so the
    O(n^3) is irrelevant and pulling in numpy for it would not be.
    """
    n = len(b)
    m = [list(row) + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        m[col], m[piv] = m[piv], m[col]
        inv = 1.0 / m[col][col]
        for r in range(col + 1, n):
            factor = m[r][col] * inv
            if factor:
                for c in range(col, n + 1):
                    m[r][c] -= factor * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        acc = m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))
        x[r] = acc / m[r][r]
    return x


def _refit(chosen, freqs, target, weights, rates, rounds=3):
    """Re-solve every gain at once, holding each filter's centre and Q.

    Sections in series add in dB, so the combined response is a linear
    combination of the individual shapes and the optimal gains fall out of the
    normal equations. The shapes drift slightly with gain, hence a few rounds:
    solve, redraw the shapes at the new gains, solve again.

    Ridge term: two filters landing on nearly the same frequency make the system
    near-singular, and the unregularised answer to that is a huge positive gain
    cancelling a huge negative one. Correct on paper, and the first thing to fall
    apart when anything about the graph changes.
    """
    if not chosen:
        return chosen
    for _ in range(rounds):
        shapes = [_shape(c["fc"], c["q"], freqs, rates, c["gain"])
                  for c in chosen]
        n = len(chosen)
        ata = [[sum(w * shapes[i][j] * shapes[k][j]
                    for j, w in enumerate(weights)) + (RIDGE if i == k else 0.0)
                for k in range(n)] for i in range(n)]
        atb = [sum(w * shapes[i][j] * target[j] for j, w in enumerate(weights))
               for i in range(n)]
        gains = _solve(ata, atb)
        if gains is None:
            break
        for c, g in zip(chosen, gains):
            c["gain"] = max(-MAX_GAIN, min(MAX_GAIN, g))
    return chosen


def _response(chosen, freqs, rates):
    """Combined dB response over every (rate, freq) pair, rate-major."""
    out = []
    for sr in rates:
        co = [biquad.design("peaking", c["fc"], sr, c["q"], c["gain"])
              for c in chosen]
        out.extend(sum(biquad.magnitude_db(c, f, sr) for c in co) for f in freqs)
    return out


def fit(points, n=DEFAULT_N, rates=RATES):
    """Fit up to `n` peaking filters to [(freq, gain_db)].

    Returns (filters, preamp_db, max_err_db, rms_err_db). The errors are the
    worst and the weighted-RMS deviation across *all* the sample rates, not just
    the nominal one -- a number that only held at 48 kHz would be a lie.
    """
    if not points:
        raise ValueError("no points to fit")
    freqs = [f for f, _ in points]
    nr = len(rates)
    target = _stack([g for _, g in points], nr)
    weights = [w / nr for w in _stack(_weights(freqs), nr)]

    chosen, residual = [], list(target)
    for _ in range(n):
        # Where is the curve worst wrong right now? That is where a filter buys
        # the most, and it is the whole idea behind matching pursuit. Fold the
        # rates together first: a filter is placed once and must serve all of
        # them, so the worst point is the worst *across* rates.
        folded = [max(abs(residual[k * len(freqs) + j]) for k in range(nr))
                  for j in range(len(freqs))]
        i = max(range(len(folded)), key=lambda j: folded[j])
        if folded[i] < 0.05:
            break                          # already inside the noise; stop early
        best = None
        for q in QS:
            shape = _shape(freqs[i], q, freqs, rates)
            denom = sum(w * s * s for s, w in zip(shape, weights))
            if denom <= 1e-12:
                continue
            gain = sum(w * r * s for r, s, w in zip(residual, shape, weights)) / denom
            gain = max(-MAX_GAIN, min(MAX_GAIN, gain))
            if abs(gain) < 0.02:
                continue
            trial = [{"fc": freqs[i], "q": q, "gain": gain}]
            got = _response(trial, freqs, rates)
            err = _wrms([r - a for r, a in zip(residual, got)], weights)
            if best is None or err < best[0]:
                best = (err, q, gain)
        if best is None:
            break
        _, q, gain = best
        chosen.append({"fc": freqs[i], "q": q, "gain": gain})
        # Every new filter changes what the earlier ones should have been.
        _refit(chosen, freqs, target, weights, rates)
        got = _response(chosen, freqs, rates)
        residual = [t - a for t, a in zip(target, got)]

    # A filter the re-fit has driven to nothing is just arithmetic and rounding.
    chosen = [c for c in chosen if abs(c["gain"]) >= 0.05]
    _refit(chosen, freqs, target, weights, rates)
    got = _response(chosen, freqs, rates)
    residual = [t - a for t, a in zip(target, got)]

    filters = [{"name": "f%d" % i, "label": "bq_peaking",
                "control": {"Freq": round(c["fc"], 2), "Q": round(c["q"], 3),
                            "Gain": round(c["gain"], 2)}}
               for i, c in enumerate(chosen)]

    # Preamp guards the output, not the fit: whatever the chain's true peak is
    # at any rate it might run at, pull it back below unity so a boosted band
    # cannot clip.
    peak = max(got) if got else 0.0
    preamp = -round(peak + 0.1, 2) if peak > 0 else 0.0
    max_err = max((abs(r) for r in residual), default=0.0)
    return filters, preamp, round(max_err, 2), round(_wrms(residual, weights), 2)


def main():
    with open(sys.argv[1]) as fh:
        pts = parse(fh.read())
    n = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_N
    if len(sys.argv) > 3:
        rates = tuple(float(r) for r in sys.argv[3].split(","))
    else:
        import devices
        rates = devices.allowed_rates()
    filters, preamp, max_err, rms = fit(pts, n, rates)
    print("# %d points -> %d peaking filters, preamp %+.1f dB "
          "(max err %.2f dB, rms %.2f dB at %s kHz)"
          % (len(pts), len(filters), preamp, max_err, rms,
             "/".join("%g" % (r / 1000.0) for r in rates)))
    for f in filters:
        c = f["control"]
        print("Filter: ON PK Fc %g Hz Gain %g dB Q %g"
              % (c["Freq"], c["Gain"], c["Q"]))


if __name__ == "__main__":
    main()
