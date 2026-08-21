import os
import tempfile
import unittest

import context  # noqa: F401
import health
import prefs
import state

DEV = {"name": "bluez_output.3C_B0_ED_50_8A_E6.1", "tag": "bt8ae6",
       "description": "Nothing Ear (open)", "kind": "headphones",
       "measurable": False, "narrowband": False}
RATES = (48000.0,)


def parametric(**extra):
    prof = {"description": "test", "format": "parametric",
            "filters": [{"name": "pr", "label": "bq_peaking",
                         "control": {"Freq": 3000, "Q": 1.0, "Gain": 6.0}}]}
    prof.update(extra)
    return prof


class HealthCase(unittest.TestCase):
    """Everything here is a failure that is *quiet*: the profile stays in
    profiles.json and keeps showing up in the menu, it has just stopped being
    the thing it claims to be. So each check gets its own fake state tree."""

    def setUp(self):
        self.saved = os.environ.get("XDG_STATE_HOME")
        self.tmp = tempfile.mkdtemp()
        os.environ["XDG_STATE_HOME"] = self.tmp

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.saved

    def install(self, **profiles):
        state._write(state.profiles_path(DEV["name"]), {"profiles": profiles})

    def wav(self, name="ir.wav"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(b"RIFF....WAVE")
        return path

    def check(self, rates=RATES):
        return health.check_device(DEV, rates)


class TestHealthy(HealthCase):
    def test_a_device_with_nothing_installed_has_nothing_to_say(self):
        self.assertEqual(self.check(), [])

    def test_a_sound_set_of_profiles_produces_no_lines(self):
        self.install(balanced=parametric(fitted_rates=[48000], fit_error_db=0.4),
                     room=dict(parametric(), format="convolution",
                               ir_file=self.wav()))
        prefs.remember(DEV["name"], "balanced")
        self.assertEqual(self.check(), [])

    def test_flat_is_never_reported_as_a_missing_profile(self):
        # "Leave this output alone" is a legitimate remembered value and has no
        # entry in profiles.json by design.
        self.install(balanced=parametric())
        prefs.remember(DEV["name"], "flat")
        self.assertEqual(self.check(), [])

    def test_a_fit_exactly_at_the_threshold_is_not_yet_a_complaint(self):
        self.install(balanced=parametric(fit_error_db=health.POOR_FIT_DB))
        self.assertEqual(self.check(), [])

    def test_unknown_graph_rates_silence_the_rate_check(self):
        # allowed_rates() falls back rather than raising; with nothing to
        # compare against, a fitted-rate warning would be a guess.
        self.install(balanced=parametric(fitted_rates=[44100]))
        self.assertEqual(self.check(rates=()), [])


class TestWarnings(HealthCase):
    def test_a_deleted_impulse_response_is_reported(self):
        # The chain fails to instantiate and the sink never appears, which
        # presents as "that profile stopped working", not as a missing file.
        self.install(room=dict(parametric(), format="convolution",
                               ir_file="/nowhere/gone.wav"))
        lines = self.check()
        self.assertEqual(len(lines), 1)
        self.assertIn("impulse response is missing", lines[0])
        self.assertIn("/nowhere/gone.wav", lines[0])
        self.assertTrue(lines[0].startswith("bt8ae6/room:"))

    def test_only_convolution_profiles_are_checked_for_an_ir_file(self):
        self.install(balanced=parametric(ir_file="/nowhere/gone.wav"))
        self.assertEqual(self.check(), [])

    def test_a_curve_fitted_at_other_rates_is_reported(self):
        # Changing clock.allowed-rates happens months after importing a preset
        # and nothing else connects the two events for you.
        self.install(balanced=parametric(fitted_rates=[44100]))
        lines = self.check()
        self.assertEqual(len(lines), 1)
        self.assertIn("fitted for 44100 Hz", lines[0])
        self.assertIn("48000", lines[0])

    def test_rates_are_compared_as_a_set_not_as_written(self):
        self.install(balanced=parametric(fitted_rates=[48000.0, 44100]))
        self.assertEqual(len(self.check(rates=(44100.0, 48000.0))), 0)

    def test_a_poor_fit_is_reported_long_after_the_terminal_is_gone(self):
        self.install(balanced=parametric(fit_error_db=5.2))
        lines = self.check()
        self.assertEqual(len(lines), 1)
        self.assertIn("5.2 dB off", lines[0])

    def test_a_remembered_profile_that_was_regenerated_away_is_reported(self):
        # Otherwise the output silently comes up somewhere other than where
        # you left it.
        self.install(balanced=parametric())
        prefs.remember(DEV["name"], "vintage")
        lines = self.check()
        self.assertEqual(len(lines), 1)
        self.assertIn("'vintage' no longer exists", lines[0])

    def test_every_problem_on_one_device_is_reported_at_once(self):
        self.install(room=dict(parametric(), format="convolution",
                               ir_file="/nowhere/gone.wav",
                               fitted_rates=[44100], fit_error_db=9.0))
        prefs.remember(DEV["name"], "vintage")
        self.assertEqual(len(self.check()), 4)

    def test_profiles_are_reported_in_a_stable_order(self):
        self.install(zeta=parametric(fit_error_db=9.0),
                     alpha=parametric(fit_error_db=9.0))
        lines = self.check()
        self.assertTrue(lines[0].startswith("bt8ae6/alpha:"))
        self.assertTrue(lines[1].startswith("bt8ae6/zeta:"))


if __name__ == "__main__":
    unittest.main()
