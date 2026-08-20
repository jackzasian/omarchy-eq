import unittest

import context  # noqa: F401
import curve
import import_apo

AUTOEQ = """Preamp: -6.8 dB
Filter 1: ON LSC Fc 105 Hz Gain 5.5 dB Q 0.70
Filter 2: ON PK Fc 105 Hz Gain -2.4 dB Q 0.70
Filter 3: ON PK Fc 2200 Hz Gain 3.1 dB Q 1.50
Filter 4: OFF PK Fc 5000 Hz Gain 9.9 dB Q 1.00
Filter 5: ON HSC Fc 10000 Hz Gain -1.5 dB Q 0.70
Filter 6: ON None
"""


class TestParse(unittest.TestCase):
    def test_parses_gain_fc_and_q(self):
        filters, preamp, _ = import_apo.parse(AUTOEQ)
        self.assertAlmostEqual(preamp, -6.8)
        self.assertEqual(filters[0]["label"], "bq_lowshelf")
        self.assertEqual(filters[0]["control"]["Freq"], 105.0)
        self.assertEqual(filters[0]["control"]["Gain"], 5.5)
        self.assertEqual(filters[0]["control"]["Q"], 0.70)

    def test_disabled_filters_are_skipped(self):
        filters, _, _ = import_apo.parse(AUTOEQ)
        self.assertFalse(any(f["control"].get("Gain") == 9.9 for f in filters))

    def test_unsupported_types_are_reported_not_silently_dropped(self):
        _, _, skipped = import_apo.parse(AUTOEQ)
        self.assertTrue(any("None" in s for s in skipped))

    def test_all_apo_types_map_to_real_pipewire_labels(self):
        import biquad
        for label in set(import_apo.TYPES.values()):
            self.assertIn(label, biquad.LABELS)

    def test_bandwidth_only_filters_get_no_gain_control(self):
        filters, _, _ = import_apo.parse("Filter 1: ON HP Fc 80 Hz Q 0.70\n")
        self.assertNotIn("Gain", filters[0]["control"])

    def test_graphic_eq_is_rejected_with_guidance(self):
        with self.assertRaises(SystemExit) as ctx:
            import_apo.parse("GraphicEQ: 20 -0.5; 25 -0.6; 31 -0.8\n")
        self.assertIn("ParametricEQ", str(ctx.exception))

    def test_missing_q_defaults_rather_than_crashing(self):
        filters, _, _ = import_apo.parse("Filter 1: ON PK Fc 1000 Hz Gain 3 dB\n")
        self.assertAlmostEqual(filters[0]["control"]["Q"], 0.707, places=3)


class TestBuild(unittest.TestCase):
    def test_preamp_becomes_a_broadband_linear_stage(self):
        chain = import_apo.build(*import_apo.parse(AUTOEQ)[:2])
        self.assertEqual(chain[0]["label"], "linear")
        self.assertAlmostEqual(chain[0]["control"]["mult"], 10 ** (-6.8 / 20), places=5)

    def test_no_preamp_stage_when_preamp_is_zero(self):
        chain = import_apo.build(import_apo.parse(AUTOEQ)[0], 0.0)
        self.assertNotEqual(chain[0]["label"], "linear")

    def test_node_names_are_unique(self):
        chain = import_apo.build(*import_apo.parse(AUTOEQ)[:2])
        names = [f["name"] for f in chain]
        self.assertEqual(len(names), len(set(names)))

    def test_midband_gain_matches_the_declared_preamp(self):
        # End-to-end: the preamp is the only thing acting at 700 Hz, well away
        # from every filter in this preset.
        chain = import_apo.build(*import_apo.parse(AUTOEQ)[:2])
        self.assertAlmostEqual(curve.chain_response(chain, [700])[0][1], -6.8, delta=0.3)


if __name__ == "__main__":
    unittest.main()
