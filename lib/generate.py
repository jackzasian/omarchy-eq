#!/usr/bin/env python3
"""Derive EQ profiles from a measured speaker response.

Design rule: correct only broad, physically plausible trends. A near-field
measurement taken with a laptop's own microphone is full of narrow nulls caused
by comb filtering and mic placement -- inverting those would wreck the sound.
So the curve is smoothed first and every correction is clamped.

Input : response.json (preferred; carries per-point validity) or the legacy
        flat "<freq_hz> <db>" text form, where `nan` marks an unusable point.
Output: profiles.json
"""
import json
import math
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

MUSIC_AIR = 1.0            # dB of extra top end the "music" profile adds


def load(path):
    """Measured points, excluding everything the measurement flagged unusable."""
    return load_all(path)[0]


def load_all(path):
    """(trusted points, floor-limited points).

    The second list is where the speaker was too quiet to measure. Those levels
    are upper bounds, so they say nothing about *how* loud a band is -- but they
    do say a band is not being reproduced, which is what the highpass needs.
    """
    if path.endswith(".json"):
        import state
        with open(path) as fh:
            data = json.load(fh)
        return state.valid_points(data), state.floor_limited_points(data)
    pts = []
    with open(path) as fh:
        lines = fh.readlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f, d = line.split()[:2]
        try:
            fv, dv = float(f), float(d)
        except ValueError:
            continue
        if math.isnan(dv) or math.isinf(dv):
            continue
        pts.append((fv, dv))
    return sorted(pts), []


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


def analyse(pts, floor_limited=()):
    # width=3 (~1 octave at 1/3-octave spacing): enough to reject single-point
    # artifacts without smearing a real resonance across neighbouring bands.
    s = smooth(pts, width=3)
    ref = level(s, 500, 4000)
    if ref is None:
        raise SystemExit("measurement has no usable 500-4000Hz data")

    notes, pinned = [], []

    # Highpass: highest low frequency still ROLLOFF_DB below midband.
    #
    # Floor-limited bands count here. They were dropped from `pts` because their
    # level is unknowable, but "we could not hear it over the noise floor" is
    # itself proof the driver is not reproducing that band -- and excluding them
    # left the corner at its minimum on a speaker with no bass at all.
    corner = HPF_MIN
    for f, d in list(s) + [(f, d) for f, d in floor_limited]:
        if f < 500 and d < ref - ROLLOFF_DB:
            corner = max(corner, f)
    if corner >= HPF_MAX:
        pinned.append("highpass corner")
    corner = clamp(corner, HPF_MIN, HPF_MAX)

    # Box resonance: strongest peak in the low-mid region.
    lowmid = [(f, d) for f, d in s if 300 <= f <= 1500]
    rf, rdb = max(lowmid, key=lambda p: p[1]) if lowmid else (750.0, ref)
    raw_res = (rdb - ref) * STRENGTH
    if raw_res >= MAX_CUT:
        pinned.append("resonance cut")
    resonance = clamp(raw_res, 0.0, MAX_CUT)

    # Presence: 2-5kHz deficit relative to midband (speech intelligibility).
    pres = level(s, 2000, 5000)
    raw_pres = (ref - pres) * STRENGTH if pres is not None else 0.0
    if raw_pres >= MAX_BOOST:
        pinned.append("presence lift")
    presence = clamp(raw_pres, 0.0, MAX_BOOST)

    # Top end: broad tilt above 8kHz.
    #
    # An internal microphone has a large resonance of its own up here, and
    # nothing in a single measurement can separate it from the speaker. If the
    # top octaves read *hotter* than the midband, that is not a laptop speaker
    # -- no small sealed driver is brighter than it is midrangey -- so it is the
    # mic, and "correcting" it would cut real treble. Refuse rather than guess.
    hi = level(s, 8000, 20000)
    if hi is None:
        shelf = 0.0
    elif hi > ref:
        shelf = 0.0
        notes.append("8k+ measured above midband: treated as microphone "
                     "resonance, HF shelf disabled")
    else:
        raw_shelf = (ref - hi) * STRENGTH
        if raw_shelf >= MAX_SHELF:
            pinned.append("HF shelf")
        shelf = clamp(raw_shelf, 0.0, MAX_SHELF)

    return dict(ref=round(ref, 2), corner=round(corner), res_freq=round(rf),
                res_cut=round(resonance, 1), presence=round(presence, 1),
                shelf=round(shelf, 1), points=len(pts),
                pinned=pinned, notes=notes)


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
        # "adds air" means *more* top end than balanced, so start from the
        # measured shelf and add to it. This used to negate the measurement,
        # which gave the music profile less treble than the neutral one and gave
        # a speaker that measured bright the most extra treble of all.
        "music":    {"description": "music - keeps warmth, adds air",
                     "filters": chain(clamp(c * 0.9, HPF_MIN, HPF_MAX),
                                      clamp(cut * 0.85, 0, MAX_CUT),
                                      clamp(pres * 0.85, 0, MAX_BOOST),
                                      clamp(shelf + MUSIC_AIR, -MAX_SHELF, MAX_SHELF),
                                      warmth=(clamp(c * 2.0, 200, 600), 2.5))},
    }


def main():
    pts, floor_limited = load_all(sys.argv[1])
    if len(pts) < 8:
        raise SystemExit("need at least 8 usable measurement points, have %d -- "
                         "re-run: omarchy-eq measure" % len(pts))
    a = analyse(pts, floor_limited)
    existing = {}
    try:
        with open(sys.argv[2]) as fh:
            existing = json.load(fh).get("profiles", {})
    except (OSError, ValueError):
        pass
    # Imported presets live alongside derived ones; regenerating must not drop
    # them.
    keep = {k: v for k, v in existing.items() if v.get("source") == "import"}
    out = {"analysis": a, "profiles": dict(profiles(a), **keep)}
    with open(sys.argv[2], "w") as fh:
        json.dump(out, fh, indent=2)

    print("usable points    %d" % a["points"])
    print("midband ref      %.1f dB" % a["ref"])
    print("highpass corner  %d Hz" % a["corner"])
    print("resonance        %d Hz, cutting %.1f dB" % (a["res_freq"], a["res_cut"]))
    print("presence lift    %.1f dB @3kHz" % a["presence"])
    print("HF shelf         %+.1f dB @9kHz" % a["shelf"])
    for n in a["notes"]:
        print("note: %s" % n)
    if a["pinned"]:
        # A parameter sitting on its clamp means the measurement ran off the end
        # of what this tool is willing to correct -- the user should know the
        # number is a limit, not a result.
        print("\nwarning: %s hit the safety clamp -- the measurement is more "
              "extreme than\n         this tool will correct. Re-measure from a "
              "second position\n         (omarchy-eq measure --again) if you have "
              "not already." % ", ".join(a["pinned"]))


if __name__ == "__main__":
    main()
