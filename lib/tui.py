#!/usr/bin/env python3
"""Terminal UI: your measured curve, what the EQ does to it, and live switching.

Deliberately not a GUI. The value here is seeing *your measurement* and the
corrected result on the same axes -- which is the one thing a generic EQ app
cannot show you -- and switching fast enough to A/B by ear.

Actions that restart PipeWire or need a real TTY (calibrate, apply) drop out of
curses, run normally, and come back.
"""
import curses
import json
import math
import os
import subprocess
import sys

import braille
import curve
import devices as devmod
import state

F_LO, F_HI = 20.0, 20000.0
TICKS = [(50, "50"), (100, "100"), (500, "500"), (1000, "1k"),
         (5000, "5k"), (10000, "10k"), (20000, "20k")]


def _read(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def resample(pts, n):
    """One value per dot-column, linearly interpolated in log frequency."""
    if len(pts) < 2 or n < 2:
        return [None] * max(n, 0)
    lo, hi = math.log10(F_LO), math.log10(F_HI)
    xs = [math.log10(f) for f, _ in pts]
    ys = [v for _, v in pts]
    out = []
    for c in range(n):
        t = lo + (hi - lo) * c / (n - 1)
        if t < xs[0] or t > xs[-1]:
            out.append(None)                 # do not invent data past the ends
            continue
        i = next((i for i in range(1, len(xs)) if t <= xs[i]), len(xs) - 1)
        k = (t - xs[i - 1]) / (xs[i] - xs[i - 1]) if xs[i] != xs[i - 1] else 0.0
        out.append(ys[i - 1] + k * (ys[i] - ys[i - 1]))
    return out


def to_dots(values, lo, hi, height):
    span = (hi - lo) or 1.0
    return [None if v is None else
            max(0, min(height - 1, int(round((hi - v) / span * (height - 1)))))
            for v in values]


def measured(resp):
    """Measured curve normalised so the midband sits at 0 dB, plus what was dropped."""
    if not resp:
        return [], []
    pts = state.valid_points(resp)
    mid = [d for f, d in pts if 500 <= f <= 4000]
    ref = sum(mid) / len(mid) if mid else 0.0
    dropped = sorted(float(f) for f, p in resp.get("merged", {}).items()
                     if not p.get("valid"))
    return [(f, d - ref) for f, d in pts], dropped


def draw_plot(win, top, height, width, series, dropped, lo, hi, pairs):
    """One panel: dB axis, braille curves, log frequency ticks."""
    pad, gutter = 6, 1
    cw = width - pad - gutter
    rows = height - 1
    if cw < 10 or rows < 2:
        return
    canvases = []
    for values, attr in series:
        cv = braille.Canvas(cw, rows)
        cv.plot(to_dots(resample(values, cw * 2), lo, hi, cv.h))
        canvases.append((cv.rows_text(), attr))

    for r in range(rows):
        db = hi - (hi - lo) * r / max(1, rows - 1)
        if r % 2 == 0 or r == rows - 1:
            try:
                win.addstr(top + r, 0, "%+5.0f " % db, curses.A_DIM)
            except curses.error:
                pass
        for c in range(cw):
            ch, attr = " ", curses.A_NORMAL
            for text, a in canvases:            # later series wins an overlap
                g = text[r][c]
                if g != chr(0x2800):
                    ch, attr = g, a
            if ch != " ":
                try:
                    win.addstr(top + r, pad + c, ch, attr)
                except curses.error:
                    pass

    lo_l, hi_l = math.log10(F_LO), math.log10(F_HI)
    axis = [" "] * cw
    for f, lab in TICKS:
        x = int((math.log10(f) - lo_l) / (hi_l - lo_l) * (cw - 1)) - len(lab) // 2
        x = max(0, min(x, cw - len(lab)))
        for i, c in enumerate(lab):
            axis[x + i] = c
    for f in dropped:                            # bands with no usable data
        x = int((math.log10(f) - lo_l) / (hi_l - lo_l) * (cw - 1))
        if 0 <= x < cw and axis[x] == " ":
            axis[x] = "x"
    try:
        win.addstr(top + rows, pad, "".join(axis)[:cw], curses.A_DIM)
    except curses.error:
        pass


def run(stdscr, exe, devname):
    curses.curs_set(0)
    curses.use_default_colors()
    for i, c in enumerate((curses.COLOR_CYAN, curses.COLOR_YELLOW,
                           curses.COLOR_GREEN, curses.COLOR_RED), start=1):
        curses.init_pair(i, c, -1)
    CY, YE, GR, RE = (curses.color_pair(i) for i in (1, 2, 3, 4))

    sel, msg = 0, ""
    while True:
        devs = devmod.listing()
        if not devs:
            stdscr.erase(); stdscr.addstr(0, 0, "no output devices"); stdscr.getch()
            return
        dev = devmod.find(devs, devname) if devname else None
        if dev is None:
            dev = devmod.active(devs)
            devname = dev["name"]

        resp = _read(state.response_path(dev["name"]))
        profs = (_read(state.profiles_path(dev["name"]), {}) or {}).get("profiles", {})
        order = ["flat"] + list(profs)
        sel = max(0, min(sel, len(order) - 1))
        chosen = order[sel]

        try:
            default = devmod.default_sink()
        except Exception:
            default = ""
        act = "flat" if default == dev["name"] else None
        if act is None:
            for k in profs:
                if default == "eq_%s_%s" % (dev["tag"], k):
                    act = k
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        stdscr.addstr(0, 0, (" omarchy-eq " + " " * w)[:w - 1], curses.A_REVERSE)
        hdr = "%s  [%s%s]" % (dev["description"], dev["kind"],
                              "/" + dev["codec"] if dev["codec"] else "")
        stdscr.addstr(1, 1, hdr[:w - 2], curses.A_BOLD)

        mpts, dropped = measured(resp)
        if not mpts:
            note = ("no measurement for this output"
                    if dev["measurable"] else
                    "cannot be measured - import an AutoEQ preset instead")
            stdscr.addstr(3, 2, note[:w - 3], RE)
            plot_bottom = 4
        else:
            eqpts = []
            if chosen != "flat" and chosen in profs:
                gains = dict(curve.chain_response(profs[chosen]["filters"],
                                                  [f for f, _ in mpts]))
                eqpts = [(f, d + gains.get(f, 0.0)) for f, d in mpts]
            ph = max(6, min(16, h - len(order) - 9))
            series = [(mpts, CY | curses.A_DIM)]
            if eqpts:
                series.append((eqpts, YE))
            draw_plot(stdscr, 3, ph, w, series, dropped, -36, 18, None)
            legend = "measured" + ("   corrected: %s" % chosen if eqpts else "")
            stdscr.addstr(2, 1, legend[:w - 2], curses.A_DIM)
            if dropped:
                stdscr.addstr(2, min(w - 24, len(legend) + 4),
                              "x = %d band(s) dropped" % len(dropped), RE | curses.A_DIM)
            plot_bottom = 3 + ph + 1

        row = plot_bottom
        for i, n in enumerate(order):
            if row + i >= h - 2:
                break
            desc = (profs[n]["description"] if n in profs
                    else "no EQ - raw output (reference)")
            line = "%s %s %-10s %s" % (">" if i == sel else " ",
                                       "*" if n == act else " ", n, desc)
            attr = GR if n == act else curses.A_NORMAL
            if i == sel:
                attr |= curses.A_BOLD
            try:
                stdscr.addstr(row + i, 0, line[:w - 1], attr)
            except curses.error:
                pass

        foot = msg or ("enter switch   tab device   c calibrate   a apply   "
                       "g generate   d doctor   q quit")
        try:
            stdscr.addstr(h - 1, 0, (foot + " " * w)[:w - 1], curses.A_REVERSE)
        except curses.error:
            pass
        stdscr.refresh()

        k = stdscr.getch()
        msg = ""
        if k in (ord("q"), 27):
            return
        elif k in (curses.KEY_UP, ord("k")):
            sel -= 1
        elif k in (curses.KEY_DOWN, ord("j")):
            sel += 1
        elif k == ord("\t"):
            names = [d["name"] for d in devs]
            devname = names[(names.index(dev["name"]) + 1) % len(names)]
            sel = 0
        elif k in (curses.KEY_ENTER, 10, 13, ord(" ")):
            if chosen == "flat" or chosen in profs:
                r = subprocess.run([exe, "ab", "--device", dev["tag"], chosen],
                                   capture_output=True, text=True)
                msg = ("switched to %s" % chosen if r.returncode == 0
                       else r.stderr.strip().splitlines()[0] if r.stderr.strip()
                       else "switch failed")
        elif k in (ord("c"), ord("g"), ord("a"), ord("d")):
            cmd = {"c": "calibrate", "g": "generate", "a": "apply", "d": "doctor"}[chr(k)]
            curses.endwin()
            subprocess.run([exe, cmd, "--device", dev["tag"]])
            input("\n  press Enter to return to the TUI ")
            stdscr.clear()


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else "omarchy-eq"
    devname = sys.argv[2] if len(sys.argv) > 2 else ""
    if not sys.stdout.isatty():
        raise SystemExit("omarchy-eq tui needs a terminal. From the Omarchy menu "
                         "it is launched\nvia omarchy-eq-term; for scripting use "
                         "'omarchy-eq ab list' instead.")
    try:
        curses.wrapper(run, exe, devname)
    except curses.error as e:
        raise SystemExit("terminal does not support the TUI (%s).\n"
                         "Use 'omarchy-eq ab list' and 'omarchy-eq ab <profile>' "
                         "instead." % e)


if __name__ == "__main__":
    main()
