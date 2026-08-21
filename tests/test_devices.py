import subprocess
import types
import unittest

import context  # noqa: F401
import devices

PACTL = """Sink #70
	Name: alsa_output.pci-0000_00_1f.3.analog-stereo
	Description: Built-in Audio Analog Stereo
		device.bus = "pci"
		device.form_factor = "internal"
Sink #155
	Name: bluez_output.3C_B0_ED_50_8A_E6.1
	Description: Nothing Ear (open)
		api.bluez5.codec = "aac"
		api.bluez5.address = "3C:B0:ED:50:8A:E6"
		device.bus = "bluetooth"
		device.form_factor = "headset"
Sink #172
	Name: sonos_stream
	Description: Sonos Roam
Sink #48
	Name: eq_builtin_balanced
	Description: Built-in Audio: Balanced
"""


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.d = devices.parse(PACTL)
        self.by = {x["tag"]: x for x in self.d}

    def test_our_own_eq_sinks_are_never_devices(self):
        # Otherwise apply would render an EQ for the EQ.
        self.assertNotIn("eq_builtin_balanced", [x["name"] for x in self.d])
        self.assertEqual(len(self.d), 3)

    def test_internal_form_factor_is_a_measurable_builtin(self):
        self.assertEqual(self.by["builtin"]["kind"], "builtin")
        self.assertTrue(self.by["builtin"]["measurable"])

    def test_headset_is_not_measurable(self):
        # The laptop microphone cannot hear headphones.
        self.assertEqual(self.by["bt8ae6"]["kind"], "headphones")
        self.assertFalse(self.by["bt8ae6"]["measurable"])

    def test_network_sink_is_not_measurable(self):
        # Buffering puts the tone outside the recording window.
        self.assertFalse(self.by["sonosstrea"]["measurable"])
        self.assertEqual(self.by["sonosstrea"]["kind"], "stream")

    def test_bluetooth_tag_comes_from_the_address(self):
        self.assertEqual(self.by["bt8ae6"]["tag"], "bt8ae6")

    def test_codec_is_reported(self):
        self.assertEqual(self.by["bt8ae6"]["codec"], "aac")

    def test_tags_are_unique(self):
        tags = [x["tag"] for x in self.d]
        self.assertEqual(len(tags), len(set(tags)))

    def test_duplicate_tags_get_disambiguated(self):
        two = devices.parse(PACTL + PACTL.replace("Sink #155", "Sink #156"))
        tags = [x["tag"] for x in two]
        self.assertEqual(len(tags), len(set(tags)))


class TestResolution(unittest.TestCase):
    def setUp(self):
        self.d = devices.parse(PACTL)

    def test_builtin_is_preferred_for_measurement(self):
        self.assertEqual(devices.builtin(self.d)["tag"], "builtin")

    def test_active_sees_through_our_own_eq_sink(self):
        a = devices.active(self.d, "eq_builtin_music")
        self.assertEqual(a["name"], "alsa_output.pci-0000_00_1f.3.analog-stereo")

    def test_active_resolves_a_plain_hardware_sink(self):
        a = devices.active(self.d, "bluez_output.3C_B0_ED_50_8A_E6.1")
        self.assertEqual(a["tag"], "bt8ae6")

    def test_active_falls_back_to_builtin_for_an_unknown_sink(self):
        self.assertEqual(devices.active(self.d, "nope")["tag"], "builtin")

    def test_find_by_tag_name_and_description(self):
        for want in ("bt8ae6", "bluez_output.3C_B0_ED_50_8A_E6.1", "Nothing"):
            self.assertEqual(devices.find(self.d, want)["tag"], "bt8ae6")

    def test_find_returns_none_for_an_ambiguous_substring(self):
        self.assertIsNone(devices.find(self.d, "zzzz"))


if __name__ == "__main__":
    unittest.main()


A2DP = """Sink #155
	Name: bluez_output.3C_B0_ED_50_8A_E6.1
	Description: Nothing Ear (open)
		api.bluez5.codec = "aac"
		api.bluez5.profile = "a2dp-sink"
		api.bluez5.address = "3C:B0:ED:50:8A:E6"
		device.bus = "bluetooth"
		device.form_factor = "headset"
"""
HSP = """Sink #156
	Name: bluez_output.3C_B0_ED_50_8A_E6.2
	Description: Nothing Ear (open)
		api.bluez5.codec = "msbc"
		api.bluez5.profile = "headset-head-unit"
		api.bluez5.address = "3C:B0:ED:50:8A:E6"
		device.bus = "bluetooth"
		device.form_factor = "headset"
"""


class TestBluetoothProfiles(unittest.TestCase):
    """One headset is not one output. A2DP is a wideband stereo sink; the call
    profile is a separate mono sink at 8 or 16 kHz, with its own response."""

    def setUp(self):
        self.by = {d["name"]: d for d in devices.parse(A2DP + HSP)}
        self.a2dp = self.by["bluez_output.3C_B0_ED_50_8A_E6.1"]
        self.hsp = self.by["bluez_output.3C_B0_ED_50_8A_E6.2"]

    def test_the_call_profile_is_narrowband(self):
        self.assertTrue(self.hsp["narrowband"])

    def test_a2dp_is_not_narrowband(self):
        # Correcting a wideband link with a curve fitted for 16 kHz mono would
        # be as wrong as the other way round.
        self.assertFalse(self.a2dp["narrowband"])

    def test_the_bluez_profile_is_reported(self):
        self.assertEqual(self.a2dp["profile"], "a2dp-sink")
        self.assertEqual(self.hsp["profile"], "headset-head-unit")

    def test_the_two_profiles_of_one_headset_get_different_tags(self):
        self.assertNotEqual(self.a2dp["tag"], self.hsp["tag"])

    def test_a2dp_keeps_the_bare_address_tag(self):
        # No suffix for the common case, so tags minted before per-profile
        # sinks existed -- and whatever the user bound to a key -- keep working.
        self.assertEqual(self.a2dp["tag"], "bt8ae6")
        self.assertEqual(self.hsp["tag"], "bt8ae6hs")

    def test_the_tags_do_not_depend_on_the_order_the_sinks_appear_in(self):
        # The bug the suffix fixes: the uniquing counter handed out bt8ae6 and
        # bt8ae62 in whatever order BlueZ happened to publish the two profiles,
        # so a reconnect could swap which sink owned which EQ.
        forward = {d["name"]: d["tag"] for d in devices.parse(A2DP + HSP)}
        reverse = {d["name"]: d["tag"] for d in devices.parse(HSP + A2DP)}
        self.assertEqual(forward, reverse)

    def test_no_uniquing_counter_is_needed_for_them_at_all(self):
        # Deriving the suffix from the profile means the two sinks never
        # collide, so nothing is ever appended to break a tie. Checked by
        # exact tag rather than by looking for a trailing digit: an A2DP tag
        # is "bt" plus four hex digits of the address and ends in one about
        # two-thirds of the time.
        tags = sorted(d["tag"] for d in devices.parse(A2DP + HSP))
        self.assertEqual(tags, ["bt8ae6", "bt8ae6hs"])

    def test_a_bluetooth_sink_with_no_profile_property_still_tags(self):
        # PACTL in the older fixture carries no api.bluez5.profile at all.
        d = devices.parse(PACTL)
        self.assertEqual({x["tag"] for x in d} & {"bt8ae6"}, {"bt8ae6"})
        self.assertFalse([x for x in d if x["tag"] == "bt8ae6"][0]["narrowband"])


class FakeRun(object):
    """Stand-in for subprocess.run: pw-metadata is not on the test machine."""

    def __init__(self, stdout="", exc=None):
        self.stdout, self.exc, self.argv = stdout, exc, None

    def __call__(self, argv, **kw):
        self.argv = argv
        if self.exc:
            raise self.exc
        return self


class TestAllowedRates(unittest.TestCase):
    """A biquad's shape near Nyquist comes partly from bilinear warping, so the
    rates the graph may settle on decide whether a fitted curve is still the
    curve that was measured. Guessing is wrong exactly for the people who
    enabled extra rates for bit-perfect playback."""

    def setUp(self):
        self.saved = devices.subprocess

    def tearDown(self):
        devices.subprocess = self.saved

    def rates(self, stdout="", exc=None, **kw):
        # Swap the module the function looks the name up in, rather than
        # monkeypatching subprocess.run itself -- that is global, and every
        # other test in the suite shares it.
        self.fake = FakeRun(stdout, exc)
        devices.subprocess = types.SimpleNamespace(
            run=self.fake, SubprocessError=subprocess.SubprocessError)
        return devices.allowed_rates(**kw)

    def test_the_stock_single_rate_is_parsed(self):
        line = ("update: id:0 key:'clock.allowed-rates' value:'[ 48000 ]' "
                "type:'Spa:String:JSON'")
        self.assertEqual(self.rates(line), (48000.0,))

    def test_several_rates_come_back_sorted_and_deduplicated(self):
        line = ("update: id:0 key:'clock.allowed-rates' "
                "value:'[ 96000, 44100, 48000, 44100 ]' type:'Spa:String:JSON'")
        self.assertEqual(self.rates(line), (44100.0, 48000.0, 96000.0))

    def test_other_settings_in_the_same_output_are_ignored(self):
        out = "\n".join([
            "update: id:0 key:'clock.rate' value:'48000' type:''",
            "update: id:0 key:'clock.quantum' value:'1024' type:''",
            "update: id:0 key:'clock.allowed-rates' value:'[ 44100 ]' type:''",
        ])
        self.assertEqual(self.rates(out), (44100.0,))

    def test_it_asks_pw_metadata_for_the_settings_metadata(self):
        self.rates("")
        self.assertEqual(self.fake.argv, ["pw-metadata", "-n", "settings"])

    def test_a_missing_key_falls_back_to_48k(self):
        # A graph that never mentions allowed-rates is running at 48000.
        self.assertEqual(self.rates("update: id:0 key:'clock.rate' value:'0'"), (48000.0,))

    def test_no_pw_metadata_at_all_falls_back_to_48k(self):
        self.assertEqual(self.rates(exc=OSError("no such file")), (48000.0,))

    def test_a_hung_pw_metadata_falls_back_to_48k(self):
        # Never let doctor or import block on a wedged daemon.
        exc = subprocess.TimeoutExpired(["pw-metadata"], 5)
        self.assertEqual(self.rates(exc=exc), (48000.0,))

    def test_implausible_numbers_are_not_treated_as_rates(self):
        line = "update: id:0 key:'clock.allowed-rates' value:'[ 0, 7 ]' type:''"
        self.assertEqual(self.rates(line), (48000.0,))

    def test_the_caller_may_choose_its_own_fallback(self):
        self.assertEqual(self.rates("", default=(44100.0, 48000.0)),
                         (44100.0, 48000.0))
