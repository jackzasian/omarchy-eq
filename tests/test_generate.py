import json
import math
import os
import tempfile
import unittest

import context
import generate


def shelf_of(profile):
    hs = [f for f in profile["filters"] if f["name"] == "hs"]
    return hs[0]["control"]["Gain"] if hs else 0.0


def flat_response(db=-20.0, hf=None):
    """A synthetic measurement: flat, optionally with a different top end."""
    freqs = [50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800,
             1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000,
             10000, 12500, 16000]
    return [(float(f), (hf if (hf is not None and f >= 8000) else db)) for f in freqs]


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_reads_legacy_two_column_text(self):
        p = os.path.join(context.FIXTURES, "response-x14.txt")
        pts = generate.load(p)
        self.assertEqual(len(pts), 26)
        self.assertEqual(pts[0][0], 50.0)

    def test_skips_nan_points(self):
        p = os.path.join(self.dir, "r.txt")
        with open(p, "w") as fh:
            fh.write("# header\n100 -30.0\n200 nan\n400 -25.0\n")
        self.assertEqual(generate.load(p), [(100.0, -30.0), (400.0, -25.0)])

    def test_reads_response_json_and_honours_validity(self):
        p = os.path.join(self.dir, "response.json")
        with open(p, "w") as fh:
            json.dump({"merged": {
                "100": {"db": -30.0, "valid": True},
                "200": {"valid": False, "reason": "below noise floor"},
                "400": {"db": -25.0, "valid": True}}}, fh)
        self.assertEqual(generate.load(p), [(100.0, -30.0), (400.0, -25.0)])


class TestAnalyse(unittest.TestCase):
    def test_flat_speaker_needs_almost_no_correction(self):
        a = generate.analyse(flat_response())
        self.assertEqual(a["corner"], generate.HPF_MIN)
        self.assertAlmostEqual(a["res_cut"], 0.0, delta=0.5)
        self.assertAlmostEqual(a["presence"], 0.0, delta=0.5)
        self.assertEqual(a["pinned"], [])

    def test_dull_top_end_produces_a_boost_shelf(self):
        a = generate.analyse(flat_response(db=-20.0, hf=-28.0))
        self.assertGreater(a["shelf"], 1.0)

    def test_hot_top_end_is_treated_as_mic_resonance_not_corrected(self):
        # An internal mic resonance makes 8k+ read hotter than midband. A laptop
        # speaker is never actually brighter than its midrange, so the shelf must
        # be refused rather than turned into a treble cut.
        a = generate.analyse(flat_response(db=-20.0, hf=-8.0))
        self.assertEqual(a["shelf"], 0.0)
        self.assertTrue(any("microphone" in n for n in a["notes"]))

    def test_saturated_parameters_are_reported(self):
        pts = generate.load(os.path.join(context.FIXTURES, "response-x14.txt"))
        a = generate.analyse(pts)
        self.assertIn("presence lift", a["pinned"])

    def test_rejects_measurement_with_no_midband(self):
        with self.assertRaises(SystemExit):
            generate.analyse([(50.0, -40.0), (63.0, -41.0)])


class TestProfiles(unittest.TestCase):
    """The music profile is described as 'adds air'. It must actually do so."""

    def test_music_has_strictly_more_top_end_than_balanced(self):
        # Below the clamp, "adds air" must be literally true.
        for hf in (-23.0, -22.0, -21.0):
            a = generate.analyse(flat_response(db=-20.0, hf=hf))
            p = generate.profiles(a)
            self.assertGreater(
                shelf_of(p["music"]), shelf_of(p["balanced"]),
                msg="music must be airier than balanced (hf=%s)" % hf)

    def test_music_is_never_less_airy_than_balanced_even_at_the_clamp(self):
        # At MAX_SHELF both saturate and become equal -- which is fine. What is
        # not fine is music ending up *below* balanced, which is what the old
        # negated formula did.
        for hf in (-40.0, -30.0, -28.0, -24.0, -21.0, -20.0, -15.0):
            a = generate.analyse(flat_response(db=-20.0, hf=hf))
            p = generate.profiles(a)
            self.assertGreaterEqual(
                shelf_of(p["music"]), shelf_of(p["balanced"]),
                msg="music dropped below balanced (hf=%s)" % hf)

    def test_music_air_is_never_a_treble_cut(self):
        # The old formula negated the measured shelf, so a bright-measuring
        # speaker got the *most* extra treble and a dull one got the least.
        for hf in (-30.0, -25.0, -20.0, -12.0):
            a = generate.analyse(flat_response(db=-20.0, hf=hf))
            self.assertGreaterEqual(shelf_of(generate.profiles(a)["music"]), 0.0)

    def test_voice_is_more_aggressive_than_balanced(self):
        a = generate.analyse(flat_response(db=-20.0, hf=-28.0))
        p = generate.profiles(a)
        hp = lambda pr: [f for f in pr["filters"] if f["name"] == "hp"][0]["control"]["Freq"]
        self.assertGreaterEqual(hp(p["voice"]), hp(p["balanced"]))

    def test_every_filter_is_a_known_label_with_required_controls(self):
        import biquad
        a = generate.analyse(flat_response(db=-20.0, hf=-28.0))
        for name, prof in generate.profiles(a).items():
            self.assertTrue(prof["filters"], "%s has no filters" % name)
            for f in prof["filters"]:
                self.assertIn(f["label"], biquad.LABELS)
                self.assertIn("Freq", f["control"])
                self.assertTrue(math.isfinite(f["control"]["Freq"]))

    def test_gains_stay_inside_the_clamps(self):
        pts = generate.load(os.path.join(context.FIXTURES, "response-x14.txt"))
        for prof in generate.profiles(generate.analyse(pts)).values():
            for f in prof["filters"]:
                g = f["control"].get("Gain")
                if g is not None:
                    self.assertLessEqual(abs(g), generate.MAX_BOOST + 0.01)


if __name__ == "__main__":
    unittest.main()


class TestFloorLimitedHighpass(unittest.TestCase):
    """A band too quiet to measure is still proof the driver is not making it."""

    def _pts(self):
        # Nothing usable below 250 Hz -- a real laptop speaker.
        return [(float(f), -21.0) for f in
                (250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000,
                 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000)]

    def test_ignoring_floor_limited_bands_leaves_the_corner_at_its_minimum(self):
        self.assertEqual(generate.analyse(self._pts())["corner"], generate.HPF_MIN)

    def test_floor_limited_bands_raise_the_corner_to_where_output_stops(self):
        fl = [(50.0, -44.0), (100.0, -43.0), (200.0, -45.0)]
        self.assertEqual(generate.analyse(self._pts(), fl)["corner"], 200)

    def test_floor_limited_bands_do_not_shift_the_midband_reference(self):
        a = generate.analyse(self._pts())
        b = generate.analyse(self._pts(), [(50.0, -44.0), (200.0, -45.0)])
        self.assertEqual(a["ref"], b["ref"])

    def test_a_quiet_band_above_the_rolloff_threshold_does_not_move_the_corner(self):
        # -25 is only 4 dB down; that is not "not reproduced".
        self.assertEqual(generate.analyse(self._pts(), [(200.0, -25.0)])["corner"],
                         generate.HPF_MIN)
