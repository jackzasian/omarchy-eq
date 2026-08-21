import math
import os
import shutil
import struct
import tempfile
import unittest
import wave

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


HALF = 16384          # 0.5 full scale in 16-bit, so -6.02 dB exactly
QUARTER = 8192        # -12.04 dB


def convolver(path, **cfg):
    cfg.setdefault("filename", path)
    return [{"name": "conv", "label": "convolver", "config": cfg}]


class TestConvolutionResponse(unittest.TestCase):
    """A convolution profile has no filter description to evaluate, so its
    curve comes out of the impulse response itself. Drawing it on the same axes
    as every other profile is the difference between a comparison and a blank
    panel with an apology."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.freqs = [100.0, 1000.0, 5000.0, 15000.0]

    def write_ir(self, frames, rate=48000, channels=1, name="ir.wav"):
        path = os.path.join(self.tmp, name)
        with wave.open(path, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(struct.pack("<%dh" % len(frames), *frames))
        return path

    def test_a_single_impulse_is_flat_at_its_own_amplitude(self):
        # An impulse of 0.5 is a broadband -6 dB pad and nothing else; if the
        # DFT were wrong this is where it would show first.
        path = self.write_ir([HALF])
        out = curve.chain_response(convolver(path), self.freqs)
        self.assertEqual([f for f, _ in out], self.freqs)
        for _, g in out:
            self.assertAlmostEqual(g, -6.02, delta=0.02)

    def test_a_delayed_impulse_is_just_as_flat(self):
        # Delay is phase, not magnitude. A response that sagged with latency
        # would mean the DFT was reading the taps out of step.
        path = self.write_ir([0] * 64 + [HALF])
        for _, g in curve.chain_response(convolver(path), self.freqs):
            self.assertAlmostEqual(g, -6.02, delta=0.02)

    def test_the_wav_s_own_sample_rate_is_used_not_the_default(self):
        # Two equal taps put a null at half the sample rate. At 8 kHz that null
        # belongs at 4 kHz; assuming 48000 would draw it at 24 kHz and the
        # curve would come out flat and wrong.
        path = self.write_ir([HALF, HALF], rate=8000)
        by = dict(curve.chain_response(convolver(path), [100.0, 4000.0]))
        self.assertLess(by[4000.0], -40.0)
        self.assertAlmostEqual(by[100.0], 0.0, delta=0.1)

    def test_the_requested_channel_is_the_one_that_is_drawn(self):
        path = self.write_ir([HALF, QUARTER], channels=2)   # L then R
        left = curve.chain_response(convolver(path, channel=0), [1000.0])[0][1]
        right = curve.chain_response(convolver(path, channel=1), [1000.0])[0][1]
        self.assertAlmostEqual(left, -6.02, delta=0.02)
        self.assertAlmostEqual(right, -12.04, delta=0.02)

    def test_the_left_channel_config_is_used_when_there_is_no_shared_one(self):
        # Stereo convolution profiles carry config_l/config_r instead.
        path = self.write_ir([HALF])
        f = {"name": "conv", "label": "convolver",
             "config_l": {"filename": path, "channel": 0},
             "config_r": {"filename": path, "channel": 1}}
        self.assertAlmostEqual(curve.chain_response([f], [1000.0])[0][1],
                               -6.02, delta=0.02)

    def test_read_ir_reports_the_rate_it_found(self):
        samples, rate = curve.read_ir(self.write_ir([HALF], rate=44100))
        self.assertEqual(rate, 44100)
        self.assertAlmostEqual(samples[0], 0.5, places=6)

    def test_a_missing_impulse_response_says_so_instead_of_drawing_nothing(self):
        # The same deletion breaks the actual sink, so the plot is often where
        # you find out. FileNotFoundError, not a bare ValueError from wave.
        gone = os.path.join(self.tmp, "gone.wav")
        with self.assertRaises(FileNotFoundError) as caught:
            curve.chain_response(convolver(gone), self.freqs)
        self.assertIn(gone, str(caught.exception))

    def test_a_convolver_anywhere_in_the_chain_takes_over_the_response(self):
        # A convolution profile is one node; there is nothing to add to it.
        path = self.write_ir([HALF])
        chain = [{"name": "pre", "label": "linear", "control": {"mult": 0.5}}] \
            + convolver(path)
        for _, g in curve.chain_response(chain, self.freqs):
            self.assertAlmostEqual(g, -6.02, delta=0.02)
