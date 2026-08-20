import math
import unittest

import context  # noqa: F401
import biquad

SR = 48000


class TestBiquad(unittest.TestCase):
    def test_peaking_hits_its_gain_at_fc(self):
        for gain in (-9.0, -3.0, 3.0, 6.0, 12.0):
            c = biquad.design("bq_peaking", 1000, SR, 1.0, gain)
            self.assertAlmostEqual(biquad.magnitude_db(c, 1000, SR), gain, places=6)

    def test_peaking_is_unity_far_from_fc(self):
        c = biquad.design("bq_peaking", 1000, SR, 2.0, 12.0)
        self.assertLess(abs(biquad.magnitude_db(c, 20, SR)), 0.1)

    def test_highpass_is_minus_three_db_at_corner(self):
        c = biquad.design("bq_highpass", 300, SR, math.sqrt(0.5))
        self.assertAlmostEqual(biquad.magnitude_db(c, 300, SR), -3.01, places=1)

    def test_highpass_rolls_off_twelve_db_per_octave(self):
        c = biquad.design("bq_highpass", 300, SR, math.sqrt(0.5))
        a = biquad.magnitude_db(c, 37.5, SR)
        b = biquad.magnitude_db(c, 75.0, SR)
        self.assertAlmostEqual(b - a, 12.0, delta=0.5)

    def test_shelves_reach_their_gain(self):
        hs = biquad.design("bq_highshelf", 9000, SR, math.sqrt(0.5), 4.0)
        self.assertAlmostEqual(biquad.magnitude_db(hs, 20000, SR), 4.0, delta=0.3)
        ls = biquad.design("bq_lowshelf", 105, SR, 0.7, 5.5)
        self.assertAlmostEqual(biquad.magnitude_db(ls, 20, SR), 5.5, delta=0.3)

    def test_bandpass_peaks_at_unity_and_rejects_out_of_band(self):
        c = biquad.design("bandpass", 1000, SR, 2.0)
        self.assertAlmostEqual(biquad.magnitude_db(c, 1000, SR), 0.0, places=6)
        self.assertLess(biquad.magnitude_db(c, 100, SR), -20.0)
        self.assertLess(biquad.magnitude_db(c, 10000, SR), -20.0)

    def test_corner_above_nyquist_is_clamped_not_crashed(self):
        c = biquad.design("bq_highpass", 40000, SR, 0.707)
        self.assertTrue(all(math.isfinite(v) for v in c))

    def test_unknown_label_rejected(self):
        with self.assertRaises(ValueError):
            biquad.design("bq_nonsense", 1000, SR)


if __name__ == "__main__":
    unittest.main()
