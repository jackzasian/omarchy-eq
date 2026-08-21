#!/usr/bin/env python3
"""Decide which EQ profile an output should be using right now. Pure stdlib.

The watcher's judgement lives here; the acting lives in the shell script. That
split is deliberate -- `omarchy-eq autoswitch once` has to be safe to run over
and over, because PipeWire emits an event for our own `set-default-sink` and the
watcher would otherwise chase its own tail. Keeping the decision in one pure-ish
function makes "is this a no-op?" a thing that can be answered and tested rather
than hoped for.

The order of preference, most specific first:

  1. what you last chose on this device, if that profile still exists. This is
     the one that matters: plugging the same headphones in twice should not need
     the same correction twice.
  2. `voice`, when the device is a Bluetooth headset that has switched to its
     call profile. That link is 8 or 16 kHz mono -- a curve derived for A2DP is
     correcting treble that is not being transmitted.
  3. `balanced`, or whatever single profile exists.
  4. nothing: leave the output flat and say why.

A device with no profiles at all is the interesting case, and what happens is a
setting. Left alone, it stays flat. With auto-setup on, its name is looked up in
the AutoEQ catalogue and a preset installed if -- and only if -- the name matches
one product unambiguously. See autoeq.match_device for how hard that refuses.
"""
import sys

import devices as devmod
import prefs
import state

FLAT = "flat"
# Preference order when nothing has been chosen for a device yet.
DEFAULT_ORDER = ("balanced", "music", "voice")
NARROWBAND_ORDER = ("voice", "balanced")


def _profiles(sink):
    data = state._read(state.profiles_path(sink), {}) or {}
    return data.get("profiles", {}) or {}


def eq_sink(tag, key):
    return "eq_%s_%s" % (tag, key)


def choose(dev, profiles, remembered):
    """(profile_key, reason). `flat` means leave the hardware sink alone."""
    if remembered == FLAT:
        return FLAT, "you last chose flat here"
    if remembered and remembered in profiles:
        return remembered, "you last chose '%s' here" % remembered
    if remembered:
        # The profile was renamed or regenerated away. Say so rather than
        # silently landing somewhere else.
        reason = "'%s' no longer exists" % remembered
    else:
        reason = "no choice recorded yet"

    if not profiles:
        return FLAT, reason + "; this output has no profiles"
    order = NARROWBAND_ORDER if dev.get("narrowband") else DEFAULT_ORDER
    for key in order:
        if key in profiles:
            extra = (" (call profile: 16 kHz mono, so the wideband curves do "
                     "not apply)" if dev.get("narrowband") else "")
            return key, "%s; defaulting to '%s'%s" % (reason, key, extra)
    key = sorted(profiles)[0]
    return key, "%s; defaulting to '%s'" % (reason, key)


def decide(spec=None, current_default=None):
    """Rows describing what should happen, for the shell side to act on."""
    devs = devmod.listing()
    if not devs:
        return ["error\tno output devices"]
    default = (current_default if current_default is not None
               else devmod.default_sink())
    if spec in (None, "", "active"):
        dev = devmod.active(devs, default)
    else:
        dev = devmod.find(devs, spec)
    if dev is None:
        return ["error\tno such output device: %s" % spec]

    sink = dev["name"]
    profiles = _profiles(sink)
    conf = prefs.autoswitch()
    key, reason = choose(dev, profiles, prefs.remembered(sink))
    target = sink if key == FLAT else eq_sink(dev["tag"], key)

    if key == FLAT and not profiles:
        if dev["measurable"]:
            action = "none"
            reason += " -- measure it with: omarchy-eq calibrate"
        elif conf.get("fetch"):
            action = "setup"           # try the AutoEQ catalogue
        else:
            action = "none"
            reason += (" -- import one, or turn on auto-setup: "
                       "omarchy-eq autoswitch enable --fetch")
    elif default == target:
        action = "none"
        reason = "already on '%s'" % key
    else:
        action = "switch"

    return ["device\tname\t%s" % sink,
            "device\ttag\t%s" % dev["tag"],
            "device\tlabel\t%s" % dev["description"],
            "device\tkind\t%s" % dev["kind"],
            "device\tnarrowband\t%d" % (1 if dev.get("narrowband") else 0),
            "action\t%s" % action,
            "profile\t%s" % key,
            "target\t%s" % target,
            "reason\t%s" % reason]


def setup(spec=None):
    """Find and install an AutoEQ preset for a device that has none.

    Only ever called when the user turned auto-setup on. Returns rows; an
    `error` row means "leave it flat", not "stop the watcher".
    """
    import importer

    devs = devmod.listing()
    dev = (devmod.active(devs) if spec in (None, "", "active")
           else devmod.find(devs, spec))
    if dev is None:
        return ["error\tno such output device: %s" % spec]
    if _profiles(dev["name"]):
        return ["error\t'%s' already has profiles" % dev["description"]]

    import autoeq
    try:
        hit = autoeq.match_device(dev["description"])
    except SystemExit as exc:
        return ["error\t%s" % exc]
    except Exception as exc:                      # network, parse, anything
        return ["error\tAutoEQ lookup failed: %s" % exc]
    if not hit:
        return ["error\tno confident AutoEQ match for '%s'" % dev["description"]]

    score, entry = hit
    devdir = state.device_dir(dev["name"])
    key = importer.slug(entry["name"]) or "autoeq"
    try:
        tmp = autoeq.download(entry, "%s/downloads" % devdir, "parametric")
        profile, notes = importer.build_profile(
            tmp, devdir, key, devmod.allowed_rates())
    except SystemExit as exc:
        return ["error\t%s" % exc]
    except Exception as exc:
        return ["error\tcould not fetch preset: %s" % exc]

    profile["source"] = "autoeq"
    profile["description"] = "AutoEQ: %s" % autoeq.label(entry)
    importer.install(state.profiles_path(dev["name"]), key, profile)
    # Not pinned: the watcher chose this, not the user. A later manual switch
    # takes precedence and auto-setup never overrides it.
    prefs.remember(dev["name"], key, pinned=False)
    rows = ["installed\t%s\t%s" % (key, autoeq.label(entry)),
            "match\t%.0f" % score]
    rows += ["note\t%s" % n for n in notes]
    return rows


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "decide"
    spec = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "decide":
        print("\n".join(decide(spec)))
    elif cmd == "setup":
        print("\n".join(setup(spec)))
    else:
        raise SystemExit("usage: autoswitch.py {decide|setup} [device]")


if __name__ == "__main__":
    main()
