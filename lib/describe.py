#!/usr/bin/env python3
"""One-line summaries of every profile, as '<key>\\t<description>' rows.

A single process for the whole file: `ab` used to fork python once per profile
just to build these strings.
"""
import json
import math
import sys


def summarise(profile):
    bits = []
    for f in profile["filters"]:
        c = f["control"]
        if f["label"] == "linear":
            bits.append("pre%+.1fdB" % (20.0 * math.log10(max(float(c.get("mult", 1.0)), 1e-9))))
        elif "Gain" in c:
            bits.append("%+g@%g" % (c["Gain"], c["Freq"]))
        else:
            bits.append("HPF%gHz" % c["Freq"])
    return "%s | %s" % (profile.get("description", ""), " ".join(bits))


def main():
    data = json.load(open(sys.argv[1]))
    for key, p in data.get("profiles", {}).items():
        print("%s\t%s" % (key, summarise(p)))


if __name__ == "__main__":
    main()
