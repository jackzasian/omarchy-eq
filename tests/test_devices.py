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
