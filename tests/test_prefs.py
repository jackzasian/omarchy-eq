import json
import os
import tempfile
import unittest

import context  # noqa: F401
import prefs
import state

SPK = "alsa_output.pci-0000_00_1f.3.analog-stereo"
BT = "bluez_output.3C_B0_ED_50_8A_E6.1"


class PrefsCase(unittest.TestCase):
    """Every test gets its own XDG_STATE_HOME, so none of this touches the real
    config.json -- these tests would otherwise rewrite the developer's own
    remembered profiles."""

    def setUp(self):
        self.saved = os.environ.get("XDG_STATE_HOME")
        self.tmp = tempfile.mkdtemp()
        os.environ["XDG_STATE_HOME"] = self.tmp

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.saved

    def corrupt(self, text):
        os.makedirs(state.state_root(), exist_ok=True)
        with open(state.config_path(), "w") as fh:
            fh.write(text)

    def raw(self):
        with open(state.config_path()) as fh:
            return json.load(fh)


class TestIsolation(PrefsCase):
    def test_the_config_path_follows_the_environment_at_call_time(self):
        # state_root() re-reads XDG_STATE_HOME on every access rather than
        # caching it at import. That is the only reason setting the variable in
        # setUp -- long after `import prefs` -- redirects anything at all.
        first = state.config_path()
        os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
        self.assertNotEqual(first, state.config_path())

    def test_writes_land_under_the_temporary_state_home(self):
        prefs.remember(SPK, "balanced")
        self.assertTrue(state.config_path().startswith(self.tmp))
        self.assertTrue(os.path.exists(state.config_path()))


class TestRemembering(PrefsCase):
    def test_a_remembered_profile_round_trips(self):
        prefs.remember(SPK, "music")
        self.assertEqual(prefs.remembered(SPK), "music")

    def test_devices_do_not_collide_with_each_other(self):
        # One config file holds every output; the device key is what keeps the
        # laptop speakers from inheriting the headphones' correction.
        prefs.remember(SPK, "balanced")
        prefs.remember(BT, "music")
        self.assertEqual(prefs.remembered(SPK), "balanced")
        self.assertEqual(prefs.remembered(BT), "music")
        self.assertEqual(len(prefs.all_devices()), 2)

    def test_a_second_choice_replaces_the_first(self):
        prefs.remember(SPK, "balanced")
        prefs.remember(SPK, "voice")
        self.assertEqual(prefs.remembered(SPK), "voice")

    def test_an_unknown_device_has_no_memory(self):
        self.assertIsNone(prefs.remembered("bluez_output.NOPE.1"))
        self.assertEqual(prefs.device("bluez_output.NOPE.1"), {})

    def test_a_human_choice_is_pinned(self):
        prefs.remember(SPK, "music")
        self.assertTrue(prefs.device(SPK)["pinned"])

    def test_an_unpinned_write_records_that_nobody_chose_it(self):
        # Auto-setup landed here; it must be distinguishable from a real choice.
        prefs.remember(SPK, "autoeq", pinned=False)
        self.assertFalse(prefs.device(SPK)["pinned"])

    def test_an_unpinned_write_never_clears_an_existing_pin(self):
        # Auto-setup runs behind your back. If it could unpin, the next run
        # would feel free to override a profile you deliberately picked.
        prefs.remember(SPK, "music")
        prefs.remember(SPK, "autoeq", pinned=False)
        self.assertTrue(prefs.device(SPK)["pinned"])

    def test_a_pinned_write_does_overwrite_an_unpinned_one(self):
        prefs.remember(SPK, "autoeq", pinned=False)
        prefs.remember(SPK, "music")
        self.assertEqual(prefs.remembered(SPK), "music")
        self.assertTrue(prefs.device(SPK)["pinned"])

    def test_forget_drops_only_the_device_asked_for(self):
        prefs.remember(SPK, "balanced")
        prefs.remember(BT, "music")
        self.assertTrue(prefs.forget(SPK))
        self.assertIsNone(prefs.remembered(SPK))
        self.assertEqual(prefs.remembered(BT), "music")

    def test_forgetting_an_unknown_device_reports_that_it_did_nothing(self):
        self.assertFalse(prefs.forget(SPK))

    def test_all_devices_is_a_copy_the_caller_cannot_corrupt(self):
        prefs.remember(SPK, "balanced")
        prefs.all_devices().clear()
        self.assertEqual(prefs.remembered(SPK), "balanced")


class TestDefaults(PrefsCase):
    def test_a_missing_file_reads_as_the_defaults(self):
        self.assertFalse(os.path.exists(state.config_path()))
        self.assertEqual(prefs.autoswitch(), prefs.DEFAULT_AUTOSWITCH)
        self.assertEqual(prefs.all_devices(), {})

    def test_autoswitch_is_off_until_it_is_turned_on(self):
        # Nothing may start re-routing audio because omarchy-eq was installed.
        self.assertFalse(prefs.autoswitch()["enabled"])
        self.assertFalse(prefs.autoswitch()["fetch"])

    def test_a_corrupt_file_degrades_to_the_defaults_rather_than_raising(self):
        # A half-written config must not take the watcher -- or the menu -- down
        # with it; forgetting your choices is recoverable, a traceback is not.
        self.corrupt("{ not json at all")
        self.assertEqual(prefs.autoswitch(), prefs.DEFAULT_AUTOSWITCH)
        self.assertIsNone(prefs.remembered(SPK))
        self.assertEqual(prefs.all_devices(), {})

    def test_a_file_holding_the_wrong_shape_also_degrades(self):
        self.corrupt("[1, 2, 3]")
        self.assertEqual(prefs.autoswitch(), prefs.DEFAULT_AUTOSWITCH)
        self.assertEqual(prefs.all_devices(), {})

    def test_a_corrupt_file_is_replaced_by_the_next_write(self):
        self.corrupt("garbage")
        prefs.remember(SPK, "music")
        self.assertEqual(prefs.remembered(SPK), "music")
        self.assertEqual(self.raw()["devices"][state.device_key(SPK)]["profile"],
                         "music")

    def test_the_autoswitch_defaults_are_filled_in_around_a_partial_file(self):
        prefs.set_autoswitch(enabled=True)
        conf = prefs.autoswitch()
        self.assertEqual(sorted(conf), sorted(prefs.DEFAULT_AUTOSWITCH))


class TestAutoswitchSettings(PrefsCase):
    def test_a_setting_round_trips(self):
        prefs.set_autoswitch(enabled=True)
        self.assertTrue(prefs.autoswitch()["enabled"])

    def test_only_the_keys_passed_are_touched(self):
        prefs.set_autoswitch(fetch=True)
        prefs.set_autoswitch(enabled=True)
        conf = prefs.autoswitch()
        self.assertTrue(conf["fetch"])
        self.assertTrue(conf["enabled"])
        self.assertTrue(conf["notify"])       # never passed, keeps its default

    def test_a_setting_can_be_turned_back_off(self):
        prefs.set_autoswitch(notify=True)
        prefs.set_autoswitch(notify=False)
        self.assertFalse(prefs.autoswitch()["notify"])

    def test_set_autoswitch_returns_the_whole_settings_block(self):
        self.assertEqual(prefs.set_autoswitch(enabled=True), prefs.autoswitch())

    def test_an_unknown_key_is_refused_rather_than_stored(self):
        # A typo would otherwise become a new key that reads back as the
        # default forever -- the kind of setting bug that costs an hour.
        with self.assertRaises(ValueError):
            prefs.set_autoswitch(enabeld=True)

    def test_a_refused_key_leaves_the_existing_settings_alone(self):
        prefs.set_autoswitch(enabled=True)
        with self.assertRaises(ValueError):
            prefs.set_autoswitch(fetch=True, notfiy=False)
        conf = prefs.autoswitch()
        self.assertTrue(conf["enabled"])
        self.assertFalse(conf["fetch"])       # the whole call was rejected

    def test_settings_and_device_choices_share_one_file_without_clobbering(self):
        prefs.remember(SPK, "music")
        prefs.set_autoswitch(enabled=True)
        self.assertEqual(prefs.remembered(SPK), "music")
        self.assertTrue(prefs.autoswitch()["enabled"])


if __name__ == "__main__":
    unittest.main()
