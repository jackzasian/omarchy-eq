import os
import tempfile
import unittest

import context  # noqa: F401
import autoswitch
import prefs
import state

BUILTIN = {"name": "alsa_output.pci-0000_00_1f.3.analog-stereo", "tag": "builtin",
           "description": "Built-in Audio Analog Stereo", "kind": "builtin",
           "measurable": True, "narrowband": False}
A2DP = {"name": "bluez_output.3C_B0_ED_50_8A_E6.1", "tag": "bt8ae6",
        "description": "Nothing Ear (open)", "kind": "headphones",
        "measurable": False, "narrowband": False}
HSP = dict(A2DP, name="bluez_output.3C_B0_ED_50_8A_E6.2", tag="bt8ae6hs",
           narrowband=True)


def profiles(*keys):
    return {k: {"description": k, "filters": []} for k in keys}


class TestChoose(unittest.TestCase):
    """choose() is the whole judgement of the watcher, kept pure so that
    'what would it do?' can be asked without a running PipeWire."""

    def test_a_remembered_profile_wins_over_every_default(self):
        # Plugging the same headphones in twice must not need the same
        # correction picked twice.
        key, why = autoswitch.choose(A2DP, profiles("balanced", "music"), "music")
        self.assertEqual(key, "music")
        self.assertIn("you last chose", why)

    def test_flat_is_a_choice_and_is_honoured(self):
        # "Leave this output alone" is a real preference, not the absence of
        # one, so it must not fall through to balanced.
        key, why = autoswitch.choose(A2DP, profiles("balanced"), "flat")
        self.assertEqual(key, autoswitch.FLAT)
        self.assertIn("flat", why)

    def test_flat_is_honoured_even_when_the_device_has_no_profiles(self):
        key, _ = autoswitch.choose(A2DP, {}, "flat")
        self.assertEqual(key, autoswitch.FLAT)

    def test_a_remembered_profile_that_is_gone_falls_through_to_the_default(self):
        key, _ = autoswitch.choose(A2DP, profiles("balanced", "music"), "vintage")
        self.assertEqual(key, "balanced")

    def test_and_says_that_it_is_gone_rather_than_switching_silently(self):
        # `generate` can rename or drop a profile; landing somewhere else
        # without explanation reads as the EQ having lost your setting.
        _, why = autoswitch.choose(A2DP, profiles("balanced"), "vintage")
        self.assertIn("'vintage' no longer exists", why)

    def test_a_narrowband_link_prefers_voice_over_balanced(self):
        # HSP/HFP is 8 or 16 kHz mono. A curve fitted to the A2DP measurement
        # is boosting treble the link never transmits.
        key, _ = autoswitch.choose(HSP, profiles("balanced", "music", "voice"), None)
        self.assertEqual(key, "voice")

    def test_the_narrowband_reason_explains_itself(self):
        _, why = autoswitch.choose(HSP, profiles("balanced", "voice"), None)
        self.assertIn("call profile", why)
        self.assertIn("mono", why)

    def test_a_wideband_device_prefers_balanced_over_voice(self):
        key, _ = autoswitch.choose(A2DP, profiles("balanced", "music", "voice"), None)
        self.assertEqual(key, "balanced")

    def test_music_is_the_second_choice_when_there_is_no_balanced(self):
        key, _ = autoswitch.choose(A2DP, profiles("music", "voice"), None)
        self.assertEqual(key, "music")

    def test_voice_is_the_last_of_the_known_names(self):
        key, _ = autoswitch.choose(A2DP, profiles("voice"), None)
        self.assertEqual(key, "voice")

    def test_a_remembered_choice_beats_the_narrowband_preference(self):
        key, _ = autoswitch.choose(HSP, profiles("balanced", "voice"), "balanced")
        self.assertEqual(key, "balanced")

    def test_an_imported_preset_under_any_name_is_still_used(self):
        # AutoEQ presets are named after the product, so none of the known
        # names match; picking alphabetically is at least deterministic.
        key, why = autoswitch.choose(A2DP, profiles("sennheiser", "moondrop"), None)
        self.assertEqual(key, "moondrop")
        self.assertIn("moondrop", why)

    def test_a_narrowband_device_with_only_unknown_names_still_gets_one(self):
        key, _ = autoswitch.choose(HSP, profiles("sennheiser"), None)
        self.assertEqual(key, "sennheiser")

    def test_a_device_with_no_profiles_is_left_flat_and_told_why(self):
        key, why = autoswitch.choose(A2DP, {}, None)
        self.assertEqual(key, autoswitch.FLAT)
        self.assertIn("no profiles", why)

    def test_a_device_with_no_profiles_and_a_stale_memory_says_both(self):
        _, why = autoswitch.choose(A2DP, {}, "vintage")
        self.assertIn("'vintage' no longer exists", why)
        self.assertIn("no profiles", why)

    def test_no_choice_yet_is_reported_as_such(self):
        _, why = autoswitch.choose(A2DP, profiles("balanced"), None)
        self.assertIn("no choice recorded yet", why)


class DecideCase(unittest.TestCase):
    """decide() reads real state, so it gets a temporary XDG_STATE_HOME, and
    the device listing is stubbed instead of asking PipeWire."""

    def setUp(self):
        self.saved_state = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
        self.saved_listing = autoswitch.devmod.listing
        self.devices = [BUILTIN, A2DP]
        autoswitch.devmod.listing = lambda: list(self.devices)

    def tearDown(self):
        autoswitch.devmod.listing = self.saved_listing
        if self.saved_state is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.saved_state

    def install(self, dev, *keys):
        state._write(state.profiles_path(dev["name"]), {"profiles": profiles(*keys)})

    def field(self, rows, key):
        for row in rows:
            parts = row.split("\t")
            if parts[0] == key or (parts[0] == "device" and parts[1] == key):
                return parts[-1]
        return None


class TestDecide(DecideCase):
    def test_switching_to_the_eq_sink_is_asked_for_when_needed(self):
        self.install(BUILTIN, "balanced")
        rows = autoswitch.decide("builtin", BUILTIN["name"])
        self.assertEqual(self.field(rows, "action"), "switch")
        self.assertEqual(self.field(rows, "target"), "eq_builtin_balanced")

    def test_being_already_on_the_target_is_a_no_op(self):
        # PipeWire emits a default-sink event for our own set-default-sink, so
        # a decide() that said "switch" here would make the watcher chase its
        # own tail forever.
        self.install(BUILTIN, "balanced")
        rows = autoswitch.decide("builtin", "eq_builtin_balanced")
        self.assertEqual(self.field(rows, "action"), "none")
        self.assertIn("already on", self.field(rows, "reason"))

    def test_deciding_twice_in_a_row_is_stable(self):
        self.install(BUILTIN, "balanced")
        first = autoswitch.decide("builtin", BUILTIN["name"])
        second = autoswitch.decide("builtin", self.field(first, "target"))
        self.assertEqual(self.field(second, "action"), "none")

    def test_a_remembered_profile_is_read_back_from_the_config(self):
        self.install(BUILTIN, "balanced", "music")
        prefs.remember(BUILTIN["name"], "music")
        rows = autoswitch.decide("builtin", BUILTIN["name"])
        self.assertEqual(self.field(rows, "profile"), "music")
        self.assertEqual(self.field(rows, "target"), "eq_builtin_music")

    def test_a_measurable_device_with_no_profiles_is_pointed_at_calibrate(self):
        rows = autoswitch.decide("builtin", BUILTIN["name"])
        self.assertEqual(self.field(rows, "action"), "none")
        self.assertEqual(self.field(rows, "profile"), autoswitch.FLAT)
        self.assertEqual(self.field(rows, "target"), BUILTIN["name"])
        self.assertIn("calibrate", self.field(rows, "reason"))

    def test_headphones_with_no_profiles_suggest_auto_setup_when_it_is_off(self):
        rows = autoswitch.decide("bt8ae6", A2DP["name"])
        self.assertEqual(self.field(rows, "action"), "none")
        self.assertIn("auto-setup", self.field(rows, "reason"))

    def test_headphones_with_no_profiles_trigger_a_lookup_when_fetch_is_on(self):
        prefs.set_autoswitch(fetch=True)
        rows = autoswitch.decide("bt8ae6", A2DP["name"])
        self.assertEqual(self.field(rows, "action"), "setup")

    def test_the_active_device_is_used_when_no_device_is_named(self):
        self.install(A2DP, "balanced")
        rows = autoswitch.decide(None, A2DP["name"])
        self.assertEqual(self.field(rows, "name"), A2DP["name"])

    def test_the_active_device_is_seen_through_our_own_eq_sink(self):
        self.install(A2DP, "balanced")
        rows = autoswitch.decide("active", "eq_bt8ae6_balanced")
        self.assertEqual(self.field(rows, "tag"), "bt8ae6")
        self.assertEqual(self.field(rows, "action"), "none")

    def test_narrowband_is_reported_as_a_flag_for_the_shell_side(self):
        self.devices = [BUILTIN, HSP]
        rows = autoswitch.decide("bt8ae6hs", HSP["name"])
        self.assertEqual(self.field(rows, "narrowband"), "1")
        self.assertEqual(autoswitch.decide("builtin", BUILTIN["name"])[4],
                         "device\tnarrowband\t0")

    def test_an_unknown_device_is_an_error_row_not_an_exception(self):
        rows = autoswitch.decide("nosuchthing", BUILTIN["name"])
        self.assertTrue(rows[0].startswith("error\t"))

    def test_no_outputs_at_all_is_an_error_row(self):
        self.devices = []
        self.assertEqual(autoswitch.decide("builtin", ""), ["error\tno output devices"])


class TestSinkNaming(unittest.TestCase):
    def test_the_eq_sink_name_matches_what_render_emits(self):
        import render
        self.assertEqual(autoswitch.eq_sink("bt8ae6hs", "voice"),
                         render.sink_name("bt8ae6hs", "voice"))


if __name__ == "__main__":
    unittest.main()
