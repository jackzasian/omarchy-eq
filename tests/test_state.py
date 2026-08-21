import json
import os
import tempfile
import unittest

import context  # noqa: F401
import state


def run(points):
    return {"points": {f: {"db": d, "snr": s, "valid": s >= state.SNR_MIN}
                       for f, (d, s) in points.items()}}


class TestMerge(unittest.TestCase):
    def test_agreeing_positions_are_kept_as_the_median(self):
        m = state.merge([run({"1000": (-15.0, 40)}), run({"1000": (-16.2, 40)})])
        self.assertTrue(m["1000"]["valid"])
        self.assertAlmostEqual(m["1000"]["db"], -15.6, places=1)
        self.assertEqual(m["1000"]["confidence"], "high")

    def test_disagreeing_positions_are_dropped_as_geometry(self):
        # A comb null moves when the mic moves; the driver does not.
        m = state.merge([run({"4000": (-39.0, 25)}), run({"4000": (-22.0, 30)})])
        self.assertFalse(m["4000"]["valid"])
        self.assertIn("disagree", m["4000"]["reason"])

    def test_points_below_the_noise_floor_are_dropped(self):
        m = state.merge([run({"80": (-68.0, 2)}), run({"80": (-66.0, 3)})])
        self.assertFalse(m["80"]["valid"])
        self.assertEqual(m["80"]["reason"], "below noise floor")

    def test_single_run_is_kept_but_flagged_as_such(self):
        m = state.merge([run({"1000": (-15.0, 40)})])
        self.assertEqual(m["1000"]["confidence"], "single")

    def test_spread_exactly_at_threshold_is_kept(self):
        m = state.merge([run({"1000": (-10.0, 40)}),
                         run({"1000": (-10.0 - state.CONSISTENCY_DB, 40)})])
        self.assertTrue(m["1000"]["valid"])


class TestExport(unittest.TestCase):
    def test_invalid_points_export_as_nan_not_a_number(self):
        m = state.merge([run({"80": (-68.0, 2), "1000": (-15.0, 40)})])
        txt = state.export_txt({"merged": m})
        self.assertIn("80 nan", txt)
        self.assertIn("1000 -15.00", txt)

    def test_export_is_ordered_by_frequency(self):
        m = state.merge([run({"1000": (-15.0, 40), "80": (-40.0, 40),
                              "10000": (-20.0, 40)})])
        rows = [l.split()[0] for l in state.export_txt({"merged": m}).splitlines()
                if not l.startswith("#")]
        self.assertEqual(rows, ["80", "1000", "10000"])


class TestPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["XDG_STATE_HOME"] = self.tmp

    def test_device_key_is_filesystem_safe(self):
        k = state.device_key("bluez_output.AA:BB:CC:DD:EE:FF.1")
        self.assertNotIn(":", k)
        self.assertTrue(k)

    def test_missing_sink_still_yields_a_key(self):
        self.assertTrue(state.device_key(""))
        self.assertTrue(state.device_key(None))

    def test_different_devices_get_different_directories(self):
        a = state.device_dir("alsa_output.pci-0000_00_1f.3.analog-stereo")
        b = state.device_dir("bluez_output.AA:BB:CC:DD:EE:FF.1")
        self.assertNotEqual(a, b)

    def test_state_is_not_under_the_install_prefix(self):
        # Regression: state used to live in XDG_DATA_HOME/omarchy-eq, the same
        # directory install.sh writes lib/ into.
        self.assertNotIn(state.legacy_root(), state.state_root())


class TestMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["XDG_STATE_HOME"] = os.path.join(self.tmp, "state")
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp, "data")
        os.makedirs(state.legacy_root(), exist_ok=True)

    def test_legacy_response_becomes_a_run(self):
        with open(os.path.join(state.legacy_root(), "response.txt"), "w") as fh:
            fh.write("# old\n100 -30.0\n1000 -15.0\n")
        moved = state.migrate("spk")
        self.assertTrue(moved)
        with open(state.response_path("spk")) as fh:
            data = json.load(fh)
        self.assertEqual(len(data["runs"]), 1)
        self.assertTrue(data["merged"]["1000"]["valid"])

    def test_migration_never_clobbers_newer_state(self):
        with open(os.path.join(state.legacy_root(), "response.txt"), "w") as fh:
            fh.write("100 -30.0\n")
        state._write(state.response_path("spk"), {"merged": {}, "runs": ["keep"]})
        state.migrate("spk")
        with open(state.response_path("spk")) as fh:
            self.assertEqual(json.load(fh)["runs"], ["keep"])


if __name__ == "__main__":
    unittest.main()


class TestFloorLimited(unittest.TestCase):
    """Two kinds of 'invalid' that must not be conflated.

    A position disagreement means the level is unknown. A floor-limited reading
    means the level is at most this loud -- which is the evidence that a driver
    reproduces nothing in that band. Discarding both cost the highpass its
    corner on a speaker with no bass at all.
    """

    def test_below_floor_keeps_its_level_as_an_upper_bound(self):
        m = state.merge([run({"80": (-68.0, 2)}), run({"80": (-66.0, 3)})])
        self.assertFalse(m["80"]["valid"])
        self.assertTrue(m["80"]["floor_limited"])
        self.assertAlmostEqual(m["80"]["db"], -67.0, places=1)

    def test_position_disagreement_records_no_level(self):
        m = state.merge([run({"4000": (-39.0, 25)}), run({"4000": (-22.0, 30)})])
        self.assertFalse(m["4000"]["valid"])
        self.assertNotIn("db", m["4000"])
        self.assertNotIn("floor_limited", m["4000"])

    def test_floor_limited_points_are_listed_separately_from_valid_ones(self):
        m = state.merge([run({"80": (-68.0, 2), "1000": (-15.0, 40)})])
        data = {"merged": m}
        self.assertEqual([f for f, _ in state.valid_points(data)], [1000.0])
        self.assertEqual([f for f, _ in state.floor_limited_points(data)], [80.0])


class TestMigrationIsBuiltinOnly(unittest.TestCase):
    """Pre-v2 state was always a measurement of the laptop's own drivers.

    Copying it into whichever device was touched first gave a pair of
    Bluetooth headphones the laptop speaker's highpass and correction curve.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["XDG_STATE_HOME"] = os.path.join(self.tmp, "state")
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp, "data")
        os.makedirs(state.legacy_root(), exist_ok=True)
        with open(os.path.join(state.legacy_root(), "response.txt"), "w") as fh:
            fh.write("100 -30.0\n1000 -15.0\n")

    def test_builtin_device_receives_the_legacy_measurement(self):
        self.assertTrue(state.migrate("alsa_output.pci-x", is_builtin=True))

    def test_non_builtin_device_receives_nothing(self):
        self.assertEqual(state.migrate("bluez_output.AA_BB.1", is_builtin=False), [])
        self.assertFalse(os.path.exists(state.response_path("bluez_output.AA_BB.1")))
