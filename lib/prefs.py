#!/usr/bin/env python3
"""User preferences: which profile each output should come up in. Pure stdlib.

Separate from profiles.json, which holds the *filters*. This file holds the
choices -- what you last picked for each device, and whether the watcher is
allowed to act. It is the memory that makes auto-switching feel like the
machine remembers your headphones rather than resetting them every time.

    ~/.local/state/omarchy-eq/config.json
    {
      "autoswitch": {"enabled": true, "fetch": false, "notify": true},
      "devices": {
        "<device-key>": {"profile": "music", "pinned": true}
      }
    }

`pinned` records that a human chose this profile, as opposed to the watcher
landing on it by default. A pinned choice is never overridden by auto-setup.
"""
import json
import os
import sys

import state

SCHEMA = 1
DEFAULT_AUTOSWITCH = {"enabled": False, "fetch": False, "notify": True}


def _read():
    try:
        with open(state.config_path()) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema", SCHEMA)
    data.setdefault("autoswitch", {})
    data.setdefault("devices", {})
    return data


def _write(data):
    path = state.config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


# ---- autoswitch settings ----------------------------------------------------
def autoswitch():
    conf = dict(DEFAULT_AUTOSWITCH)
    conf.update(_read().get("autoswitch") or {})
    return conf


def set_autoswitch(**kw):
    """Update only the keys given; unknown keys are refused, not stored.

    A typo that silently became a new key would read back as the default
    forever, which is the kind of setting bug that takes an hour to find.
    """
    bad = [k for k in kw if k not in DEFAULT_AUTOSWITCH]
    if bad:
        raise ValueError("unknown autoswitch setting: %s" % ", ".join(sorted(bad)))
    data = _read()
    conf = data.setdefault("autoswitch", {})
    conf.update({k: v for k, v in kw.items() if v is not None})
    _write(data)
    return autoswitch()


# ---- per-device choices -----------------------------------------------------
def device(sink):
    return dict(_read().get("devices", {}).get(state.device_key(sink)) or {})


def remembered(sink):
    """The profile this output should come up in, or None."""
    return device(sink).get("profile") or None


def remember(sink, profile, pinned=True):
    """Record a profile choice for one output.

    Called by `ab` on every switch, so the watcher restores whatever you were
    last listening to on these headphones rather than a fixed default.
    """
    data = _read()
    devs = data.setdefault("devices", {})
    entry = devs.setdefault(state.device_key(sink), {})
    entry["profile"] = profile
    # Auto-setup may write a profile without pinning it. Never let that clear a
    # pin a human set earlier.
    if pinned or "pinned" not in entry:
        entry["pinned"] = bool(pinned)
    _write(data)
    return entry


def forget(sink):
    data = _read()
    if data.get("devices", {}).pop(state.device_key(sink), None) is None:
        return False
    _write(data)
    return True


def all_devices():
    return dict(_read().get("devices", {}))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "remember":
        pinned = sys.argv[4] not in ("0", "false", "no") if len(sys.argv) > 4 \
            else True
        remember(sys.argv[2], sys.argv[3], pinned)
    elif cmd == "remembered":
        print(remembered(sys.argv[2]) or "")
    elif cmd == "forget":
        print("forgotten" if forget(sys.argv[2]) else "nothing stored")
    elif cmd == "autoswitch":
        conf = autoswitch()
        for k in sorted(conf):
            print("%s\t%s" % (k, "1" if conf[k] else "0"))
    elif cmd == "set-autoswitch":
        kw = {}
        for arg in sys.argv[2:]:
            k, _, v = arg.partition("=")
            kw[k] = v not in ("0", "false", "no", "off")
        for k in sorted(set_autoswitch(**kw)):
            pass
    else:
        raise SystemExit("usage: prefs.py {remember|remembered|forget|"
                         "autoswitch|set-autoswitch}")


if __name__ == "__main__":
    main()
