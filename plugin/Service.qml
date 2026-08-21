import QtQuick
import Quickshell
import Quickshell.Io

// Headless service for the Speaker EQ plugin.
//
// It does exactly one thing: re-assert the wiring a previous explicit
// `install.sh` run established -- the ~/.local/bin shims, the omarchy-menu
// entries, and the Hyprland keybinding fragment. That wiring lives in files
// this plugin does not own (a shared menu file, the user's bindings.lua), so
// it can drift when the user edits them or when the plugin is updated.
//
// `install.sh --wire-only` refuses to touch anything unless the install marker
// at ~/.local/state/omarchy-eq/plugin.wired exists, and exits without writing
// when everything is already in sync. That makes running it at every shell
// start both safe and nearly free -- and means a user who has never run the
// installer never gets their menu file rewritten behind their back.
Item {
    id: root

    function pluginDir() {
        var path = Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")
        if (path.charAt(path.length - 1) !== "/") path += "/"
        return path
    }

    Process {
        id: wire
        stdout: StdioCollector { id: wireOut; waitForEnd: true }
        stderr: StdioCollector { id: wireErr; waitForEnd: true }
        onExited: function (code) {
            if (code !== 0)
                console.warn("jackzasian.eq: wiring exited", code, wireErr.text)
            else if (wireOut.text.trim())
                console.log("jackzasian.eq:", wireOut.text.trim())
        }
    }

    Component.onCompleted: {
        wire.command = ["bash", root.pluginDir() + "install.sh", "--wire-only"]
        wire.running = true
    }
}
