#!/usr/bin/env python3
"""Derive EQ profiles from a measured speaker response.

Design rule: correct only broad, physically plausible trends. A near-field
measurement taken with a laptop's own microphone is full of narrow nulls caused
by comb filtering and mic placement -- inverting those would wreck the sound.
So the curve is smoothed first and every correction is clamped.

Input : "<freq_hz> <db>" per line (from `omarchy-eq measure`)
Output: profiles.json
"""
import json
import statistics
import sys

# clamps -- deliberately conservative
HPF_MIN, HPF_MAX = 80.0, 300.0
MAX_CUT, MAX_BOOST, MAX_SHELF = 6.0, 6.0, 3.0
ROLLOFF_DB = 20.0          # how far below midband counts as "not reproduced"

# A single-position near-field measurement systematically overstates deviations:
# the mic sits centimetres from the driver, in the chassis, uncalibrated. Room
# correction software applies partial correction for the same reason. Fully
# inverting the measured curve here produces a harsh, over-EQ'd result.
STRENGTH = 0.65
TRIM = 0.4                 # discard this fraction of a band's lowest points


def load(path):
    pts = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f, d = line.split()[:2]
        pts.append((float(f), float(d)))
    return sorted(pts)


def smooth(pts, width=3):
    """Moving average over log-spaced points -- kills narrow artifacts."""
    out = []
    for i, (f, _) in enumerate(pts):
        lo, hi = max(0, i - width // 2), min(len(pts), i + width // 2 + 1)
        out.append((f, statistics.fmean(d for _, d in pts[lo:hi])))
    return out


def band(pts, lo, hi):
    return [d for f, d in pts if lo <= f <= hi]


def level(pts, lo, hi):
    """Representative level of a band, rejecting nulls.

    Interference nulls are sharp *downward* excursions that move with mic
    position, so the low tail of a band is untrustworthy while the upper part
    reflects real output. Discarding the bottom TRIM fraction before averaging
    keeps a null from dragging the estimate down and inflating corrections.
    """
    vals = sorted(band(pts, lo, hi))
    if not vals:
        return None
    keep = vals[int(len(vals) * TRIM):] or vals
    return statistics.fmean(keep)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def analyse(pts):
    # width=3 (~1 octave at 1/3-octave spacing): enough to reject single-point
    # artifacts without smearing a real resonance across neighbouring bands.
    s = smooth(pts, width=3)
    ref = level(s, 500, 4000)
    if ref is None:
        raise SystemExit("measurement has no usable 500-4000Hz data")

    # Highpass: highest low frequency still ROLLOFF_DB below midband.
    corner = HPF_MIN
    for f, d in s:
        if f < 500 and d < ref - ROLLOFF_DB:
            corner = max(corner, f)
    corner = clamp(corner, HPF_MIN, HPF_MAX)

    # Box resonance: strongest peak in the low-mid region.
    lowmid = [(f, d) for f, d in s if 300 <= f <= 1500]
    rf, rdb = max(lowmid, key=lambda p: p[1]) if lowmid else (750.0, ref)
    resonance = clamp((rdb - ref) * STRENGTH, 0.0, MAX_CUT)

    # Presence: 2-5kHz deficit relative to midband (speech intelligibility).
    pres = level(s, 2000, 5000)
    presence = clamp((ref - pres) * STRENGTH, 0.0, MAX_BOOST) if pres else 0.0

    # Top end: broad tilt above 8kHz.
    hi = level(s, 8000, 20000)
    shelf = clamp((ref - hi) * STRENGTH, -MAX_SHELF, MAX_SHELF) if hi is not None else 0.0

    return dict(ref=round(ref, 2), corner=round(corner), res_freq=round(rf),
                res_cut=round(resonance, 1), presence=round(presence, 1),
                shelf=round(shelf, 1))


def profiles(a):
    c, rf, cut, pres, shelf = (a["corner"], a["res_freq"], a["res_cut"],
                               a["presence"], a["shelf"])

    def chain(hpf, cut_g, pres_g, shelf_g, warmth=None):
        f = [{"name": "hp", "label": "bq_highpass",
              "control": {"Freq": round(hpf), "Q": 0.707}}]
        if warmth:
            f.append({"name": "wm", "label": "bq_peaking",
                      "control": {"Freq": round(warmth[0]), "Q": 1.0,
                                  "Gain": round(warmth[1], 1)}})
        if cut_g > 0.3:
            f.append({"name": "bx", "label": "bq_peaking",
                      "control": {"Freq": rf, "Q": 1.2, "Gain": -round(cut_g, 1)}})
        if pres_g > 0.3:
            f.append({"name": "pr", "label": "bq_peaking",
                      "control": {"Freq": 3000, "Q": 1.0, "Gain": round(pres_g, 1)}})
        if abs(shelf_g) > 0.3:
            f.append({"name": "hs", "label": "bq_highshelf",
                      "control": {"Freq": 9000, "Q": 0.707,
                                  "Gain": round(shelf_g, 1)}})
        return f

    return {
        "balanced": {"description": "measured correction - general use",
                     "filters": chain(c, cut, pres, shelf)},
        "voice":    {"description": "calls, video, podcasts - forward speech",
                     "filters": chain(clamp(c * 1.5, HPF_MIN, HPF_MAX),
                                      clamp(cut * 1.35, 0, MAX_CUT),
                                      clamp(pres * 1.4, 0, MAX_BOOST),
                                      clamp(shelf * 0.5, -MAX_SHELF, MAX_SHELF))},
        "music":    {"description": "music - keeps warmth, adds air",
                     "filters": chain(clamp(c * 0.9, HPF_MIN, HPF_MAX),
                                      clamp(cut * 0.85, 0, MAX_CUT),
                                      clamp(pres * 0.85, 0, MAX_BOOST),
                                      clamp(-shelf * 0.6 + 2.0, -MAX_SHELF, MAX_SHELF),
                                      warmth=(clamp(c * 2.0, 200, 600), 2.5))},
    }


def main():
    pts = load(sys.argv[1])
    if len(pts) < 8:
        raise SystemExit("need at least 8 measurement points")
    a = analyse(pts)
    out = {"analysis": a, "profiles": profiles(a)}
    json.dump(out, open(sys.argv[2], "w"), indent=2)
    print("midband ref      %.1f dB" % a["ref"])
    print("highpass corner  %d Hz" % a["corner"])
    print("resonance        %d Hz, cutting %.1f dB" % (a["res_freq"], a["res_cut"]))
    print("presence lift    %.1f dB @3kHz" % a["presence"])
    print("HF shelf         %+.1f dB @9kHz" % a["shelf"])


if __name__ == "__main__":
    main()
