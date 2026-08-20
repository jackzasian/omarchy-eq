"""Exercise the exact command lines bin/omarchy-eq invokes.

Every one of these is a subprocess boundary the library tests do not cross. The
argv unpacking in state.py's `add-run` was wrong by one element and no library
test could see it -- the sweep ran for three minutes and then threw the results
away.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import context

SINK = "alsa_output.pci-0000_00_1f.3.analog-stereo"
SOURCE = "alsa_input.pci-0000_00_1f.3.analog-stereo"
FREQS = ["50", "1000", "16000"]


def run(module, *args, env=None):
    e = dict(os.environ)
    e["PYTHONPATH"] = context.LIB
    if env:
        e.update(env)
    return subprocess.run([sys.executable, os.path.join(context.LIB, module)]
                          + [str(a) for a in args],
                          capture_output=True, text=True, env=e)


class TestStateCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = {"XDG_STATE_HOME": os.path.join(self.tmp, "state"),
                    "XDG_DATA_HOME": os.path.join(self.tmp, "data")}
        self.runfile = os.path.join(self.tmp, "run.txt")
        with open(self.runfile, "w") as fh:
            for f in FREQS:
                fh.write("%s -20.0 30.0\n" % f)

    def _path(self, kind):
        r = run("state.py", "path", kind, SINK, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_path_response_and_profiles(self):
        self.assertTrue(self._path("response").endswith("response.json"))
        self.assertTrue(self._path("profiles").endswith("profiles.json"))

    def test_add_run_accepts_the_argv_bash_sends(self):
        # Regression: this is the exact call from cmd_measure.
        r = run("state.py", "add-run", SINK, SOURCE, "position-1",
                self.runfile, "60%", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self._path("response")) as fh:
            data = json.load(fh)
        self.assertEqual(len(data["runs"]), 1)
        self.assertEqual(data["runs"][0]["position"], "position-1")
        self.assertEqual(data["runs"][0]["volume"], "60%")
        self.assertEqual(data["sink"], SINK)

    def test_add_run_twice_accumulates_positions(self):
        for pos in ("position-1", "position-2"):
            r = run("state.py", "add-run", SINK, SOURCE, pos, self.runfile,
                    "60%", env=self.env)
            self.assertEqual(r.returncode, 0, r.stderr)
        with open(self._path("response")) as fh:
            self.assertEqual(len(json.load(fh)["runs"]), 2)

    def test_add_run_reports_a_summary(self):
        r = run("state.py", "add-run", SINK, SOURCE, "position-1",
                self.runfile, "60%", env=self.env)
        self.assertIn("usable points", r.stdout)

    def test_export_and_summary_read_what_add_run_wrote(self):
        run("state.py", "add-run", SINK, SOURCE, "p1", self.runfile, "60%",
            env=self.env)
        p = self._path("response")
        self.assertEqual(run("state.py", "export", p, env=self.env).returncode, 0)
        self.assertEqual(run("state.py", "summary", p, env=self.env).returncode, 0)

    def test_migrate_accepts_a_sink(self):
        self.assertEqual(run("state.py", "migrate", SINK, env=self.env).returncode, 0)

    def test_unknown_subcommand_exits_nonzero(self):
        self.assertNotEqual(run("state.py", "bogus", env=self.env).returncode, 0)


class TestPipelineCli(unittest.TestCase):
    """generate -> render -> describe, wired the way cmd_* wires them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.resp = os.path.join(self.tmp, "response.json")
        self.prof = os.path.join(self.tmp, "profiles.json")
        merged = {str(f): {"db": -20.0 - (5 if f >= 8000 else 0), "valid": True}
                  for f in (50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500,
                            630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000,
                            5000, 6300, 8000, 10000, 12500, 16000)}
        with open(self.resp, "w") as fh:
            json.dump({"schema": 1, "sink": SINK, "runs": [], "merged": merged}, fh)

    def test_generate_then_render_then_describe(self):
        g = run("generate.py", self.resp, self.prof)
        self.assertEqual(g.returncode, 0, g.stderr)
        r = run("render.py", self.prof, SINK)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("context.modules", r.stdout)
        d = run("describe.py", self.prof)
        self.assertEqual(d.returncode, 0, d.stderr)
        self.assertTrue(all("\t" in l for l in d.stdout.strip().splitlines()))

    def test_generate_refuses_a_measurement_with_too_few_points(self):
        thin = os.path.join(self.tmp, "thin.json")
        with open(thin, "w") as fh:
            json.dump({"merged": {"1000": {"db": -20.0, "valid": True}}}, fh)
        self.assertNotEqual(run("generate.py", thin, self.prof).returncode, 0)

    def test_import_accepts_the_empty_third_arg_bash_sends(self):
        # cmd_import passes "${2:-}", i.e. an empty string when unnamed.
        src = os.path.join(self.tmp, "AutoEq.txt")
        with open(src, "w") as fh:
            fh.write("Preamp: -3.0 dB\nFilter 1: ON PK Fc 1000 Hz Gain 2 dB Q 1.0\n")
        run("generate.py", self.resp, self.prof)
        r = run("import_apo.py", src, self.prof, "")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.prof) as fh:
            self.assertIn("autoeq", json.load(fh)["profiles"])


class TestAnalyzeCli(unittest.TestCase):
    def setUp(self):
        import struct
        import wave
        self.tmp = tempfile.mkdtemp()
        self.wav = os.path.join(self.tmp, "s.wav")
        w = wave.open(self.wav, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(4800)))
        w.close()

    def test_floor_batch_returns_one_row_per_frequency(self):
        r = run("analyze.py", "floor", self.wav, *FREQS)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = r.stdout.strip().splitlines()
        self.assertEqual(len(rows), len(FREQS))
        self.assertEqual([x.split()[0] for x in rows], FREQS)

    def test_band_returns_a_single_number(self):
        r = run("analyze.py", "band", self.wav, "1000")
        self.assertEqual(r.returncode, 0, r.stderr)
        float(r.stdout.strip())

    def test_no_arguments_exits_nonzero(self):
        self.assertNotEqual(run("analyze.py").returncode, 0)


if __name__ == "__main__":
    unittest.main()
