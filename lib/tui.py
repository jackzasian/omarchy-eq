#!/usr/bin/env python3
"""Terminal UI: see the measured curve and the EQ, switch profiles live.

Deliberately not a GUI. The value here is showing *your measurement* next to
the correction derived from it -- which is the one thing a generic EQ app
cannot do -- and switching fast enough to A/B by ear.

Actions that restart PipeWire or need a real TTY (measure, apply) drop out of
curses, run normally, and come back.
"""
import curses
import json
import math
import os
import subprocess
import sys

import curve

F_LO, F_HI = 20.0, 20000.0
TICKS = [50, 200, 1000, 5000, 20000]


def _read(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def resample(pts, w):
    """One value per screen column, linearly interpolated in log-frequency."""
    if not pts or w < 2:
        return []
    lo, hi = math.log10(F_LO), math.log10(F_HI)
    xs = [math.log10(f) for f, _ in pts]
    ys = [d for _, d in pts]
    out = []
    for c in range(w):
        t = lo + (hi - lo) * c / (w - 1)
        if t <= xs[0]:
            out.append(ys[0])
        elif t >= xs[-1]:
            out.append(ys[-1])
        else:
            i = next(i for i in range(1, len(xs)) if t <= xs[i])
            k = (t - xs[i - 1]) / (xs[i] - xs[i - 1])
            out.append(ys[i - 1] + k * (ys[i] - ys[i - 1]))
    return out


def draw_plot(win, y0, h, w, pts, title, lo, hi, attr):
    """One panel: labelled dB axis, log frequency, a curve of block chars."""
    if h < 3 or w < 20:
        return
    pad = 7
    pw = w - pad - 1
    win.addstr(y0, 0, title[:w - 1], curses.A_BOLD)
    body = h - 2
    if not pts:
        win.addstr(y0 + 2, pad, "(no measurement yet - press m)")
        return
    cols = resample(pts, pw)
    for row in range(body):
        db = hi - (hi - lo) * row / max(1, body - 1)
        if row % 2 == 0 or row == body - 1:
            win.addstr(y0 + 1 + row, 0, "%+5.0f  " % db)
        for c, v in enumerate(cols):
            cell = int(round((hi - v) / (hi - lo) * (body - 1)))
            if cell == row:
                try:
                    win.addstr(y0 + 1 + row, pad + c, "*", attr)
                except curses.error:
                    pass
    # frequency ticks
    lo_l, hi_l = math.log10(F_LO), math.log10(F_HI)
    axis = [" "] * pw
    for t in TICKS:
        x = int((math.log10(t) - lo_l) / (hi_l - lo_l) * (pw - 1))
        lab = ("%dk" % (t // 1000)) if t >= 1000 else str(t)
        x = min(max(0, x - len(lab) // 2), pw - len(lab))
        for i, ch in enumerate(lab):
            axis[x + i] = ch
    try:
        win.addstr(y0 + h - 1, pad, "".join(axis)[:pw])
    except curses.error:
        pass


def active_profile(names):
    try:
        d = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                           text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    for n in names:
        if d == "eq_%s" % n:
            return n
    return "flat"


def measured_points(resp):
    """Measured curve, normalised so the midband sits at 0 dB."""
    import state
    pts = state.valid_points(resp) if resp else []
    mid = [d for f, d in pts if 500 <= f <= 4000]
    ref = sum(mid) / len(mid) if mid else 0.0
    return [(f, d - ref) for f, d in pts]


def run(stdscr, resp_path, prof_path, exe):
    curses.curs_set(0)
    curses.use_default_colors()
    for i, c in enumerate((curses.COLOR_CYAN, curses.COLOR_YELLOW,
                           curses.COLOR_GREEN), start=1):
        curses.init_pair(i, c, -1)
    CY, YE, GR = (curses.color_pair(i) for i in (1, 2, 3))

    sel = 0
    msg = ""
    while True:
        resp = _read(resp_path)
        data = _read(prof_path, {}) or {}
        profs = data.get("profiles", {})
        names = list(profs)
        order = ["flat"] + names
        sel = max(0, min(sel, len(order) - 1))
        act = active_profile(names)

        stdscr.erase()
        h, w = stdscr.getmaxyx()
        stdscr.addstr(0, 0, " omarchy-eq "[:w - 1], curses.A_REVERSE)
        stdscr.addstr(0, 13, "measured response and derived correction"[:max(0, w - 14)])

        ph = max(5, (h - 12) // 2)
        mp = measured_points(resp)
        draw_plot(stdscr, 2, ph, w, mp,
                  "measured  (dB, normalised to midband)", -40, 15, CY)

        chosen = order[sel]
        if chosen == "flat":
            eq, tit = [], "EQ curve  flat - no correction"
        else:
            eq = curve.chain_response(profs[chosen]["filters"], curve.log_axis())
            tit = "EQ curve  %s" % chosen
        draw_plot(stdscr, 3 + ph, ph, w, eq, tit, -18, 12, YE)

        row = 4 + 2 * ph
        for i, n in enumerate(order):
            if row + i >= h - 2:
                break
            mark = ">" if i == sel else " "
            live = "*" if n == act else " "
            desc = (profs[n]["description"] if n in profs
                    else "no EQ - raw speakers (reference)")
            line = "%s %s %-10s %s" % (mark, live, n, desc)
            attr = GR if n == act else curses.A_NORMAL
            if i == sel:
                attr |= curses.A_BOLD
            try:
                stdscr.addstr(row + i, 0, line[:w - 1], attr)
            except curses.error:
                pass

        foot = msg or "up/down select  enter switch  m measure  g generate  a apply  q quit"
        try:
            stdscr.addstr(h - 1, 0, foot[:w - 1], curses.A_REVERSE)
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
        elif k in (curses.KEY_ENTER, 10, 13, ord(" ")):
            subprocess.run([exe, "ab", order[sel]], capture_output=True)
            msg = "switched to %s" % order[sel]
        elif k in (ord("m"), ord("g"), ord("a"), ord("d")):
            cmd = {"m": "measure", "g": "generate", "a": "apply",
                   "d": "doctor"}[chr(k)]
            curses.endwin()
            subprocess.run([exe, cmd])
            input("\n  press Enter to return to the TUI ")
            stdscr.clear()


def main():
    resp, prof = sys.argv[1], sys.argv[2]
    exe = sys.argv[3] if len(sys.argv) > 3 else "omarchy-eq"
    if not os.path.exists(prof):
        raise SystemExit("no profiles yet -- run: omarchy-eq measure && "
                         "omarchy-eq generate")
    if not sys.stdout.isatty():
        raise SystemExit("omarchy-eq tui needs a terminal. From the Omarchy "
                         "menu it is launched\nvia omarchy-eq-term; for "
                         "scripting use 'omarchy-eq ab list' instead.")
    try:
        curses.wrapper(run, resp, prof, exe)
    except curses.error as e:
        raise SystemExit("terminal does not support the TUI (%s).\n"
                         "Use 'omarchy-eq ab list' and 'omarchy-eq ab "
                         "<profile>' instead." % e)


if __name__ == "__main__":
    main()
