import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "Model.js" as Model

// Bar widget: which EQ profile the current output is on, and a click to change it.
//
// The rows cannot be a fixed list. Profiles are per-device and open-ended --
// `flat` plus whatever was generated, imported or fetched -- so this asks
// `omarchy-eq ab list` what exists on whatever you are listening through now
// and renders that. Plugging in headphones changes the contents of this popup.
Panel {
  id: root
  moduleName: "local.omarchyeq"
  ipcTarget: "local.omarchyeq"

  property var profiles: []
  property var status: ({ active: "", device: "", tag: "", remembered: "" })
  property bool autoswitchOn: false
  property var streams: []
  property bool haveTool: true

  readonly property string barText: Model.barLabel(root.status.active, root.streams)
  readonly property string heroSubtitle: {
    if (!root.haveTool) return "omarchy-eq is not installed"
    if (!root.status.device) return "No output"
    var a = root.status.active
    return root.status.device + (a && a !== "unknown" ? " · " + Model.prettyKey(a) : "")
  }

  readonly property color hoverFill: bar
    ? Style.hoverFillFor(bar.foreground, Color.accent)
    : "transparent"
  readonly property color selectedFill: bar
    ? Style.selectedFillFor(bar.foreground, Color.accent)
    : "transparent"

  property int selectedIndex: 0
  property bool cursorActive: false

  function refresh() {
    if (!statusProc.running) statusProc.running = true
    if (!autoProc.running) autoProc.running = true
    if (!playingProc.running) playingProc.running = true
    if (opened && !listProc.running) listProc.running = true
  }

  function setProfile(key) {
    if (!key) return
    Quickshell.execDetached(["omarchy-eq", "ab", String(key)])
    refreshTimer.restart()
  }

  function toggleAutoswitch() {
    Quickshell.execDetached(["omarchy-eq-autoswitch", "toggle"])
    refreshTimer.restart()
  }

  function clampCursor() {
    if (profiles.length === 0) { selectedIndex = 0; return }
    if (selectedIndex > profiles.length - 1) selectedIndex = profiles.length - 1
    if (selectedIndex < 0) selectedIndex = 0
  }

  function moveCursor(delta) {
    if (profiles.length === 0) return
    selectedIndex = Math.max(0, Math.min(profiles.length - 1, selectedIndex + delta))
  }

  onOpenedChanged: {
    if (opened) {
      refresh()
      cursorActive = false
      clampCursor()
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: statusProc
    command: ["omarchy-eq", "ab", "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.status = Model.parseStatus(text)
        root.haveTool = String(text).trim() !== ""
      }
    }
  }

  Process {
    id: listProc
    command: ["omarchy-eq", "ab", "list"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: { root.profiles = Model.parseProfiles(text); root.clampCursor() }
    }
  }

  Process {
    id: playingProc
    command: ["omarchy-eq", "route", "playing"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.streams = Model.parsePlaying(text)
    }
  }

  Process {
    id: autoProc
    command: ["omarchy-eq", "autoswitch", "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.autoswitchOn = Model.parseAutoswitch(text)
    }
  }

  // Slow poll while closed: the label only has to be right, not instant. With
  // auto-switching on, the profile can change without anyone touching the bar.
  Timer {
    interval: 8000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Timer {
    interval: 3000
    running: root.opened
    repeat: true
    onTriggered: root.refresh()
  }

  // After a switch, re-read so the new active row lights up promptly.
  Timer {
    id: refreshTimer
    interval: 600
    repeat: false
    onTriggered: root.refresh()
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.barText
    tooltipText: "EQ profile"
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(520))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        if (dy !== 0) root.moveCursor(dy)
      }
      onActivateRequested: {
        if (root.cursorActive && root.profiles.length > 0)
          root.setProfile(root.profiles[root.selectedIndex].key)
      }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors.fill: parent
        spacing: Style.space(14)

        // ---------- Hero: current output and what it is playing through ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

          Text {
            id: heroIcon
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "󰃟"
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.display
            opacity: root.haveTool ? 1.0 : 0.5
          }

          Column {
            id: heroLabels
            anchors.left: heroIcon.right
            anchors.leftMargin: Style.space(14)
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              text: "Speaker EQ"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }

            Text {
              text: root.heroSubtitle.toUpperCase()
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 1.2
              elide: Text.ElideRight
              width: parent.width
            }
          }
        }

        PanelSeparator { foreground: root.bar.foreground }

        Text {
          visible: root.profiles.length === 0
          text: root.haveTool
            ? "No profiles for this output yet.\nRun: omarchy-eq calibrate (speakers)\nor: omarchy-eq fetch (headphones)"
            : "omarchy-eq is not on PATH"
          color: Qt.darker(root.bar.foreground, 1.5)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }

        Column {
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: root.profiles
            delegate: ProfileRow {
              required property var modelData
              required property int index
              width: column.width
              row: modelData
              rowIndex: index
            }
          }
        }

        PanelSeparator {
          foreground: root.bar.foreground
          visible: root.profiles.length > 0
        }

        // ---------- Where each app's audio is actually going ----------
        Column {
          width: parent.width
          spacing: Style.space(4)
          visible: root.streams.length > 0

          Text {
            text: "PLAYING THROUGH"
            color: Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 1.2
          }

          Repeater {
            model: root.streams
            delegate: Item {
              required property var modelData
              width: column.width
              implicitHeight: appName.implicitHeight

              Text {
                id: appName
                anchors.left: parent.left
                text: (modelData.playing ? "󰐊 " : "󰏤 ") + modelData.app
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
                opacity: modelData.playing ? 1.0 : 0.55
              }

              Text {
                anchors.right: parent.right
                text: Model.prettyKey(modelData.profile)
                color: Qt.darker(root.bar.foreground, 1.3)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
                opacity: modelData.playing ? 1.0 : 0.55
              }
            }
          }
        }

        PanelSeparator {
          foreground: root.bar.foreground
          visible: root.streams.length > 0
        }

        // ---------- Auto-switching toggle ----------
        CursorSurface {
          id: autoRow
          width: parent.width
          current: root.autoswitchOn
          foreground: root.bar.foreground
          fill: root.hoverFill
          currentFill: root.selectedFill
          implicitHeight: autoInner.implicitHeight + Style.spacing.xl

          Item {
            id: autoInner
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Style.space(6)
            anchors.rightMargin: Style.space(6)
            implicitHeight: Math.max(autoIcon.implicitHeight, autoLabel.implicitHeight)

            Text {
              id: autoIcon
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              text: root.autoswitchOn ? "󰄬" : "󰑓"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.body
              opacity: root.autoswitchOn ? 1.0 : 0.6
            }

            Text {
              id: autoLabel
              anchors.left: autoIcon.right
              anchors.leftMargin: Style.space(12)
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: root.autoswitchOn
                ? "Auto-switch per output · on"
                : "Auto-switch per output · off"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }
          }

          // CursorSurface draws the hover and selection states but emits
          // nothing -- pointer handling is the caller's job.
          MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.toggleAutoswitch()
          }
        }
      }
    }
  }

  component ProfileRow: CursorSurface {
    id: profileRow
    required property var row
    required property int rowIndex

    readonly property bool isActive: row && row.key === root.status.active
    hasCursor: root.cursorActive && root.selectedIndex === rowIndex
    current: isActive
    foreground: root.bar.foreground
    fill: root.hoverFill
    currentFill: root.selectedFill
    implicitHeight: rowInner.implicitHeight + Style.spacing.xl

    Item {
      id: rowInner
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(6)
      anchors.rightMargin: Style.space(6)
      implicitHeight: Math.max(iconText.implicitHeight, labels.implicitHeight)

      Text {
        id: iconText
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: profileRow.isActive ? "󰄬" : "󰋚"
        color: root.bar.foreground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.body
        opacity: profileRow.isActive ? 1.0 : 0.45
      }

      Column {
        id: labels
        anchors.left: iconText.right
        anchors.leftMargin: Style.space(12)
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(1)

        Text {
          text: Model.prettyKey(profileRow.row ? profileRow.row.key : "")
          color: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.bold: profileRow.isActive
          elide: Text.ElideRight
          width: parent.width
        }

        Text {
          visible: text !== ""
          text: profileRow.row ? String(profileRow.row.description || "") : ""
          color: Qt.darker(root.bar.foreground, 1.5)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
          width: parent.width
        }
      }
    }

    // Hovering moves the keyboard cursor too, so pointer and keyboard agree
    // about which row is selected.
    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onContainsMouseChanged: if (containsMouse) {
        root.cursorActive = true
        root.selectedIndex = profileRow.rowIndex
      }
      onClicked: root.setProfile(profileRow.row ? profileRow.row.key : "")
    }
  }
}
