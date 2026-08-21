.pragma library

// Parsing for the EQ bar widget. Kept out of the QML so it can be reasoned
// about (and changed) without touching layout code.
//
// Everything here reads `omarchy-eq`'s own output rather than its state files.
// The files are JSON and would be easier to parse, but they are private layout
// that has already changed once; the CLI's output is the part with users.

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

// What the bar shows. A profile name is more useful than an icon alone, but
// only when it says something: "flat" means no EQ is doing anything, so the
// bare icon is the honest signal there.
function barLabel(active) {
    if (!active || active === "flat" || active === "unknown")
        return "󰃟"
    return "󰃟 " + prettyKey(active).toUpperCase()
}

// Fetched and imported profiles are keyed like `sennheiser_hd_650`.
function prettyKey(key) {
    return String(key || "").replace(/_/g, " ")
}
