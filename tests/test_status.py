"""The single document the bar widget reads.

`status.snapshot` exists to replace four separate CLI calls the Quickshell panel
used to make on a timer. Two things about it are worth pinning down with tests.

The first is that it must not re-derive anything. Every answer comes from the
module that already owns it -- devices, state, prefs, routing -- so there is
still exactly one implementation of "which device is active" and of "what am I
hearing". These tests patch those seams, which is only possible because the
seams are there.

The second is the `active` vs `default_profile` split, which is the whole reason
the panel needed a new command rather than a faster loop. Per-stream routing
deliberately does not move the default sink -- that is precisely what lets two
applications use two profiles at once -- so a bar reading the default sits
unchanged all day while the audio moves around behind it. That is
indistinguishable from routing being broken, and it is exactly what it looked
like before this was fixed.
"""
import unittest

import context  # noqa: F401
import devices
import prefs
import routing
import state
import status

BUILTIN = {
    "name": "alsa_output.pci-0000_00_1f.3.analog-stereo",
    "description": "Built-in Audio Analog Stereo",
    "kind": "builtin", "tag": "builtin", "measurable": True,
    "codec": "", "profile": "", "narrowband": False, "available": True,
}

# describe.summarise reads profile["filters"] and joins a " | " tail onto the
# description, which is the format the panel must not have to parse itself.
STORED = {"profiles": {
    "balanced": {
        "description": "measured correction - general use",
        "filters": [{"label": "bq_highpass", "control": {"Freq": 200}},
                    {"label": "bq_peaking",
                     "control": {"Freq": 3000, "Gain": 4.2}}],
    },
}}


class StatusCase(unittest.TestCase):
    """Patches every call that would otherwise need a live PipeWire."""

    default_sink = "eq_builtin_balanced"
    rows = []
    stored = STORED
    dev = BUILTIN

    def setUp(self):
        self._orig = {
            (devices, "listing"): devices.listing,
            (devices, "active"): devices.active,
            (devices, "find"): devices.find,
            (devices, "builtin"): devices.builtin,
            (devices, "default_sink"): devices.default_sink,
            (routing, "playing"): routing.playing,
            (prefs, "autoswitch"): prefs.autoswitch,
            (prefs, "remembered"): prefs.remembered,
            (state, "_read"): state._read,
        }
        devices.listing = lambda: [self.dev] if self.dev else []
        devices.active = lambda devs, default=None: self.dev
        devices.find = lambda devs, want: self.dev
        devices.builtin = lambda devs: self.dev
        devices.default_sink = lambda: self.default_sink
        routing.playing = lambda devs=None: list(self.rows)
        prefs.autoswitch = lambda: {"enabled": True, "fetch": False,
                                    "notify": True}
        prefs.remembered = lambda sink: "balanced"
        state._read = lambda path, default=None: self.stored

    def tearDown(self):
        for (mod, name), fn in self._orig.items():
            setattr(mod, name, fn)


class TestShape(StatusCase):
    def test_the_document_has_exactly_the_keys_the_panel_reads(self):
        # Adding a key is fine; renaming one silently breaks a bar that has
        # already shipped, because QML reads them by name and shows nothing.
        self.assertEqual(
            sorted(status.snapshot()),
            ["active", "autoswitch", "default_profile", "device", "profiles",
             "remembered", "streams"])

    def test_the_device_block_carries_what_the_hero_line_needs(self):
        dev = status.snapshot()["device"]
        self.assertEqual(sorted(dev),
                         ["kind", "label", "measurable", "name", "tag"])
        self.assertEqual(dev["label"], "Built-in Audio Analog Stereo")
        self.assertEqual(dev["tag"], "builtin")

    def test_remembered_is_a_string_even_when_nothing_is_remembered(self):
        prefs.remembered = lambda sink: None
        self.assertEqual(status.snapshot()["remembered"], "")


class TestProfiles(StatusCase):
    def test_flat_is_always_first_and_always_present(self):
        # It is the reference, not a stored profile -- an output with no
        # measurement and no preset still has somewhere to go.
        self.stored = {"profiles": {}}
        keys = [p["key"] for p in status.snapshot()["profiles"]]
        self.assertEqual(keys, ["flat"])

    def test_stored_profiles_follow_flat(self):
        keys = [p["key"] for p in status.snapshot()["profiles"]]
        self.assertEqual(keys, ["flat", "balanced"])

    def test_every_profile_has_the_same_three_fields(self):
        for p in status.snapshot()["profiles"]:
            with self.subTest(key=p["key"]):
                self.assertEqual(sorted(p), ["description", "filters", "key"])

    def test_the_filter_tail_is_split_off_rather_than_left_in_the_text(self):
        # `ab list` prints "<description> | <filters>" because a terminal has
        # room for it. A 360px popup does not, and QML should not be splitting
        # a display format it does not own.
        p = [x for x in status.snapshot()["profiles"] if x["key"] == "balanced"][0]
        self.assertEqual(p["description"], "measured correction - general use")
        self.assertNotIn("|", p["description"])
        self.assertIn("HPF200Hz", p["filters"])


class TestActiveVersusDefault(StatusCase):
    """The distinction the bar exists to show."""

    def test_a_playing_stream_wins_over_the_default_sink(self):
        self.default_sink = "eq_builtin_music"
        self.rows = ["stream\tFirefox\tvoice\t1"]
        snap = status.snapshot()
        self.assertEqual(snap["active"], "voice")
        self.assertEqual(snap["default_profile"], "music")

    def test_with_nothing_playing_the_default_is_the_answer(self):
        self.default_sink = "eq_builtin_music"
        self.rows = []
        self.assertEqual(status.snapshot()["active"], "music")

    def test_a_corked_stream_does_not_win(self):
        # A paused Spotify should not pin the bar to whatever it last used.
        self.default_sink = "eq_builtin_music"
        self.rows = ["stream\tSpotify\tvoice\t0"]
        self.assertEqual(status.snapshot()["active"], "music")

    def test_a_default_sink_that_is_not_ours_reads_as_flat(self):
        # The raw hardware sink is the "no EQ" case, not an unknown one.
        self.default_sink = BUILTIN["name"]
        self.rows = []
        self.assertEqual(status.snapshot()["active"], "flat")

    def test_streams_are_reported_with_their_playing_state(self):
        self.rows = ["stream\tSpotify\tmusic\t1", "stream\tZen\tvoice\t0"]
        self.assertEqual(status.snapshot()["streams"], [
            {"app": "Spotify", "profile": "music", "playing": True},
            {"app": "Zen", "profile": "voice", "playing": False},
        ])


class TestUnresolvableDevice(StatusCase):
    def test_an_unknown_device_is_an_error_document_not_a_half_built_one(self):
        # The panel tests for `device` before rendering. A snapshot that
        # answered with an empty device block would draw an empty bar and give
        # no reason for it.
        devices.find = lambda devs, want: None
        snap = status.snapshot("nonexistent")
        self.assertIn("error", snap)
        self.assertNotIn("device", snap)


if __name__ == "__main__":
    unittest.main()
