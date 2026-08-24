#!/usr/bin/env python3
"""Everything the bar widget needs, in one JSON document. Pure stdlib.

The Quickshell panel used to ask four separate questions -- `ab status`,
`ab list`, `autoswitch status` and `route playing` -- on a timer, forever. Each
was a bash process that started python and shelled out to pactl, so the bar cost
three process trees every eight seconds while sitting still, and still showed an
answer that could be eight seconds stale.

They are one question. All four answers come from the same `devices.listing()`
snapshot, and taking that snapshot once is both cheaper and more consistent:
the old way could interleave a device change between two of the four calls and
render a profile list belonging to a device the status line had already stopped
describing.

Nothing here re-derives anything. It composes the modules that already own each
answer -- devices, state, prefs, routing -- so there is still exactly one
implementation of "which device is active" and of "what am I hearing".
"""
import json
import sys

import describe
import devices as devmod
import prefs
import routing
import state


def snapshot(spec=None):
    devs = devmod.listing()
    if spec in (None, "", "active"):
        dev = devmod.active(devs)
    elif spec == "builtin":
        dev = devmod.builtin(devs)
    else:
        dev = devmod.find(devs, spec)
    if dev is None:
        return {"error": "no such output device: %s" % spec}

    sink = dev["name"]
    profiles = [{"key": "flat", "filters": "",
                 "description": "no EQ - raw output (reference)"}]
    stored = (state._read(state.profiles_path(sink), {}) or {}).get("profiles", {})
    for key, p in stored.items():
        # The " | <filters>" tail `ab list` prints is for a terminal. Split it
        # off here rather than in QML, so the panel is not parsing a display
        # format it does not own.
        summary = describe.summarise(p)
        head, sep, filters = summary.partition(" | ")
        profiles.append({"key": key,
                         "description": head.strip(),
                         "filters": filters.strip() if sep else ""})

    default = devmod.default_sink()
    prefix = "eq_%s_" % dev["tag"]
    on_default = default[len(prefix):] if default.startswith(prefix) else "flat"

    rows = routing.playing(devs)
    streams = []
    for row in rows:
        parts = row.split("\t")
        if len(parts) >= 4:
            streams.append({"app": parts[1], "profile": parts[2],
                            "playing": parts[3] == "1"})

    auto = prefs.autoswitch()
    return {
        # What you are actually hearing, which is not the default sink whenever
        # per-stream routing is doing its job. See routing.effective.
        "active": routing._effective_from_rows(rows, on_default),
        "default_profile": on_default,
        "device": {"name": sink, "tag": dev["tag"], "label": dev["description"],
                   "kind": dev["kind"], "measurable": bool(dev["measurable"])},
        "remembered": prefs.remembered(sink) or "",
        "profiles": profiles,
        "autoswitch": bool(auto.get("enabled")),
        "streams": streams,
    }


def main():
    spec = sys.argv[1] if len(sys.argv) > 1 else None
    json.dump(snapshot(spec), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
