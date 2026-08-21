"""The GraphicEQ fitter.

The interesting tests here are the ones pinning down *why* the fitter is shaped
the way it is: that fitting for rates the graph will never use makes the result
worse at the rate it does use, and that the re-fit is what keeps filters off
their gain clamp.
"""
import math
import unittest

import context  # noqa: F401
import biquad
import graphic_eq


def curve(fn, lo=20.0, hi=20000.0, n=127):
    step = (math.log10(hi) - math.log10(lo)) / (n - 1)
    return [(10.0 ** (math.log10(lo) + i * step),
             fn(10.0 ** (math.log10(lo) + i * step))) for i in range(n)]


def bass_and_treble(f):
    """A plausible headphone correction: bass lift, presence dip, treble tilt."""
    return (6.0 / (1.0 + (f / 90.0) ** 2)
            - 4.0 * math.exp(-((math.log10(f) - math.log10(3000.0)) ** 2) / 0.02)
            - 3.0 * math.log10(max(f, 1000.0) / 1000.0))


def response_at(filters, freqs, sr):
    co = [biquad.design(f["label"], f["control"]["Freq"], sr,
                        f["control"]["Q"], f["control"]["Gain"])
          for f in filters]
    return [sum(biquad.magnitude_db(c, f, sr) for c in co) for f in freqs]


def worst_error(filters, points, sr):
    freqs = [f for f, _ in points]
    got = response_at(filters, freqs, sr)
    return max(abs(t - g) for (_, t), g in zip(points, got))


class TestParse(unittest.TestCase):
    def test_parses_the_autoeq_form(self):
        pts = graphic_eq.parse("GraphicEQ: 20 -0.2; 21 -0.3; 25 1.5")
        self.assertEqual(pts, [(20.0, -0.2), (21.0, -0.3), (25.0, 1.5)])

    def test_survives_a_bare_body_and_newlines(self):
        self.assertEqual(graphic_eq.parse("20 -1;\n40 2;\n"),
                         [(20.0, -1.0), (40.0, 2.0)])

    def test_ignores_junk_and_non_positive_frequencies(self):
        pts = graphic_eq.parse("GraphicEQ: 20 -1; nonsense; 0 5; 40 2")
        self.assertEqual(pts, [(20.0, -1.0), (40.0, 2.0)])


class TestFit(unittest.TestCase):
    def setUp(self):
        self.points = curve(bass_and_treble)

    def test_fits_a_realistic_curve_closely(self):
        filters, _, max_err, rms = graphic_eq.fit(self.points, 10, (48000.0,))
        self.assertLessEqual(max_err, 1.5, "worst-case error too large")
        self.assertLessEqual(rms, 0.6)

    def test_more_filters_never_fit_worse(self):
        _, _, few, _ = graphic_eq.fit(self.points, 6, (48000.0,))
        _, _, many, _ = graphic_eq.fit(self.points, 14, (48000.0,))
        self.assertLessEqual(many, few + 0.05)

    def test_emits_only_biquads_pipewire_implements(self):
        filters, _, _, _ = graphic_eq.fit(self.points, 8, (48000.0,))
        for f in filters:
            self.assertIn(f["label"], biquad.LABELS)
            self.assertIn("Freq", f["control"])

    def test_no_filter_sits_on_the_gain_clamp(self):
        # A clamped filter is the fit saying it wanted something it could not
        # have. The joint re-fit is what stops that happening; before it, one or
        # two filters per preset came out pinned at the limit.
        filters, _, _, _ = graphic_eq.fit(self.points, 10, (48000.0,))
        for f in filters:
            self.assertLess(abs(f["control"]["Gain"]), graphic_eq.MAX_GAIN - 0.01,
                            "filter pinned at the gain clamp: %r" % (f,))

    def test_preamp_keeps_the_chain_below_unity(self):
        boost = curve(lambda f: 8.0 / (1.0 + (f / 100.0) ** 2))
        filters, preamp, _, _ = graphic_eq.fit(boost, 10, (48000.0,))
        peak = max(response_at(filters, [f for f, _ in boost], 48000.0))
        self.assertLessEqual(peak + preamp, 0.01,
                             "preamp does not cancel the boost, so it can clip")

    def test_a_flat_curve_needs_no_filters(self):
        filters, preamp, max_err, _ = graphic_eq.fit(
            curve(lambda f: 0.0), 10, (48000.0,))
        self.assertEqual(filters, [])
        self.assertEqual(preamp, 0.0)
        self.assertLess(max_err, 0.05)

    def test_rejects_an_empty_curve(self):
        with self.assertRaises(ValueError):
            graphic_eq.fit([], 10)


class TestRateRobustness(unittest.TestCase):
    """Why the rate list comes from PipeWire rather than being a constant.

    A biquad's shape near Nyquist comes partly from bilinear warping, and the
    fit will exploit it if allowed to. These two tests are the evidence for
    both halves of the rule: fit for what you will run at, and nothing else.
    """

    def setUp(self):
        self.points = curve(bass_and_treble)
        self.freqs = [f for f, _ in self.points]

    def test_a_single_rate_fit_does_not_transfer_to_another_rate(self):
        filters, _, _, _ = graphic_eq.fit(self.points, 10, (48000.0,))
        here = worst_error(filters, self.points, 48000.0)
        there = worst_error(filters, self.points, 96000.0)
        self.assertGreater(there, here * 2.0,
                           "expected a single-rate fit to degrade off its rate")

    def test_fitting_for_several_rates_holds_up_at_all_of_them(self):
        rates = (44100.0, 48000.0, 96000.0)
        filters, _, _, _ = graphic_eq.fit(self.points, 12, rates)
        for sr in rates:
            self.assertLess(worst_error(filters, self.points, sr), 4.0,
                            "poor fit at %g Hz" % sr)

    def test_padding_the_rate_list_costs_accuracy_where_it_matters(self):
        # The reason the list is not just "all the common rates": every extra
        # rate is a constraint, and satisfying one you never use is paid for at
        # the one you do.
        narrow, _, _, _ = graphic_eq.fit(self.points, 10, (48000.0,))
        wide, _, _, _ = graphic_eq.fit(self.points, 10, (44100.0, 48000.0, 96000.0))
        self.assertLess(worst_error(narrow, self.points, 48000.0),
                        worst_error(wide, self.points, 48000.0))


if __name__ == "__main__":
    unittest.main()
