#!/usr/bin/env python3
"""Import a preset in any of AutoEQ's four formats. Pure stdlib.

AutoEQ publishes each correction four ways, and the wiki's "Choosing an
Equalizer App" page is really a guide to which of them your software can eat.
PipeWire can eat all four, so omarchy-eq accepts all four:

  parametric    Equalizer APO filters. Exact -- every line is a biquad PipeWire
                already implements, so this is a parse and a name map. Prefer it.
  fixedband     the same syntax with the frequencies pinned to fixed bands. Also
                exact; it was always accepted, just never named.
  graphic       a sampled target curve. Not a filter description at all, so it is
                fitted onto a bank of biquads -- see graphic_eq.py. Approximate,
                and the fit error is recorded in the profile and printed.
  convolution   an impulse response, run through PipeWire's `convolver`. The
                most accurate option -- an FIR can draw a response a biquad bank
                cannot. The wav is copied into the device's state directory,
                because a chain pointing at ~/Downloads is a chain that breaks
                the first time that directory is tidied.

The profile records which format it came from. That is not bookkeeping -- what
you can say about a profile afterwards depends on it. A parametric import is
exact and needs no caveat; a graphic import carries a fit error and the sample
rates it was fitted at; a convolution profile depends on a file that must still
be there.
"""
import json
import os
import re
import shutil
import sys
import wave

import graphic_eq
import import_apo

FORMATS = ("parametric", "fixedband", "graphic", "convolution")
# A convolver's cost is its length. AutoEQ's own responses are a few thousand
# taps; something far longer is a room-correction IR, and past a point it is
# someone's reverb rather than a correction.
IR_WARN_TAPS = 32768
IR_MAX_TAPS = 262144
# Fraction of total energy that has to have arrived for the response to count as
# "front-loaded", i.e. minimum phase.
IR_BULK = 0.5
IR_MINPHASE_MS = 1.0


def detect(path, text=None):
    """Which of the four formats a file is, from its content then its name."""
    if path.lower().endswith(".wav"):
        return "convolution"
    if text is None:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    if re.search(r"^\s*GraphicEQ\s*:", text, re.I | re.M):
        return "graphic"
    if re.search(r"^\s*Filter\s*\d*\s*:", text, re.I | re.M):
        # Same syntax either way; the name is the only thing that distinguishes
        # them, and the distinction is cosmetic -- both parse identically.
        return "fixedband" if "fixedband" in os.path.basename(path).lower() \
            else "parametric"
    raise SystemExit(
        "unrecognised preset format: %s\n"
        "Expected an Equalizer APO / AutoEQ file (ParametricEQ.txt,\n"
        "FixedBandEQ.txt, GraphicEQ.txt) or an impulse response (.wav)." % path)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


# ---- per-format builders ----------------------------------------------------
def _from_apo(path, fmt):
    with open(path, encoding="utf-8", errors="replace") as fh:
        filters, preamp, skipped = import_apo.parse(fh.read())
    if not filters:
        raise SystemExit("no usable filters found in %s" % path)
    return {
        "format": fmt,
        "filters": import_apo.build(filters, preamp),
        "summary": import_apo.summarise(filters, preamp),
    }, ["skipped unsupported: %s" % s for s in skipped]


def _from_graphic(path, rates, bands):
    with open(path, encoding="utf-8", errors="replace") as fh:
        points = graphic_eq.parse(fh.read())
    if not points:
        raise SystemExit("no usable points found in %s" % path)
    filters, preamp, max_err, rms = graphic_eq.fit(points, bands, rates)
    if not filters:
        raise SystemExit("%s is already flat -- nothing to correct" % path)
    chain = import_apo.build(filters, preamp)
    notes = ["fitted %d curve points onto %d peaking filters at %s kHz"
             % (len(points), len(filters),
                "/".join("%g" % (r / 1000.0) for r in rates)),
             "fit error: %.2f dB worst case, %.2f dB rms" % (max_err, rms)]
    if max_err > 3.0:
        notes.append("that is a poor fit -- this curve has features a biquad "
                     "bank cannot follow. Try more bands (--bands), or use the "
                     "ParametricEQ or convolution version if there is one.")
    return {
        "format": "graphic",
        "filters": chain,
        "summary": "%d x peaking fitted from a %d-point curve"
                   % (len(filters), len(points)),
        "fitted_rates": [int(r) for r in rates],
        "fit_error_db": max_err,
        "fit_rms_db": rms,
    }, notes


def _ir_delay(path):
    """(bulk_delay_ms, total_ms) for an impulse response, or None if unreadable.

    The delay a convolver adds is not its length. AutoEQ ships *minimum phase*
    responses, whose energy is at the very front -- the HD 650's 4800-tap file
    has half its energy inside the first three samples and delays nothing. A
    linear-phase response of the same length is symmetric about its centre and
    really does cost half its length in latency. Reporting length as latency
    would libel the accurate option, so measure where the energy actually is.
    """
    try:
        with wave.open(path, "rb") as w:
            n, ch, sw, rate = (w.getnframes(), w.getnchannels(),
                               w.getsampwidth(), w.getframerate())
            raw = w.readframes(n)
    except (wave.Error, EOFError, OSError):
        return None
    fmt = {1: "b", 2: "h", 4: "i"}.get(sw)
    if not fmt or not n or not rate:
        return None                    # 24-bit or float: skip the analysis
    import struct
    try:
        vals = struct.unpack("<%d%s" % (n * ch, fmt), raw[:n * ch * sw])
    except struct.error:
        return None
    left = [abs(v) for v in vals[::ch]]
    total = sum(left)
    if not total:
        return None
    acc, bulk = 0, len(left) - 1
    for i, v in enumerate(left):
        acc += v
        if acc >= total * IR_BULK:
            bulk = i
            break
    return 1000.0 * bulk / rate, 1000.0 * n / rate


def _from_wav(path, dest_dir, name):
    try:
        with wave.open(path, "rb") as w:
            channels, frames, rate = w.getnchannels(), w.getnframes(), \
                w.getframerate()
    except (wave.Error, EOFError) as exc:
        raise SystemExit("not a readable WAV impulse response: %s (%s)"
                         % (path, exc))
    if frames == 0:
        raise SystemExit("%s has no samples" % path)
    if frames > IR_MAX_TAPS:
        raise SystemExit(
            "%s is %d taps (%.1f s) -- too long to run as a correction.\n"
            "At that length it is a room or reverb impulse response, not an\n"
            "equaliser." % (path, frames, float(frames) / rate))

    # Copy it in. A chain whose convolver points at ~/Downloads dies silently
    # the first time that directory is tidied, and the failure looks like "the
    # EQ stopped working" rather than "a file moved".
    os.makedirs(dest_dir, exist_ok=True)
    kept = os.path.join(dest_dir, "%s.wav" % name)
    if os.path.abspath(path) != os.path.abspath(kept):
        shutil.copyfile(path, kept)

    if channels >= 2:
        # A stereo impulse response is two different responses, one per ear.
        filters = [{"name": "conv", "label": "convolver",
                    "config_l": {"filename": kept, "channel": 0},
                    "config_r": {"filename": kept, "channel": 1}}]
    else:
        filters = [{"name": "conv", "label": "convolver",
                    "config": {"filename": kept, "channel": 0}}]
    notes = ["impulse response: %d taps, %d Hz, %s"
             % (frames, rate, "stereo" if channels >= 2 else "mono"),
             "copied to %s" % kept]
    timing = _ir_delay(path)
    if timing:
        bulk_ms, total_ms = timing
        if bulk_ms <= IR_MINPHASE_MS:
            notes.append("minimum phase (energy arrives in %.2f ms) -- adds no "
                         "meaningful delay" % bulk_ms)
        else:
            notes.append("adds about %.1f ms of delay (of %.1f ms total "
                         "response) -- noticeable in video and games if it is "
                         "more than ~20 ms" % (bulk_ms, total_ms))
    if frames > IR_WARN_TAPS:
        notes.append("%d taps is long for a headphone correction; expect it to "
                     "cost more CPU than a biquad chain." % frames)
    return {
        "format": "convolution",
        "filters": filters,
        "summary": "convolver, %d taps @ %d Hz (%s)"
                   % (frames, rate, "stereo" if channels >= 2 else "mono"),
        "ir_file": kept,
        "ir_taps": frames,
        "ir_rate": rate,
    }, notes


# ---- entry point ------------------------------------------------------------
def build_profile(path, dest_dir, name, rates=None, bands=graphic_eq.DEFAULT_N,
                  fmt=None):
    """(profile dict, notes) for one preset file."""
    fmt = fmt or detect(path)
    if fmt == "convolution":
        prof, notes = _from_wav(path, os.path.join(dest_dir, "ir"), name)
    elif fmt == "graphic":
        prof, notes = _from_graphic(path, tuple(rates or graphic_eq.RATES), bands)
    else:
        prof, notes = _from_apo(path, fmt)
    prof["source"] = "import"
    prof["origin"] = os.path.basename(path)
    prof["description"] = "%s from %s" % (fmt, os.path.basename(path))
    return prof, notes


def install(profiles_path, key, profile):
    try:
        with open(profiles_path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {"analysis": {}, "profiles": {}}
    data.setdefault("profiles", {})[key] = profile
    os.makedirs(os.path.dirname(profiles_path) or ".", exist_ok=True)
    tmp = profiles_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, profiles_path)
    return data


def main():
    """argv: <file> <profiles.json> <device-dir> [name] [--bands N] [--rates a,b]"""
    args = [a for a in sys.argv[1:]]
    bands, rates = graphic_eq.DEFAULT_N, None
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--bands":
            bands = int(args[i + 1]); i += 2
        elif args[i] == "--rates":
            rates = tuple(float(r) for r in args[i + 1].split(",")); i += 2
        else:
            positional.append(args[i]); i += 1
    if len(positional) < 3:
        raise SystemExit("usage: importer.py <file> <profiles.json> <device-dir> "
                         "[name] [--bands N] [--rates a,b]")
    src, profiles_path, dest_dir = positional[:3]
    name = positional[3] if len(positional) > 3 and positional[3] else \
        os.path.splitext(os.path.basename(src))[0]
    # AutoEQ filenames end in the format; keeping it would name the profile
    # "sennheiser_hd_650_parametriceq".
    name = re.sub(r"[ _](parametric|graphic|fixedband)eq$", "", name, flags=re.I)
    name = re.sub(r"\s+minimum phase \d+hz$", "", name, flags=re.I)
    key = slug(name) or "imported"

    if rates is None:
        import devices
        rates = devices.allowed_rates()
    profile, notes = build_profile(src, dest_dir, key, rates, bands)
    install(profiles_path, key, profile)

    print("imported '%s': %s" % (key, profile["summary"]))
    for n in notes:
        print("  %s" % n)
    print("written: %s" % profiles_path)


if __name__ == "__main__":
    main()
