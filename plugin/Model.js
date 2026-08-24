.pragma library

// Parsing for the EQ bar widget. Kept out of the QML so it can be reasoned
// about (and changed) without touching layout code.
//
// Everything here reads `omarchy-eq`'s own output rather than its state files.
// The files are JSON and would be easier to parse, but they are private layout
// that has already changed once; the CLI's output is the part with users.
//
// The panel asks `omarchy-eq status --json` once and parses it with
// parseStatusJson. The four text parsers below it are the fallback for when the
// omarchy-eq on PATH is older than this plugin -- the two are installed
// separately, so that combination is a normal thing to be in, not a bug. They
// are otherwise unused.

// `omarchy-eq status --json`: one document, one process, everything the panel
// needs. Returns null when the output is not the JSON we expect, which is the
// signal to fall back to the text commands.
function parseStatusJson(raw) {
    if (!raw)
        return null
    var d
    try {
        d = JSON.parse(String(raw))
    } catch (e) {
        return null
    }
    if (!d || typeof d !== "object" || d.error || !d.device)
        return null
    var profiles = []
    var src = d.profiles || []
    for (var i = 0; i < src.length; i++)
        profiles.push({ key: src[i].key, description: src[i].description || "" })
    var streams = []
    var ss = d.streams || []
    for (var j = 0; j < ss.length; j++)
        streams.push({ app: ss[j].app, profile: ss[j].profile,
                       playing: !!ss[j].playing })
    return {
        status: {
            active: d.active || "",
            device: d.device.label || "",
            tag: d.device.tag || "",
            remembered: d.remembered || ""
        },
        profiles: profiles,
        streams: streams,
        autoswitch: !!d.autoswitch
    }
}

// `omarchy-eq ab list` prints two columns:
//     flat        no EQ - raw output (reference)
//     balanced    measured correction - general use | HPF200Hz -2.5@1000
function parseProfiles(raw) {
    var out = []
    if (!raw)
        return out
    var lines = String(raw).split("\n")
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim()
        if (line === "")
            continue
        var sp = line.indexOf(" ")
        if (sp < 0) {
            out.push({ key: line, description: "" })
            continue
        }
        var key = line.substring(0, sp)
        var rest = line.substring(sp).trim()
        // The description carries a " | <filters>" tail that is useful in a
        // terminal and just noise in a 360px popup.
        var bar = rest.indexOf(" | ")
        out.push({
            key: key,
            description: bar >= 0 ? rest.substring(0, bar).trim() : rest
        })
    }
    return out
}

// `omarchy-eq ab status` prints:
//     active: balanced
//       measured correction - general use | ...
//     device: Built-in Audio Analog Stereo (builtin)
//     remembered: balanced
function parseStatus(raw) {
    var st = { active: "", device: "", tag: "", remembered: "" }
    if (!raw)
        return st
    var lines = String(raw).split("\n")
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i]
        if (line.indexOf("active:") === 0)
            st.active = line.substring(7).trim()
        else if (line.indexOf("device:") === 0) {
            var d = line.substring(7).trim()
            var m = d.match(/^(.*)\s+\(([^)]+)\)$/)
            if (m) { st.device = m[1].trim(); st.tag = m[2] }
            else st.device = d
        } else if (line.indexOf("remembered:") === 0)
            st.remembered = line.substring(11).trim()
    }
    return st
}

// `omarchy-eq autoswitch status` prints "autoswitch : on" / "off".
function parseAutoswitch(raw) {
    if (!raw)
        return false
    return /^autoswitch\s*:\s*on\s*$/m.test(String(raw))
}

// `routing.py playing` prints: stream<TAB>app<TAB>profile<TAB>playing(0|1)
function parsePlaying(raw) {
    var out = []
    if (!raw)
        return out
    var lines = String(raw).split("\n")
    for (var i = 0; i < lines.length; i++) {
        var f = lines[i].split("\t")
        if (f.length < 4 || f[0] !== "stream")
            continue
        out.push({ app: f[1], profile: f[2], playing: f[3] === "1" })
    }
    return out
}

// What the bar shows.
//
// The default sink is the wrong answer whenever per-stream routing is doing its
// job: routing deliberately leaves the default alone and moves the audio
// instead, so a bar reading the default sits unchanged all day while the sound
// moves around behind it. That is indistinguishable from routing being broken,
// and it is exactly what it looked like.
//
// So: if something is actually playing, show where *that* is going. Fall back to
// the default only when nothing is.
function barLabel(active, streams) {
    var key = active
    var playing = (streams || []).filter(function (s) { return s.playing })
    if (playing.length > 0)
        key = playing[0].profile
    if (!key || key === "flat" || key === "unknown")
        return "󰃟"
    return "󰃟 " + prettyKey(key).toUpperCase()
}

// Fetched and imported profiles are keyed like `sennheiser_hd_650`.
function prettyKey(key) {
    return String(key || "").replace(/_/g, " ")
}
