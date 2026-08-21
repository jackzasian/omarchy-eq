"""Per-stream routing: which profile each playing stream belongs on.

The classifier is the part worth testing hard. It runs unattended and moves
audio around, so the tests are mostly about what it declines to touch.
"""
import os
import shutil
import tempfile
import unittest

import context  # noqa: F401
import routing

SINK_INPUTS = """Sink Input #41
\tDriver: PipeWire
\tSink: 74
\tmedia.name = "Built-in Audio: Balanced"
\tnode.name = "eq_builtin_balanced_out"
\tmedia.class = "Stream/Output/Audio"
Sink Input #3836
\tDriver: PipeWire
\tSink: 40
\tmedia.role = "music"
\tmedia.name = "Spotify"
\tnode.name = "spotify"
\tapplication.name = "Spotify"
Sink Input #3918
\tDriver: PipeWire
\tSink: 40
\tapplication.name = "Zen"
\tapplication.process.binary = "zen-bin"
"""

SHORT_SINKS = (
    "40\teq_builtin_balanced\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING\n"
    "43\teq_builtin_music\tPipeWire\tfloat32le 2ch 48000Hz\tSUSPENDED\n"
    "74\talsa_output.pci-0000_00_1f.3.analog-stereo\tPipeWire\ts32le\tRUNNING\n")


def stream(app="", role="", binary="", index="1", sink="40"):
    props = {}
    if app:
        props["application.name"] = app
    if role:
        props["media.role"] = role
    if binary:
        props["application.process.binary"] = binary
    return {"index": index, "sink": sink, "props": props}


class RoutingCase(unittest.TestCase):
    """Each test gets its own state dir: settings() reads config.json."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.tmp
        self.conf = routing.settings()

    def tearDown(self):
        if self.old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestParsing(unittest.TestCase):
    def test_reads_index_sink_and_properties(self):
        got = routing.parse_sink_inputs(SINK_INPUTS)
        self.assertEqual([s["index"] for s in got], ["41", "3836", "3918"])
        self.assertEqual(got[1]["props"]["application.name"], "Spotify")

    def test_the_sink_field_is_an_index_not_a_name(self):
        # Getting this wrong is silent: every name comparison simply never
        # matches and nothing is ever routed.
        got = routing.parse_sink_inputs(SINK_INPUTS)
        self.assertEqual(got[1]["sink"], "40")
        self.assertTrue(got[1]["sink"].isdigit())


class TestClassify(RoutingCase):
    def test_spotify_playing_a_song_gets_the_music_curve(self):
        key, _ = routing.classify(stream("Spotify"), self.conf, "music")
        self.assertEqual(key, "music")

    def test_spotify_playing_a_podcast_gets_the_speech_curve(self):
        # A song and an episode are the same stream with identical properties;
        # only the MPRIS track id tells them apart.
        key, why = routing.classify(stream("Spotify"), self.conf, "voice")
        self.assertEqual(key, "voice")
        self.assertIn("podcast", why)

    def test_content_beats_the_app_rule(self):
        key, _ = routing.classify(stream("Spotify", role="music"),
                                  self.conf, "voice")
        self.assertEqual(key, "voice", "the app rule must not override what is "
                                       "actually playing")

    def test_falls_back_to_the_app_rule_when_mpris_says_nothing(self):
        key, why = routing.classify(stream("Spotify"), self.conf, None)
        self.assertEqual(key, "music")
        self.assertIn("app rule", why)

    def test_an_app_rule_matches_the_process_binary_too(self):
        key, _ = routing.classify(stream("Media Player", binary="mpv"), self.conf)
        self.assertEqual(key, "voice")

    def test_media_role_is_used_when_no_app_rule_matches(self):
        key, why = routing.classify(stream("Anything", role="phone"), self.conf)
        self.assertEqual(key, "voice")
        self.assertIn("media.role", why)

    def test_an_unrecognised_app_is_left_alone(self):
        key, _ = routing.classify(stream("SomeGame"), self.conf)
        self.assertIsNone(key)

    def test_notification_blips_are_left_alone(self):
        # `event` is a system beep. Correcting it is meaningless and moving it
        # between sinks just makes it late.
        key, _ = routing.classify(stream("notify", role="event"), self.conf)
        self.assertIsNone(key)

    def test_pro_audio_is_left_alone(self):
        key, _ = routing.classify(stream("ardour", role="production"), self.conf)
        self.assertIsNone(key)

    def test_content_is_ignored_for_apps_that_are_not_spotify(self):
        key, _ = routing.classify(stream("Zen", binary="zen-bin"),
                                  self.conf, "voice")
        self.assertIsNone(key, "a browser must not inherit Spotify's content")


class TestRules(RoutingCase):
    def test_a_user_rule_overrides_the_built_in_one(self):
        routing.set_app_rule("spotify", "voice")
        key, _ = routing.classify(stream("Spotify"), routing.settings(), None)
        self.assertEqual(key, "voice")

    def test_a_user_rule_can_exempt_an_app(self):
        # Exempting is not the same as removing: removing restores the built-in
        # rule, which for Spotify is exactly what you were trying to stop.
        routing.set_app_rule("spotify", routing.EXEMPT)
        key, _ = routing.classify(stream("Spotify"), routing.settings(), None)
        self.assertIsNone(key)

    def test_removing_a_rule_restores_the_built_in(self):
        routing.set_app_rule("spotify", "voice")
        routing.set_app_rule("spotify", None)
        key, _ = routing.classify(stream("Spotify"), routing.settings(), None)
        self.assertEqual(key, "music")

    def test_routing_is_off_until_asked_for(self):
        self.assertFalse(routing.settings()["enabled"])

    def test_content_inspection_can_be_turned_off(self):
        routing.set_routing(content=False)
        conf = routing.settings()
        self.assertFalse(conf["content"])
        # With content off, Spotify falls back to the plain app rule.
        key, why = routing.classify(stream("Spotify"), conf, "voice")
        self.assertEqual(key, "music")
        self.assertIn("app rule", why)


class TestSpotifyContent(unittest.TestCase):
    def test_an_episode_track_id_reads_as_speech(self):
        for trackid in ("/com/spotify/episode/4aBxY", "spotify:episode:4aBxY"):
            self.assertEqual(routing._content_from_trackid(trackid), "voice")

    def test_a_song_track_id_reads_as_music(self):
        for trackid in ("/com/spotify/track/1IF5Ucq", "spotify:track:1IF5Ucq"):
            self.assertEqual(routing._content_from_trackid(trackid), "music")

    def test_an_unrecognised_track_id_says_nothing(self):
        self.assertIsNone(routing._content_from_trackid("/com/spotify/ad/xyz"))
        self.assertIsNone(routing._content_from_trackid(""))


if __name__ == "__main__":
    unittest.main()
