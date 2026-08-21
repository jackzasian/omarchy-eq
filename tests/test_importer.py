"""Importing all four AutoEQ formats.

The formats differ in what they can promise. Parametric and fixed-band imports
are exact; a graphic import is a fit and has to admit it; a convolution import
depends on a file that has to still be there. The tests assert those promises
rather than just "it produced some filters".
"""
import json
import math
import os
import shutil
import struct
import tempfile
import unittest
import wave

import context  # noqa: F401
import importer

PARAMETRIC = """Preamp: -6.1 dB
Filter 1: ON LSC Fc 105 Hz Gain 6.4 dB Q 0.70
Filter 2: ON PK Fc 8800 Hz Gain 5.1 dB Q 1.42
Filter 3: ON HSC Fc 10000 Hz Gain -2.1 dB Q 0.70
"""
FIXEDBAND = """Preamp: -7.4 dB
Filter 1: ON PK Fc 31 Hz Gain -1.2 dB Q 1.41
Filter 2: ON PK Fc 62 Hz Gain 0.4 dB Q 1.41
"""
GRAPHIC = "GraphicEQ: " + "; ".join(
    "%d %.1f" % (f, -3.0 * math.log10(f / 20.0))
    for f in (20, 30, 45, 70, 105, 160, 240, 360, 550, 820, 1200, 1800, 2700,
              4100, 6100, 9200, 13800, 19900))


def write_ir(path, frames=512, channels=2, rate=48000):
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        # Minimum-phase-ish: all the energy in the first sample.
        data = b""
        for i in range(frames):
            v = 20000 if i == 0 else 0
            data += struct.pack("<" + "h" * channels, *([v] * channels))
        w.writeframes(data)


class ImportCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.profiles = os.path.join(self.dir, "profiles.json")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path


class TestDetect(ImportCase):
    def test_recognises_each_format(self):
        cases = [("HD 650 ParametricEQ.txt", PARAMETRIC, "parametric"),
                 ("HD 650 FixedBandEQ.txt", FIXEDBAND, "fixedband"),
                 ("HD 650 GraphicEQ.txt", GRAPHIC, "graphic")]
        for name, text, want in cases:
            self.assertEqual(importer.detect(self.write(name, text)), want)

    def test_recognises_an_impulse_response_by_extension(self):
        path = os.path.join(self.dir, "ir.wav")
        write_ir(path)
        self.assertEqual(importer.detect(path), "convolution")

    def test_rejects_something_that_is_not_a_preset(self):
        with self.assertRaises(SystemExit):
            importer.detect(self.write("notes.txt", "shopping list\nmilk\n"))


class TestParametric(ImportCase):
    def test_is_exact_and_keeps_the_preamp_as_a_gain_stage(self):
        prof, _ = importer.build_profile(
            self.write("p.txt", PARAMETRIC), self.dir, "p")
        self.assertEqual(prof["format"], "parametric")
        labels = [f["label"] for f in prof["filters"]]
        self.assertEqual(labels[0], "linear", "preamp must be a real stage")
        self.assertIn("bq_lowshelf", labels)
        self.assertIn("bq_highshelf", labels)
        # An exact import claims no fit error, because there is none.
        self.assertNotIn("fit_error_db", prof)

    def test_fixed_band_parses_the_same_way(self):
        prof, _ = importer.build_profile(
            self.write("HD FixedBandEQ.txt", FIXEDBAND), self.dir, "f")
        self.assertEqual(prof["format"], "fixedband")
        self.assertEqual(sum(1 for f in prof["filters"]
                             if f["label"] == "bq_peaking"), 2)


class TestGraphic(ImportCase):
    def test_fits_onto_biquads_and_records_what_it_cost(self):
        prof, notes = importer.build_profile(
            self.write("g.txt", GRAPHIC), self.dir, "g", rates=(48000.0,))
        self.assertEqual(prof["format"], "graphic")
        self.assertTrue(prof["filters"])
        self.assertIn("fit_error_db", prof)
        self.assertEqual(prof["fitted_rates"], [48000])
        self.assertTrue(any("fit error" in n for n in notes))

    def test_records_the_rates_it_was_fitted_for(self):
        prof, _ = importer.build_profile(
            self.write("g.txt", GRAPHIC), self.dir, "g",
            rates=(44100.0, 48000.0))
        self.assertEqual(prof["fitted_rates"], [44100, 48000])


class TestConvolution(ImportCase):
    def test_copies_the_response_out_of_wherever_it_was(self):
        src = os.path.join(self.dir, "downloads", "ir.wav")
        os.makedirs(os.path.dirname(src))
        write_ir(src)
        prof, _ = importer.build_profile(src, self.dir, "conv")
        kept = prof["ir_file"]
        self.assertTrue(os.path.exists(kept))
        # Deleting the download must not break the profile.
        os.remove(src)
        self.assertTrue(os.path.exists(kept))

    def test_stereo_response_uses_a_different_channel_per_side(self):
        src = os.path.join(self.dir, "ir.wav")
        write_ir(src, channels=2)
        prof, _ = importer.build_profile(src, self.dir, "conv")
        f = prof["filters"][0]
        self.assertEqual(f["label"], "convolver")
        self.assertEqual(f["config_l"]["channel"], 0)
        self.assertEqual(f["config_r"]["channel"], 1)

    def test_mono_response_uses_one_config_for_both_sides(self):
        src = os.path.join(self.dir, "ir.wav")
        write_ir(src, channels=1)
        prof, _ = importer.build_profile(src, self.dir, "conv")
        self.assertIn("config", prof["filters"][0])
        self.assertNotIn("config_l", prof["filters"][0])

    def test_reports_a_front_loaded_response_as_adding_no_delay(self):
        src = os.path.join(self.dir, "ir.wav")
        write_ir(src)
        _, notes = importer.build_profile(src, self.dir, "conv")
        self.assertTrue(any("minimum phase" in n for n in notes),
                        "a min-phase IR must not be reported as adding latency")

    def test_reports_the_real_delay_of_a_linear_phase_response(self):
        src = os.path.join(self.dir, "ir.wav")
        with wave.open(src, "wb") as w:
            w.setnchannels(2), w.setsampwidth(2), w.setframerate(48000)
            n = 4800
            w.writeframes(b"".join(
                struct.pack("<hh", *([20000 if i == n // 2 else 0] * 2))
                for i in range(n)))
        _, notes = importer.build_profile(src, self.dir, "conv")
        self.assertTrue(any("ms of delay" in n for n in notes))

    def test_refuses_a_room_impulse_response(self):
        src = os.path.join(self.dir, "room.wav")
        write_ir(src, frames=importer.IR_MAX_TAPS + 1, channels=1)
        with self.assertRaises(SystemExit):
            importer.build_profile(src, self.dir, "room")


class TestInstall(ImportCase):
    def test_adds_a_profile_without_disturbing_the_others(self):
        importer.install(self.profiles, "a", {"filters": [], "description": "a"})
        importer.install(self.profiles, "b", {"filters": [], "description": "b"})
        with open(self.profiles) as fh:
            data = json.load(fh)
        self.assertEqual(sorted(data["profiles"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
