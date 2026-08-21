#!/usr/bin/env python3
"""Route each playing stream to the profile that suits it. Pure stdlib.

`autoswitch` follows the output *device*: plug in headphones, get the headphone
EQ. This follows the *stream*, which is a different question with a different
answer -- Spotify wants the music curve at the same moment a video call wants
the speech one, and neither should have to wait for the other to stop.

That is only possible because every profile is already loaded as its own sink.
Nothing new has to be built to play two profiles at once; the streams just have
to be pointed at the right ones.

Three signals, most specific first:

  content     what is actually playing, when an app will say. Spotify's MPRIS
              track id distinguishes /track/ from /episode/, which is the only
              way to tell a song from a podcast -- both arrive on one stream
              with the same properties otherwise.
  app rule    application.name, matched against the user's rules and then the
              built-in ones. Covers everything that sets no role.
  media.role  PipeWire's own hint. Robust and standard where it exists; Spotify
              sets `music`, most things set nothing.

A stream nothing matches is left alone, on whatever the default is. That is the
common case and it must stay uneventful: routing is for the handful of streams
where the right answer is knowable, not an excuse to move everything.
"""
import json
import re
import subprocess
import sys

import prefs
import state

# media.role -> profile. PipeWire's roles are a small fixed vocabulary.
DEFAULT_ROLES = {
    "music": "music",
    "phone": "voice",
    "video": "voice",
    "a11y": "voice",
    # `event` is notification blips and `production` is pro audio; neither wants
    # a correction chosen for it.
    "event": None,
    "production": None,
}

# application.name (lowercased substring) -> profile. Deliberately short: every
# entry is a claim about what an app is for, and a wrong one is worse than no
# entry, because a missing rule just leaves the stream on the default.
DEFAULT_APPS = {
    "spotify": "music",
    "rhythmbox": "music",
    "tidal": "music",
    "youtube music": "music",
    "zoom": "voice",
    "microsoft teams": "voice",
    "discord": "voice",
    "slack": "voice",
    "telegram": "voice",
    "signal": "voice",
    "mpv": "voice",
    "vlc": "voice",
}

DEFAULT_ROUTING = {"enabled": False, "content": True}


def settings():
    conf = dict(DEFAULT_ROUTING)
    data = prefs._read().get("routing") or {}
    conf.update({k: v for k, v in data.items() if k in DEFAULT_ROUTING})
    conf["apps"] = dict(DEFAULT_APPS)
    # A stored null is an exemption and has to survive the merge -- dropping it
    # would silently restore the built-in rule it exists to suppress.
    conf["apps"].update({str(k).lower(): v
                         for k, v in (data.get("apps") or {}).items()})
    conf["roles"] = dict(DEFAULT_ROLES)
    conf["roles"].update(data.get("roles") or {})
    return conf


def set_routing(**kw):
    data = prefs._read()
    conf = data.setdefault("routing", {})
    for k, v in kw.items():
        if v is not None:
            conf[k] = v
    prefs._write(data)
    return settings()


EXEMPT = "-"


def set_app_rule(app, profile):
    """Add, exempt or remove one application rule.

    Three outcomes, not two, and conflating them is a trap: `None` *removes* the
    rule so the built-in applies again, while EXEMPT stores a rule that says
    "leave this app alone" -- which is the only way to stop a built-in from
    acting. Stored as JSON null so `classify` sees the key present with no
    profile and reports it as deliberate.
    """
    data = prefs._read()
    apps = data.setdefault("routing", {}).setdefault("apps", {})
    if profile in (None, ""):
        apps.pop(app.lower(), None)
    elif profile == EXEMPT:
        apps[app.lower()] = None
    else:
        apps[app.lower()] = profile
    prefs._write(data)
    return settings()


# ---- reading the graph ------------------------------------------------------
def _pactl(*args):
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True,
                              timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def sink_names():
    """{index: name} for every sink.

    `pactl list sink-inputs` reports the sink a stream is on as a *number*, so
    every comparison against a sink name needs this. Getting that wrong is
    silent: the filter simply never matches and nothing is ever routed.
    """
    out = {}
    for line in _pactl("list", "short", "sinks").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            out[parts[0].strip()] = parts[1].strip()
    return out


def parse_sink_inputs(text):
    """[{index, sink, props}] from `pactl list sink-inputs`. `sink` is an index."""
    out, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^Sink Input #(\d+)$", line)
        if m:
            if cur:
                out.append(cur)
            cur = {"index": m.group(1), "sink": "", "corked": False,
                   "props": {}}
        elif cur is not None:
            if line.startswith("Sink:"):
                cur["sink"] = line.split(":", 1)[1].strip()
            elif line.startswith("Corked:"):
                # `pactl list short sink-inputs` has no state column at all, so
                # whether a stream is actually making sound only appears here.
                cur["corked"] = line.split(":", 1)[1].strip() == "yes"
            elif " = " in line:
                k, v = line.split(" = ", 1)
                cur["props"][k.strip()] = v.strip().strip('"')
    if cur:
        out.append(cur)
    return out


def _content_from_trackid(trackid):
    """'music' | 'voice' | None from an MPRIS track id.

    Split out from the subprocess call so the mapping -- the part with the
    actual decision in it -- can be tested without Spotify running.
    """
    if not trackid:
        return None
    if "/episode/" in trackid or ":episode:" in trackid:
        return "voice"
    if "/track/" in trackid or ":track:" in trackid:
        return "music"
    return None


def spotify_content():
    """'music' or 'voice' for what Spotify is playing, or None.

    A song and a podcast episode arrive on the same stream with identical
    PipeWire properties -- the only thing that tells them apart is the MPRIS
    track id, which spells the type into the object path.
    """
    try:
        out = subprocess.run(["playerctl", "-p", "spotify", "metadata",
                              "mpris:trackid"], capture_output=True, text=True,
                             timeout=4).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return _content_from_trackid(out)


# ---- the decision -----------------------------------------------------------
def classify(stream, conf, content=None):
    """(profile_key, why) for one stream, or (None, why) to leave it alone."""
    props = stream.get("props", {})
    app = (props.get("application.name") or
           props.get("node.name") or "").lower()
    binary = (props.get("application.process.binary") or "").lower()

    if content and conf.get("content") and "spotify" in (app + " " + binary):
        return content, "Spotify is playing %s" % (
            "a podcast episode" if content == "voice" else "a song")

    for name, profile in conf["apps"].items():
        if name and (name in app or name in binary):
            if profile:
                return profile, "app rule: %s" % name
            return None, "app rule: %s (leave alone)" % name

    role = props.get("media.role", "")
    if role in conf["roles"]:
        profile = conf["roles"][role]
        if profile:
            return profile, "media.role = %s" % role
        return None, "media.role = %s (leave alone)" % role

    return None, "no rule matches"


def is_ours(sink_name, tag):
    return sink_name.startswith("eq_%s_" % tag)


def plan(devs=None):
    """Rows describing which streams should move where.

    Only streams already on the active device are considered -- moving a stream
    that someone deliberately sent to another output would be overreach.
    """
    import devices as devmod

    conf = settings()
    devs = devmod.listing() if devs is None else devs
    dev = devmod.active(devs)
    if dev is None:
        return ["error\tno output device"]

    tag, sink = dev["tag"], dev["name"]
    profiles = (state._read(state.profiles_path(sink), {}) or {}).get("profiles", {})
    inputs = parse_sink_inputs(_pactl("list", "sink-inputs"))
    names = sink_names()
    content = spotify_content() if conf.get("content") else None

    rows = []
    for st in inputs:
        props = st["props"]
        # The filter chains' own playback streams have no client and must never
        # be moved: pointing one chain at another chains the EQs together.
        if props.get("node.name", "").startswith("eq_") or \
                not props.get("application.name"):
            continue
        on = names.get(st["sink"], "")
        if on and not (on == sink or is_ours(on, tag)):
            continue                       # on another output; not ours to move
        key, why = classify(st, conf, content)
        if not key or key not in profiles:
            continue
        target = "eq_%s_%s" % (tag, key)
        if on == target:
            continue                       # already there; moving it would churn
        rows.append("move\t%s\t%s\t%s\t%s" % (
            st["index"], target, props.get("application.name", "?"), why))
    return rows


def playing(devs=None):
    """Rows: where each application's audio is actually going, right now.

    The bar needs this because per-stream routing deliberately does not touch
    the default sink -- so the default, which is what `ab status` reports, stays
    put while the audio you are listening to moves somewhere else entirely. A
    bar reading the default would sit there showing the same thing all day while
    routing worked perfectly behind it, which is indistinguishable from routing
    not working at all.
    """
    import devices as devmod

    devs = devmod.listing() if devs is None else devs
    dev = devmod.active(devs)
    if dev is None:
        return []
    tag = dev["tag"]
    names = sink_names()
    rows = []
    for st in parse_sink_inputs(_pactl("list", "sink-inputs")):
        app = st["props"].get("application.name")
        if not app or st["props"].get("node.name", "").startswith("eq_"):
            continue
        on = names.get(st["sink"], "")
        if not is_ours(on, tag):
            continue
        rows.append("stream\t%s\t%s\t%d" % (
            app, on[len("eq_%s_" % tag):], 0 if st["corked"] else 1))
    return rows


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if cmd == "plan":
        print("\n".join(plan()))
    elif cmd == "settings":
        conf = settings()
        print("enabled\t%d" % (1 if conf["enabled"] else 0))
        print("content\t%d" % (1 if conf["content"] else 0))
        for app in sorted(conf["apps"]):
            print("app\t%s\t%s" % (app, conf["apps"][app] or "-"))
    elif cmd == "set":
        kw = {}
        for arg in sys.argv[2:]:
            k, _, v = arg.partition("=")
            kw[k] = v not in ("0", "false", "no", "off")
        set_routing(**kw)
    elif cmd == "rule":
        set_app_rule(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "playing":
        print("\n".join(playing()))
    elif cmd == "content":
        print(spotify_content() or "")
    else:
        raise SystemExit(
            "usage: routing.py {plan|playing|settings|set|rule|content}")


if __name__ == "__main__":
    main()
