#!/usr/bin/env python3
"""Cross-check installed profiles against the machine they will run on.

Every failure mode here is one the richer formats introduced, and all of them
are quiet -- a profile stays in profiles.json, keeps its name, keeps showing up
in the menu, and simply stops being the thing it claims to be:

  a convolution profile whose impulse response has been deleted. The chain
  fails to instantiate and the sink never appears, which presents as "that
  profile stopped working" rather than as a missing file.

  a curve fitted at sample rates the graph no longer uses. Changing
  clock.allowed-rates is a deliberate act performed months apart from importing
  a preset, and nothing connects the two events for you. The preset still
  loads; it is just no longer the curve that was measured.

  a fit that was poor when it was made. `import` says so at the time, in a
  terminal that is long gone.

  a remembered profile that a later `generate` removed, so the output silently
  comes up somewhere other than where you left it.
"""
import os
import sys

import devices as devmod
import prefs
import state

POOR_FIT_DB = 3.0


def check_device(dev, rates):
    """Warning lines for one device. Empty means healthy."""
    sink = dev["name"]
    data = state._read(state.profiles_path(sink), {}) or {}
    profiles = data.get("profiles", {}) or {}
    out = []
    for key, prof in sorted(profiles.items()):
        where = "%s/%s" % (dev["tag"], key)
        if prof.get("format") == "convolution":
            path = prof.get("ir_file", "")
            if path and not os.path.exists(path):
                out.append("%s: impulse response is missing (%s) -- re-import "
                           "it, or the profile will not load" % (where, path))
        fitted = prof.get("fitted_rates")
        if fitted and rates and sorted(int(r) for r in fitted) != \
                sorted(int(r) for r in rates):
            out.append("%s: fitted for %s Hz, but the graph now allows %s Hz -- "
                       "re-import to refit"
                       % (where, ",".join(str(int(r)) for r in fitted),
                          ",".join(str(int(r)) for r in rates)))
        err = prof.get("fit_error_db")
        if err is not None and err > POOR_FIT_DB:
            out.append("%s: fitted curve is %.1f dB off at worst -- try "
                       "'--bands 16', or the ParametricEQ version" % (where, err))

    want = prefs.remembered(sink)
    if want and want != "flat" and want not in profiles:
        out.append("%s: remembered profile '%s' no longer exists"
                   % (dev["tag"], want))
    return out


def report():
    rates = devmod.allowed_rates()
    lines = []
    for dev in devmod.listing():
        lines += check_device(dev, rates)
    return lines or ["all profiles for connected outputs look healthy"]


def main():
    print("\n".join(report()))


if __name__ == "__main__":
    main()
