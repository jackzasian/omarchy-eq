#!/usr/bin/env python3
"""Import an Equalizer APO / AutoEQ preset into profiles.json.

AutoEQ publishes "ParametricEQ.txt" files in Equalizer APO's syntax:

    Preamp: -6.8 dB
    Filter 1: ON PK Fc 105 Hz Gain -2.4 dB Q 0.70
    Filter 2: ON LSC Fc 105 Hz Gain 5.5 dB Q 0.70

Every one of those filter types is a biquad that PipeWire's filter-chain
already implements, so an import is a parse plus a name map -- no resampling
and no approximation.

Preamp becomes a `linear` node with mult = 10^(dB/20). It must be a real
broadband stage: folding it into the per-band gains is not equivalent, because
the preamp applies at every frequency and the band gains do not.
"""
import json
import os
import re
import sys

# Equalizer APO filter type -> PipeWire builtin label.
TYPES = {
    "PK": "bq_peaking", "PEQ": "bq_peaking", "MODAL": "bq_peaking",
    "LS": "bq_lowshelf", "LSC": "bq_lowshelf", "LSQ": "bq_lowshelf",
    "HS": "bq_highshelf", "HSC": "bq_highshelf", "HSQ": "bq_highshelf",
    "LP": "bq_lowpass", "LPQ": "bq_lowpass",
    "HP": "bq_highpass", "HPQ": "bq_highpass",
    "BP": "bq_bandpass", "NO": "bq_notch", "AP": "bq_allpass",
}
NO_GAIN = {"bq_lowpass", "bq_highpass", "bq_bandpass", "bq_notch", "bq_allpass"}

FILTER_RE = re.compile(
    r"^\s*Filter\s*\d*\s*:\s*(?P<state>ON|OFF)\s+(?P<type>[A-Za-z]+)"
    r"(?:\s+Fc\s+(?P<fc>[-\d.]+)\s*Hz)?"
    r"(?:\s+Gain\s+(?P<gain>[-\d.]+)\s*dB)?"
    r"(?:\s+Q\s+(?P<q>[-\d.]+))?", re.I)
PREAMP_RE = re.compile(r"^\s*Preamp\s*:\s*(?P<db>[-\d.]+)\s*dB", re.I)


def parse(text):
    """Return (filters, preamp_db, skipped)."""
    filters, preamp, skipped = [], 0.0, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("graphiceq"):
            raise SystemExit(
                "this is a GraphicEQ preset, not a parametric one.\n"
                "omarchy-eq imports Equalizer APO *parametric* files -- on "
                "AutoEQ,\ndownload the 'ParametricEQ.txt' variant instead.")
        m = PREAMP_RE.match(line)
        if m:
            preamp = float(m.group("db"))
            continue
        m = FILTER_RE.match(line)
        if not m:
            continue
        if m.group("state").upper() == "OFF":
            continue
        kind = m.group("type").upper()
        if kind not in TYPES:
            skipped.append(line)
            continue
        label = TYPES[kind]
        fc = float(m.group("fc") or 1000.0)
        q = float(m.group("q") or 0.707)
        control = {"Freq": fc, "Q": q}
        if label not in NO_GAIN:
            control["Gain"] = float(m.group("gain") or 0.0)
        filters.append({"name": "f%d" % len(filters), "label": label,
                        "control": control})
    return filters, preamp, skipped


def build(filters, preamp_db):
    chain = []
    if abs(preamp_db) > 0.01:
        chain.append({"name": "pre", "label": "linear",
                      "control": {"mult": round(10.0 ** (preamp_db / 20.0), 6),
                                  "add": 0.0}})
    chain.extend(filters)
    # Node names must stay unique within the graph once `pre` is prepended.
    for i, f in enumerate(chain):
        if f["name"] != "pre":
            f["name"] = "f%d" % i
    return chain


def summarise(filters, preamp_db):
    kinds = {}
    for f in filters:
        kinds[f["label"]] = kinds.get(f["label"], 0) + 1
    bits = ", ".join("%d x %s" % (n, k.replace("bq_", ""))
                     for k, n in sorted(kinds.items()))
    if abs(preamp_db) > 0.01:
        bits += ", preamp %+.1f dB" % preamp_db
    return bits


def main():
    src, profiles_path = sys.argv[1], sys.argv[2]
    name = (sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else
            os.path.splitext(os.path.basename(src))[0])
    name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "imported"

    with open(src) as fh:
        filters, preamp, skipped = parse(fh.read())
    if not filters:
        raise SystemExit("no usable filters found in %s" % src)

    try:
        with open(profiles_path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {"analysis": {}, "profiles": {}}
    data.setdefault("profiles", {})[name] = {
        "description": "imported from %s" % os.path.basename(src),
        "source": "import",
        "filters": build(filters, preamp),
    }
    os.makedirs(os.path.dirname(profiles_path) or ".", exist_ok=True)
    with open(profiles_path, "w") as fh:
        json.dump(data, fh, indent=2)

    print("imported '%s': %s" % (name, summarise(filters, preamp)))
    for s in skipped:
        print("  skipped unsupported: %s" % s)
    print("written: %s" % profiles_path)


if __name__ == "__main__":
    main()
