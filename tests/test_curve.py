import unittest

import context  # noqa: F401
import curve


class TestCurve(unittest.TestCase):
    def test_axis_spans_the_audible_band_logarithmically(self):
        ax = curve.log_axis(20, 20000, 64)
        self.assertAlmostEqual(ax[0], 20.0, places=6)
        self.assertAlmostEqual(ax[-1], 20000.0, places=3)
        r1 = ax[1] / ax[0]
        r2 = ax[-1] / ax[-2]
        self.assertAlmostEqual(r1, r2, places=6)

    def test_empty_chain_is_flat(self):
        for _, g in curve.chain_response([], curve.log_axis(n=16)):
            self.assertAlmostEqual(g, 0.0, places=9)

    def test_series_sections_add_in_db(self):
        a = {"name": "a", "label": "bq_peaking",
             "control": {"Freq": 1000, "Q": 1.0, "Gain": 3.0}}
        b = {"name": "b", "label": "bq_peaking",
             "control": {"Freq": 1000, "Q": 1.0, "Gain": 4.0}}
        self.assertAlmostEqual(curve.chain_response([a, b], [1000])[0][1], 7.0, places=6)

    def test_peaking_gain_appears_at_its_centre(self):
        f = {"name": "pr", "label": "bq_peaking",
             "control": {"Freq": 3000, "Q": 1.0, "Gain": 6.0}}
        self.assertAlmostEqual(curve.chain_response([f], [3000])[0][1], 6.0, places=6)

    def test_highpass_rolls_off_below_its_corner(self):
        f = {"name": "hp", "label": "bq_highpass",
             "control": {"Freq": 300, "Q": 0.707}}
        below = curve.chain_response([f], [75])[0][1]
        above = curve.chain_response([f], [3000])[0][1]
        self.assertLess(below, -20.0)
        self.assertAlmostEqual(above, 0.0, delta=0.2)

    def test_linear_node_is_a_flat_broadband_gain(self):
        # APO preamp. It must apply everywhere, not just near some frequency.
        f = {"name": "pre", "label": "linear", "control": {"mult": 0.5, "add": 0.0}}
        vals = [g for _, g in curve.chain_response([f], curve.log_axis(n=16))]
        for g in vals:
            self.assertAlmostEqual(g, -6.02, delta=0.01)


if __name__ == "__main__":
    unittest.main()
