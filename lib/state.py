#!/usr/bin/env python3
"""State layout, measurement merging and migration for omarchy-eq.

Layout (XDG_STATE_HOME, so measurements never sit beside installed code -- the
old $XDG_DATA_HOME/omarchy-eq collided with install.sh's lib directory):

    ~/.local/state/omarchy-eq/
      config.json                  prefs, active device
      devices/<device-key>/
        response.json              runs[] + merged, per-point validity
        profiles.json              derived + imported profiles

A measurement is stored as a list of *runs*, one per microphone position,
because a single position cannot distinguish the speaker from the room. Each
run's points are already the median of several repeats. merge() then keeps only
what the runs agree on: a point that moves more than CONSISTENCY_DB between
positions is interference geometry, not the driver, and gets dropped.
"""
import json
import os
import re
import statistics
import sys
import time

SCHEMA = 1
SNR_MIN = 10.0           # dB above the noise floor to count as signal
CONSISTENCY_DB = 6.0     # max spread between positions before a point is junk


def _base(var, default):
    return os.environ.get(var) or os.path.expanduser(default)


def state_root():
    return os.path.join(_base("XDG_STATE_HOME", "~/.local/state"), "omarchy-eq")


def legacy_root():
    return os.path.join(_base("XDG_DATA_HOME", "~/.local/share"), "omarchy-eq")


def device_key(sink):
    """Filesystem-safe key for a PipeWire sink name."""
    k = re.sub(r"[^A-Za-z0-9._-]", "_", sink or "default").strip("_")
    return k[:120] or "default"


def device_dir(sink):
    return os.path.join(state_root(), "devices", device_key(sink))


def response_path(sink):
    return os.path.join(device_dir(sink), "response.json")


def profiles_path(sink):
    return os.path.join(device_dir(sink), "profiles.json")


def config_path():
    return os.path.join(state_root(), "config.json")


def _read(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)          # atomic: never leave a half-written state


# ---- measurements -----------------------------------------------------------
def blank(sink, source):
    return {"schema": SCHEMA, "sink": sink, "source": source, "runs": [],
            "merged": {}}


def parse_run(path):
    """Read a run file of '<freq> <db> <snr>' lines written by cmd_measure."""
    points = {}
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 3 or line.startswith("#"):
                continue
            f, db, snr = parts[0], float(parts[1]), float(parts[2])
            points[f] = {"db": db, "snr": snr, "valid": snr >= SNR_MIN}
    return points


def merge(runs):
    """Collapse runs into one trusted curve, marking what cannot be trusted.

    A point survives only if at least one run measured it above the noise
    floor, and -- when several runs did -- if they agree. Disagreement between
    microphone positions is the signature of comb filtering: the null moves,
    the driver does not.
    """
    freqs = sorted({f for r in runs for f in r.get("points", {})}, key=float)
    out = {}
    for f in freqs:
        vals = [r["points"][f]["db"] for r in runs
                if f in r.get("points", {}) and r["points"][f]["valid"]]
        if not vals:
            # "Below the noise floor" is not the same kind of ignorance as
            # "the positions disagree". A disagreement means the value is
            # unknown. A floor-limited reading means the output is at most this
            # loud -- which is exactly the evidence that a driver reproduces
            # nothing down here, so keep the number as an upper bound.
            raw = [r["points"][f]["db"] for r in runs if f in r.get("points", {})]
            out[f] = {"valid": False, "reason": "below noise floor",
                      "floor_limited": True}
            if raw:
                out[f]["db"] = round(statistics.median(raw), 2)
        elif len(vals) == 1:
            out[f] = {"db": round(vals[0], 2), "valid": True,
                      "confidence": "single", "spread": 0.0}
        else:
            spread = max(vals) - min(vals)
            if spread > CONSISTENCY_DB:
                out[f] = {"valid": False, "spread": round(spread, 2),
                          "reason": "positions disagree by %.1f dB" % spread}
            else:
                out[f] = {"db": round(statistics.median(vals), 2), "valid": True,
                          "confidence": "high", "spread": round(spread, 2)}
    return out


def add_run(path, sink, source, position, runfile, volume=""):
    data = _read(path) or blank(sink, source)
    data["sink"], data["source"] = sink, source
    data.setdefault("runs", []).append({
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "position": position, "volume": volume,
        "points": parse_run(runfile)})
    data["merged"] = merge(data["runs"])
    _write(path, data)
    return data


def valid_points(data):
    """[(freq, db)] for points the measurement actually trusts."""
    return sorted(((float(f), p["db"])
                   for f, p in data.get("merged", {}).items() if p.get("valid")),
                  key=lambda x: x[0])


def floor_limited_points(data):
    """[(freq, db)] for points that never rose above the noise floor.

    The level is an upper bound, not a measurement. Useful only for deciding
    where the driver stops reproducing -- never for computing a band level.
    """
    return sorted(((float(f), p["db"])
                   for f, p in data.get("merged", {}).items()
                   if p.get("floor_limited") and "db" in p),
                  key=lambda x: x[0])


def export_txt(data):
    """Flat two-column form, for docs and for sharing a curve.

    Invalid points are written as `nan` rather than a plausible-looking number:
    the whole point of the merge is to say 'we do not know'.
    """
    lines = ["# omarchy-eq response -- sink=%s source=%s runs=%d"
             % (data.get("sink", "?"), data.get("source", "?"),
                len(data.get("runs", [])))]
    for f, p in sorted(data.get("merged", {}).items(), key=lambda x: float(x[0])):
        lines.append("%s %s" % (f, ("%.2f" % p["db"]) if p.get("valid") else "nan"))
    return "\n".join(lines)


def summary(data):
    m = data.get("merged", {})
    good = [f for f, p in m.items() if p.get("valid")]
    bad = [(f, p.get("reason", "?")) for f, p in m.items() if not p.get("valid")]
    out = ["runs: %d   usable points: %d/%d"
           % (len(data.get("runs", [])), len(good), len(m))]
    for f, why in sorted(bad, key=lambda x: float(x[0])):
        out.append("  dropped %6s Hz  (%s)" % (f, why))
    return "\n".join(out)


def analysis_lines(profiles_data):
    """Clamp/note warnings from the last `generate`, as plain lines.

    `generate` prints these once, to whatever terminal happened to run it --
    easy to miss, and gone the moment that scrollback is lost. `doctor` reads
    them back out of profiles.json so a clamped correction stays visible.
    """
    a = (profiles_data or {}).get("analysis") or {}
    lines = ["note: %s" % n for n in a.get("notes", [])]
    if a.get("pinned"):
        lines.append(
            "clamped: %s -- measurement is more extreme than this tool will "
            "correct. Re-measure from a second position if you have not "
            "already (omarchy-eq measure --again)." % ", ".join(a["pinned"]))
    return lines


# ---- migration --------------------------------------------------------------
def migrate(sink, is_builtin=True):
    """One-shot move of the pre-schema files. Never clobbers newer state.

    Only ever targets the built-in speakers. Pre-v2 state had no notion of a
    device, but it was always a measurement of the laptop's own drivers -- so
    copying it into whatever device happened to be touched first would give a
    pair of headphones the laptop's highpass and correction curve.
    """
    if not is_builtin:
        return []
    old_resp = os.path.join(legacy_root(), "response.txt")
    old_prof = os.path.join(legacy_root(), "profiles.json")
    moved = []
    if os.path.exists(old_resp) and not os.path.exists(response_path(sink)):
        pts = {}
        with open(old_resp) as fh:
            legacy_lines = fh.readlines()
        for line in legacy_lines:
            if line.startswith("#") or not line.split():
                continue
            p = line.split()
            if len(p) >= 2 and p[1] != "nan":
                pts[p[0]] = {"db": float(p[1]), "snr": 99.0, "valid": True}
        data = blank(sink, "")
        data["runs"] = [{"started": "migrated", "position": "legacy",
                         "volume": "", "points": pts}]
        data["merged"] = merge(data["runs"])
        _write(response_path(sink), data)
        moved.append(response_path(sink))
    if os.path.exists(old_prof) and not os.path.exists(profiles_path(sink)):
        prof = _read(old_prof)
        if prof:
            _write(profiles_path(sink), prof)
            moved.append(profiles_path(sink))
    return moved


def context(spec=None):
    """Everything a subcommand needs about one device, in a single process.

    `ab` used to spend four python startups per invocation -- two for paths, one
    for migration, one for the descriptions -- which is a lot for something bound
    to a hotkey and evaluated repeatedly by the menu's guard batch.
    """
    import devices as devmod
    import describe

    devs = devmod.listing()
    if spec in (None, "", "active"):
        dev = devmod.active(devs)
    elif spec == "builtin":
        dev = devmod.builtin(devs)
    else:
        dev = devmod.find(devs, spec)
    if dev is None:
        return ["error\tno such output device: %s" % spec]

    sink = dev["name"]
    rows = ["device\tname\t%s" % sink,
            "device\ttag\t%s" % dev["tag"],
            "device\tlabel\t%s" % dev["description"],
            "device\tkind\t%s" % dev["kind"],
            "device\tmeasurable\t%d" % (1 if dev["measurable"] else 0),
            "device\tcodec\t%s" % dev.get("codec", "")]
    for m in migrate(sink, dev["kind"] == "builtin"):
        rows.append("migrated\t%s" % m)
    rows += ["path\tdir\t%s" % device_dir(sink),
             "path\tresponse\t%s" % response_path(sink),
             "path\tprofiles\t%s" % profiles_path(sink)]
    prof = _read(profiles_path(sink), {}) or {}
    for key, p in prof.get("profiles", {}).items():
        rows.append("profile\t%s\t%s" % (key, describe.summarise(p)))
    data = _read(response_path(sink))
    if data:
        good = sum(1 for v in data.get("merged", {}).values() if v.get("valid"))
        rows.append("measurement\t%d\t%d" % (len(data.get("runs", [])), good))
    return rows


def _profile_count(sink):
    prof = _read(profiles_path(sink), {}) or {}
    return len(prof.get("profiles", {}))


def render_args():
    """Render arguments for every present device that has profiles.

    Devices that are not connected are skipped: a filter chain pinned to a
    target.object that does not exist just sits there doing nothing, and
    cluttering the graph with chains for headphones in a drawer helps no one.
    Reconnect and re-run apply.
    """
    import devices as devmod
    rows = []
    for dev in devmod.listing():
        if _profile_count(dev["name"]):
            rows.append("\t".join([dev["tag"], dev["name"], dev["description"],
                                    profiles_path(dev["name"])]))
    return rows


def devices_status():
    """One row per present device, plus whatever we know about it."""
    import devices as devmod
    default = devmod.default_sink()
    devs = devmod.listing()
    act = devmod.active(devs, default)
    rows = []
    for dev in devs:
        data = _read(response_path(dev["name"])) or {}
        runs = len(data.get("runs", []))
        good = sum(1 for v in data.get("merged", {}).values() if v.get("valid"))
        rows.append("\t".join([
            "*" if act and dev["name"] == act["name"] else " ",
            dev["tag"], dev["kind"], "1" if dev["measurable"] else "0",
            str(runs), str(good), str(_profile_count(dev["name"])),
            dev["description"], dev.get("codec", "")]))
    return rows


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "path":
        kind, sink = sys.argv[2], sys.argv[3]
        print({"response": response_path, "profiles": profiles_path}[kind](sink))
    elif cmd == "dir":
        print(device_dir(sys.argv[2]))
    elif cmd == "add-run":
        sink, source, position, runfile, volume = sys.argv[2:7]
        print(summary(add_run(response_path(sink), sink, source, position,
                              runfile, volume)))
    elif cmd == "export":
        print(export_txt(_read(sys.argv[2], {})))
    elif cmd == "summary":
        print(summary(_read(sys.argv[2], {})))
    elif cmd == "analysis":
        print("\n".join(analysis_lines(_read(sys.argv[2], {}))))
    elif cmd == "context":
        print("\n".join(context(sys.argv[2] if len(sys.argv) > 2 else None)))
    elif cmd == "render-args":
        print("\n".join(render_args()))
    elif cmd == "devices":
        print("\n".join(devices_status()))
    elif cmd == "migrate":
        for p in migrate(sys.argv[2]):
            print("migrated: %s" % p)
    else:
        raise SystemExit(
            "usage: state.py {path|dir|context|render-args|devices|add-run|"
            "export|summary|analysis|migrate}")


if __name__ == "__main__":
    main()
