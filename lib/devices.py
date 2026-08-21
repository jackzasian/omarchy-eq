#!/usr/bin/env python3
"""Enumerate and classify PipeWire output devices. Pure stdlib.

Not every output can be measured. The measurement plays a tone and records it
on the laptop's own microphone, so it only means anything when the sound is
actually in the room *and* arrives promptly:

  builtin/speaker   measurable -- this is what omarchy-eq was built for
  headphones        NOT measurable; the laptop mic cannot hear them. These get
                    EQ from an imported AutoEQ preset instead.
  stream            network sinks (Sonos, RAOP). The buffering means the tone
                    arrives long after the recording window, so a measurement
                    would be noise. Import-only.

Classification comes from device.form_factor and device.bus, which PipeWire
fills in from ALSA and BlueZ.
"""
import re
import subprocess
import sys

OURS = re.compile(r"^eq_")

FORM_FACTOR_KIND = {
    "internal": "builtin",
    "speaker": "speaker",
    "headset": "headphones",
    "headphone": "headphones",
    "hands-free": "headphones",
    "microphone": "headphones",
}
MEASURABLE = ("builtin", "speaker")


def _pactl(*args):
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True,
                              timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _tag(name, kind, props):
    """Short, stable, human-readable slug used in the EQ sink names."""
    if kind == "builtin":
        return "builtin"
    addr = props.get("api.bluez5.address", "")
    if addr:
        return "bt" + addr.replace(":", "")[-4:].lower()
    if props.get("device.bus") == "usb":
        return "usb"
    slug = re.sub(r"[^a-z0-9]+", "", name.split(".")[0].lower())
    return (slug or "dev")[:10]


def parse(text):
    """Parse `pactl list sinks` into device dicts."""
    out, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Sink #"):
            if cur:
                out.append(cur)
            cur = {"name": "", "description": "", "props": {}}
        elif cur is not None:
            if line.startswith("Name:"):
                cur["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                cur["description"] = line.split(":", 1)[1].strip()
            elif " = " in line:
                k, v = line.split(" = ", 1)
                cur["props"][k.strip()] = v.strip().strip('"')
    if cur:
        out.append(cur)

    devices, seen = [], {}
    for d in out:
        if not d["name"] or OURS.match(d["name"]):
            continue                      # never treat our own sinks as devices
        p = d["props"]
        ff = p.get("device.form_factor", "")
        kind = FORM_FACTOR_KIND.get(ff)
        if kind is None:
            if p.get("device.bus") == "bluetooth":
                kind = "headphones"       # unlabelled BT is far more often earbuds
            elif d["name"].startswith("alsa_output.pci"):
                kind = "builtin"
            elif d["name"].startswith("alsa_output"):
                kind = "speaker"
            else:
                kind = "stream"           # virtual / network sink
        tag = _tag(d["name"], kind, p)
        if tag in seen:                   # keep tags unique across devices
            seen[tag] += 1
            tag = "%s%d" % (tag, seen[tag])
        else:
            seen[tag] = 1
        devices.append({
            "name": d["name"],
            "description": d["description"] or d["name"],
            "kind": kind,
            "tag": tag,
            "measurable": kind in MEASURABLE,
            "codec": p.get("api.bluez5.codec", ""),
            "profile": p.get("api.bluez5.profile", ""),
        })
    return devices


def listing():
    return parse(_pactl("list", "sinks"))


def default_sink():
    return _pactl("get-default-sink").strip()


def find(devices, want):
    """Resolve a user-supplied name/tag/substring to exactly one device."""
    for d in devices:
        if want in (d["name"], d["tag"]):
            return d
    hits = [d for d in devices
            if want.lower() in d["description"].lower() or want in d["name"]]
    return hits[0] if len(hits) == 1 else None


def builtin(devices):
    for d in devices:
        if d["kind"] == "builtin":
            return d
    for d in devices:
        if d["measurable"]:
            return d
    return devices[0] if devices else None


def active(devices, default=None):
    """The device audio is currently going to, seeing through our own EQ sinks."""
    d = default if default is not None else default_sink()
    if d.startswith("eq_"):
        rest = d[3:]
        best = None
        for dev in devices:
            if rest.startswith(dev["tag"] + "_"):
                if best is None or len(dev["tag"]) > len(best["tag"]):
                    best = dev            # longest tag wins: bt50e6 before bt5
        if best:
            return best
    for dev in devices:
        if dev["name"] == d:
            return dev
    return builtin(devices)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    devs = listing()
    if cmd == "list":
        for d in devs:
            print("\t".join([d["tag"], d["name"], d["kind"],
                             "1" if d["measurable"] else "0", d["description"],
                             d["codec"]]))
    elif cmd == "active":
        a = active(devs)
        print(a["name"] if a else "")
    elif cmd == "resolve":
        d = find(devs, sys.argv[2]) if len(sys.argv) > 2 else builtin(devs)
        if not d:
            raise SystemExit("no such output device: %s" % (sys.argv[2:] or ""))
        print(d["name"])
    elif cmd == "tag":
        d = find(devs, sys.argv[2])
        print(d["tag"] if d else "")
    else:
        raise SystemExit("usage: devices.py {list|active|resolve|tag}")


if __name__ == "__main__":
    main()
