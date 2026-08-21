#!/usr/bin/env python3
"""Find and download presets from the AutoEQ database. Pure stdlib.

AutoEQ publishes ~7000 measured headphone corrections as files in a GitHub
repository. Downloading them by hand works fine -- `omarchy-eq import` has always
accepted the result -- but it means leaving the terminal, knowing which of four
file formats to pick, and knowing which of the five measurements of your
headphones to trust. This module does that part.

Two network calls, both to raw.githubusercontent.com over HTTPS:

  index    results/INDEX.md, ~850 KB, one line per preset:
               - [Sennheiser HD 650](./oratory1990/over-ear/Sennheiser%20HD%20650)
                 by oratory1990
           Cached under XDG_CACHE_HOME for a week. It is the whole catalogue, so
           searching is local and instant once it has been fetched once.
  preset   one file out of one result directory.

Nothing is fetched unless asked for. The watcher's auto-setup is opt-in for
exactly this reason: looking up a device name is a request to a third party
carrying the name of hardware you own, and that should be a choice rather than
something that starts happening when you plug in headphones.

Filenames inside a result directory are derived from the directory's own name --
"<dir> ParametricEQ.txt" and so on -- not from the display name in the index,
which carries a parenthesised measurement target when a source published several.
"""
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results"
INDEX_URL = RAW + "/INDEX.md"
INDEX_TTL = 7 * 24 * 3600
TIMEOUT = 30
UA = "omarchy-eq (+https://github.com/jackzasian/omarchy-eq)"

# Formats, as (suffix template, what it is). `wav` needs a rate, filled in later.
FORMATS = {
    "parametric": "%s ParametricEQ.txt",
    "graphic": "%s GraphicEQ.txt",
    "fixedband": "%s FixedBandEQ.txt",
    "convolution": "%s minimum phase %dHz.wav",
}
IR_RATES = (44100, 48000)

# Measurement sources, best first. Only ever a tie-break between entries that
# matched the query equally well -- it never promotes a worse name match.
# oratory1990 and crinacle are the two large rigs with published methodology;
# the rest are ordered by how much of the database they cover.
SOURCE_RANK = ["oratory1990", "crinacle", "Rtings", "Innerfidelity",
               "Headphone.com Legacy", "DHRME", "HypetheSonics"]

ENTRY_RE = re.compile(
    r"^-\s*\[(?P<name>[^\]]+)\]\((?P<path>[^)]+)\)\s*by\s+(?P<source>.+?)"
    r"(?:\s+on\s+(?P<target>.+?))?\s*$")


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "omarchy-eq")


def index_path():
    return os.path.join(cache_dir(), "autoeq-index.md")


def _get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
        data = fh.read()
    return data if binary else data.decode("utf-8", "replace")


def fetch_index(force=False):
    """The catalogue text, from cache when it is fresh enough."""
    path = index_path()
    if not force:
        try:
            if time.time() - os.path.getmtime(path) < INDEX_TTL:
                with open(path, encoding="utf-8") as fh:
                    return fh.read()
        except OSError:
            pass
    text = _get(INDEX_URL)
    os.makedirs(cache_dir(), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return text


def parse_index(text):
    """[{name, path, dir, source, target}] for every preset in the catalogue."""
    out = []
    for line in text.splitlines():
        m = ENTRY_RE.match(line.strip())
        if not m:
            continue
        path = urllib.parse.unquote(m.group("path")).lstrip("./")
        out.append({"name": m.group("name").strip(),
                    "path": path,
                    "dir": path.rsplit("/", 1)[-1],
                    "source": (m.group("source") or "").strip(),
                    "target": (m.group("target") or "").strip()})
    return out


def entries(force=False):
    return parse_index(fetch_index(force))


# ---- matching ---------------------------------------------------------------
def norm(s):
    """Lowercase alphanumeric tokens, joined by single spaces.

    Everything the two sides might disagree about goes away: punctuation, case,
    and the spacing inside a model number. "WH-1000XM4", "wh 1000xm4" and
    "WH1000XM4" all have to land on the same string or nothing matches.
    """
    s = re.sub(r"[^a-z0-9]+", " ", (s or "").lower())
    return " ".join(s.split())


def _tokens(s):
    return set(norm(s).split())


def _source_rank(entry):
    try:
        return SOURCE_RANK.index(entry["source"])
    except ValueError:
        return len(SOURCE_RANK)


def score(entry, query):
    """How well one catalogue entry answers a query. Higher is better, 0 = no.

    The asymmetry is the whole point. Words in the *name* that the query lacks
    are usually just the brand -- "wh 1000xm4" against "Sony WH-1000XM4" is a
    hit. Words in the *query* that the name lacks are the opposite: they are how
    product variants are spelled. "Nothing Ear (open)" is not "Nothing ear", and
    an earlier symmetric version of this scored that pair 87 and would have
    installed the wrong headphone's correction curve without saying anything.

    So query-side extras are penalised hard enough to fall under STRONG, and the
    entry survives only as a search suggestion for a human to look at.

    Deliberately blunt otherwise -- no edit distance. A fuzzy matcher finds
    something for every query, which is the wrong instinct for a value that may
    be acted on unattended.
    """
    q, name = norm(query), norm(entry["name"])
    if not q or not name:
        return 0.0
    if q == name:
        return 100.0
    qt, nt = _tokens(query), _tokens(entry["name"])
    if not qt or not nt:
        return 0.0
    extra_q, extra_n = qt - nt, nt - qt
    if not extra_q:                    # query is contained in the name
        return max(55.0, 90.0 - 12.0 * len(extra_n))
    if not extra_n:                    # query says more than the name does
        return max(20.0, 50.0 - 12.0 * len(extra_q))
    overlap = len(qt & nt)
    if not overlap:
        return 0.0
    return 45.0 * overlap / len(qt | nt)


def search(query, limit=10, force=False, items=None):
    """Ranked [(score, entry)], best first."""
    items = entries(force) if items is None else items
    hits = [(score(e, query), e) for e in items]
    hits = [h for h in hits if h[0] > 0]
    hits.sort(key=lambda h: (-h[0], _source_rank(h[1]), h[1]["name"]))
    return hits[:limit]


# Words PipeWire or the vendor adds to a Bluetooth name that are not part of the
# model. Stripped only when trying to auto-match; a hand-typed query is used as
# given, because the user may genuinely mean "(ANC Off)".
NOISE = ("bluetooth", "stereo", "headset", "headphones", "handsfree",
         "hands free", "audio", "a2dp", "sink", "le", "le_audio", "hi fi",
         "hifi", "wireless", "true wireless", "earbuds", "buds")
STRONG = 60.0                # below this, auto-setup declines to guess
AMBIGUOUS_GAP = 10.0         # two different products this close: also decline


def match_device(description, items=None, force=False):
    """Best catalogue entry for a device description, or None.

    Used by unattended auto-setup, so it refuses to guess twice over: a weak
    score returns None, and so does an *ambiguous* strong one. If the two best
    candidates name different products and score within a hair of each other,
    there is no answer here -- only a coin flip, and silently EQ-ing someone's
    headphones from a coin flip is the failure mode worth engineering against.
    Several sources measuring the same model is not ambiguity; that is one
    answer with a source to pick, and SOURCE_RANK picks it.
    """
    items = entries(force) if items is None else items
    tried = [description]
    cleaned = norm(description)
    for word in NOISE:
        cleaned = re.sub(r"\b%s\b" % re.escape(word), " ", cleaned)
    cleaned = " ".join(cleaned.split())
    if cleaned and cleaned != norm(description):
        tried.append(cleaned)

    best = None
    for q in tried:
        hits = search(q, limit=8, items=items)
        if not hits or hits[0][0] < STRONG:
            continue
        top_name = norm(hits[0][1]["name"])
        rival = next((h for h in hits if norm(h[1]["name"]) != top_name), None)
        if rival and hits[0][0] - rival[0] < AMBIGUOUS_GAP:
            continue
        if best is None or hits[0][0] > best[0]:
            best = hits[0]
    return best


# ---- download ---------------------------------------------------------------
def file_url(entry, fmt="parametric", rate=48000):
    if fmt == "convolution":
        name = FORMATS[fmt] % (entry["dir"], rate)
    else:
        name = FORMATS[fmt] % entry["dir"]
    return "%s/%s" % (RAW, urllib.parse.quote("%s/%s" % (entry["path"], name)))


def download(entry, dest, fmt="parametric", rate=48000):
    """Save one preset file. Returns the path written."""
    binary = fmt == "convolution"
    data = _get(file_url(entry, fmt, rate), binary=binary)
    if os.path.isdir(dest):
        dest = os.path.join(dest, os.path.basename(
            urllib.parse.unquote(file_url(entry, fmt, rate))))
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb" if binary else "w",
              **({} if binary else {"encoding": "utf-8"})) as fh:
        fh.write(data)
    return dest


def label(entry):
    bits = [entry["name"], "by %s" % entry["source"]]
    if entry["target"]:
        bits.append("on %s" % entry["target"])
    return " ".join(bits)


def _row(score, e):
    """One tab-separated result line.

    The measurement target is empty for most sources, and an empty field in the
    middle of a tab-separated line does not survive `read` in the shell: tab is
    IFS whitespace, so bash collapses the doubled delimiter and every later
    field shifts left. That silently dropped exactly the entries with no target
    -- which includes oratory1990, the source ranked first. A literal "-" keeps
    the column count fixed.
    """
    return "%.0f\t%s\t%s\t%s\t%s" % (score, e["name"], e["source"],
                                       e["target"] or "-", e["path"])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "search":
            limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
            for sc, e in search(sys.argv[2], limit):
                print(_row(sc, e))
        elif cmd == "match":
            hit = match_device(sys.argv[2])
            if not hit:
                raise SystemExit(1)
            print(_row(*hit))
        elif cmd == "get":
            # get <path> <dest> [format] [rate]
            path = sys.argv[2]
            entry = {"path": path, "dir": path.rsplit("/", 1)[-1]}
            fmt = sys.argv[4] if len(sys.argv) > 4 else "parametric"
            rate = int(sys.argv[5]) if len(sys.argv) > 5 else 48000
            print(download(entry, sys.argv[3], fmt, rate))
        elif cmd == "refresh":
            fetch_index(force=True)
            print("%d presets" % len(entries()))
        else:
            raise SystemExit("usage: autoeq.py {search|match|get|refresh}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit("autoeq: not published in this format (404)")
        raise SystemExit("autoeq: HTTP %s for %s" % (exc.code, exc.url))
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit("autoeq: cannot reach the AutoEQ database (%s)" % exc)


if __name__ == "__main__":
    main()
