"""Argument handling in bin/omarchy-eq itself.

The bash driver runs under `set -u`, which turns a missing option value into
bash's own "$2: unbound variable" -- a message that names neither the flag the
user got wrong nor the command that lists valid values. These check the guard
that replaces it.

Only the subcommands that parse arguments *before* reaching for PipeWire are
exercised here: `ab` and `calibrate` call need_pa() first, so on a machine
without a running PipeWire (CI) they die of that instead, and the assertion
would be testing the wrong thing.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

import context  # noqa: F401

EXE = os.path.join(os.path.dirname(context.LIB), "bin", "omarchy-eq")
# These reach need_dev_val() before any pactl call, so they behave the same on a
# developer's desktop and on a headless runner.
PARSES_ARGS_FIRST = ["generate", "export", "tui", "import"]

# cmd_measure's median-of-repeats and snr pair, lifted verbatim apart from the
# %(sort)s hole the locale test uses to run it with and without the guard.
SWEEP_PIPELINE = r"""
vals=(%(vals)s)
med=$(printf '%%s\n' "${vals[@]}" | %(sort)s | awk '{a[NR]=$1} END{print a[int((NR+1)/2)]}')
snr=$(awk -v a="$med" -v b="%(floor)s" 'BEGIN{printf "%%.2f", a-b}')
printf '%%s %%s\n' "$med" "$snr"
"""


def run(*args):
    return subprocess.run(["bash", EXE, *args], capture_output=True, text=True)


class TestDeviceFlagNeedsAValue(unittest.TestCase):
    def test_bare_device_flag_is_reported_not_crashed_on(self):
        for cmd in PARSES_ARGS_FIRST:
            with self.subTest(cmd=cmd):
                r = run(cmd, "--device")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("--device needs a value", r.stderr)

    def test_bash_never_leaks_its_own_unbound_variable_error(self):
        for cmd in PARSES_ARGS_FIRST:
            with self.subTest(cmd=cmd):
                r = run(cmd, "--device")
                self.assertNotIn("unbound variable", r.stderr)


class TestOtherValueOptions(unittest.TestCase):
    """`--device` was not the only option reading $2 unguarded.

    `--position` and `--play` are checked by the same helper, but they live
    behind need_pa() so they cannot be driven end-to-end on a headless runner.
    Assert the call sites exist instead of pretending to exercise them.
    """

    def test_every_value_option_is_guarded(self):
        with open(EXE) as fh:
            body = fh.read()
        for flag in ("--device", "--position", "--play"):
            with self.subTest(flag=flag):
                self.assertIn('need_val %s "${2:-}"' % flag, body)

    def test_no_value_option_still_reads_bare_dollar_two(self):
        # The pattern this replaced: `--flag) var="$2"; shift ;;` with no guard.
        import re
        with open(EXE) as fh:
            body = fh.read()
        unguarded = re.findall(r'^\s*--(\w[\w-]*)\)\s+(?!need_val)\w+="\$2"',
                               body, re.M)
        self.assertEqual(unguarded, [], "unguarded $2 after: %s" % unguarded)


class TestUsage(unittest.TestCase):
    def test_version_is_reported_alone(self):
        r = run("--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.strip(), r"^\d+\.\d+\.\d+$")

    def test_help_lists_the_first_run_command(self):
        r = run("help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("omarchy-eq calibrate", r.stdout)

    def test_unknown_command_exits_nonzero(self):
        self.assertNotEqual(run("nonsense-command").returncode, 0)


class TestInterruptHandling(unittest.TestCase):
    """Ctrl-C during a sweep has to leave, not resume the loop.

    A bare `trap handler INT` returns into the interrupted loop. Because the
    handler also deletes the measurement tempdir, the sweep carried on with its
    working directory gone -- recording -120 for every remaining band and then
    writing that to response.json. The handler must exit.
    """

    def test_int_and_term_handlers_exit(self):
        with open(EXE) as fh:
            body = fh.read()
        self.assertIn("trap 'restore_audio; exit 130' INT TERM", body)
        # The EXIT trap stays bare: it fires on the way out either way.
        self.assertIn("trap restore_audio EXIT\n", body)

    def test_restore_audio_is_idempotent(self):
        # It runs from both traps, so it must be safe to call twice.
        with open(EXE) as fh:
            body = fh.read()
        self.assertIn("(( RESTORED )) && return 0", body)


class TestCommaDecimalLocale(unittest.TestCase):
    """The median+snr pipeline under a comma-decimal locale.

    `sort -g` converts with the locale's strtod. Under de_DE.UTF-8 the '.' in
    "-45.23" terminates the number, so every repeat of a band reduces to the
    same integer, the repeats compare equal, and the tie is broken by string
    order -- handing back the median of a mis-sorted list. Nothing raises and
    the value stays a well-formed float, which is what makes it worth a test.

    Asserting only that the output parses with float() would pass with or
    without the fix: gawk keeps '.' outside --posix mode, so no comma is ever
    produced for python to choke on. The assertion that bites is the value.
    """

    # Chosen so the numeric median and the string-order median are different
    # elements: -46.20 sorts first either way, but "-45.23" < "-45.90" as text
    # while -45.90 < -45.23 as numbers.
    VALS = ["-46.20", "-45.90", "-45.23"]
    FLOOR = "-70.50"
    WANT_MED = -45.90
    WANT_SNR = 24.60

    @classmethod
    def setUpClass(cls):
        if not shutil.which("localedef"):
            raise unittest.SkipTest("localedef not available")
        cls._dir = tempfile.mkdtemp(prefix="omarchy-eq-locale-")
        target = os.path.join(cls._dir, "de_DE.UTF-8")
        built = subprocess.run(
            ["localedef", "-i", "de_DE", "-f", "UTF-8", target],
            capture_output=True, text=True)
        if built.returncode != 0:
            shutil.rmtree(cls._dir, ignore_errors=True)
            raise unittest.SkipTest(
                "could not build de_DE.UTF-8: %s" % built.stderr.strip())
        cls.env = dict(os.environ, LOCPATH=cls._dir, LC_ALL="de_DE.UTF-8")
        # A locale that fails to load makes glibc fall back to C, which would
        # quietly turn this into a test of nothing. Prove the comma took first.
        probe = subprocess.run(["locale", "-k", "decimal_point"],
                               capture_output=True, text=True, env=cls.env)
        if 'decimal_point=","' not in probe.stdout:
            shutil.rmtree(cls._dir, ignore_errors=True)
            raise unittest.SkipTest(
                "de_DE.UTF-8 did not take; got %r" % probe.stdout.strip())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._dir, ignore_errors=True)

    def pipeline(self, guarded):
        """Run cmd_measure's median+snr pair, with and without the sort guard."""
        script = SWEEP_PIPELINE % {
            "vals": " ".join(self.VALS),
            "sort": "LC_ALL=C sort -g" if guarded else "sort -g",
            "floor": self.FLOOR,
        }
        r = subprocess.run(["bash", "-c", script], capture_output=True,
                           text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def test_guarded_pipeline_gives_the_right_median_and_parses(self):
        med, snr = self.pipeline(guarded=True)
        # float() is the real downstream consumer: state.py add-run reads run.txt.
        self.assertAlmostEqual(float(med), self.WANT_MED, places=2)
        self.assertAlmostEqual(float(snr), self.WANT_SNR, places=2)

    def test_unguarded_sort_is_what_the_guard_is_for(self):
        # Pins the bug itself rather than trusting the comment in bin/omarchy-eq.
        # If a future coreutils stops using strtod here this fails loudly and the
        # guard can be reconsidered -- it does not silently become vacuous.
        med, _ = self.pipeline(guarded=False)
        self.assertNotAlmostEqual(float(med), self.WANT_MED, places=2)

    def test_the_sweep_actually_pins_the_sort(self):
        with open(EXE) as fh:
            body = fh.read()
        self.assertIn("| LC_ALL=C sort -g |", body)


if __name__ == "__main__":
    unittest.main()
