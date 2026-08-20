import math
import os
import struct
import tempfile
import unittest
import wave

import context  # noqa: F401
import analyze

SR = 48000


def write_wav(path, frames, ch=1):
    w = wave.open(path, "wb")
    w.setnchannels(ch)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(b"".join(struct.pack("<h", s) * ch for s in frames))
    w.close()


def sine(fc, dur=1.0, amp=0.1):
    n = int(SR * dur)
    return [int(amp * 32767 * math.sin(2 * math.pi * fc * i / SR)) for i in range(n)]


def warble(fc, dur=1.0, amp=0.1, dev=1 / 6.0, rate=5.0):
    n, ph, out = int(SR * dur), 0.0, []
    for i in range(n):
        f = fc * (2.0 ** (dev * math.sin(2 * math.pi * rate * i / SR)))
        ph += 2 * math.pi * f / SR
        out.append(int(amp * 32767 * math.sin(ph)))
    return out


def rms_dbfs(amp):
    """dBFS of a sine's RMS -- what band_level reports."""
    return 20 * math.log10(amp / math.sqrt(2))


def peak_dbfs(amp):
    """dBFS of a sine's peak -- what goertzel reports. 3.01 dB above RMS."""
    return 20 * math.log10(amp)


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _path(self, name="t.wav"):
        return os.path.join(self.dir, name)

    def test_goertzel_recovers_a_pure_tone_level(self):
        p = self._path()
        write_wav(p, sine(1000, amp=0.1))
        s, sr = analyze.read_mono(p)
        self.assertAlmostEqual(analyze.goertzel(s, sr, 1000), peak_dbfs(0.1), delta=0.5)

    def test_goertzel_and_band_differ_by_the_sine_crest_factor(self):
        # goertzel is peak-referenced, band_level is RMS-referenced. Documenting
        # the 3.01 dB offset so nobody "fixes" one to match the other.
        p = self._path()
        write_wav(p, sine(1000, amp=0.1))
        s, sr = analyze.read_mono(p)
        self.assertAlmostEqual(analyze.goertzel(s, sr, 1000)
                               - analyze.band_level(s, sr, 1000), 3.01, delta=0.5)

    def test_goertzel_rejects_off_frequency_energy(self):
        p = self._path()
        write_wav(p, sine(1000, amp=0.1))
        s, sr = analyze.read_mono(p)
        self.assertLess(analyze.goertzel(s, sr, 3000), -60.0)

    def test_band_recovers_a_warble_level_across_the_spectrum(self):
        # The reason band_level exists: a warble spreads energy over 1/3 octave,
        # so a single Goertzel bin no longer sees it.
        for fc in (100, 1000, 8000):
            p = self._path("w%d.wav" % fc)
            write_wav(p, warble(fc, amp=0.1))
            s, sr = analyze.read_mono(p)
            self.assertAlmostEqual(analyze.band_level(s, sr, fc),
                                   rms_dbfs(0.1), delta=1.5,
                                   msg="band level wrong at %d Hz" % fc)

    def test_goertzel_badly_underreads_a_warble(self):
        # Regression guard: if someone "simplifies" measure back to goertzel,
        # the readings collapse. This documents why.
        p = self._path()
        write_wav(p, warble(1000, amp=0.1))
        s, sr = analyze.read_mono(p)
        self.assertLess(analyze.goertzel(s, sr, 1000), analyze.band_level(s, sr, 1000) - 20)

    def test_band_rejects_out_of_band_tone(self):
        p = self._path()
        write_wav(p, sine(1000, amp=0.1))
        s, sr = analyze.read_mono(p)
        self.assertLess(analyze.band_level(s, sr, 4000), -50.0)

    def test_silence_reads_as_floor(self):
        p = self._path()
        write_wav(p, [0] * SR)
        s, sr = analyze.read_mono(p)
        self.assertLessEqual(analyze.band_level(s, sr, 1000), -110.0)

    def test_empty_recording_does_not_crash(self):
        p = self._path()
        write_wav(p, [])
        s, sr = analyze.read_mono(p)
        self.assertEqual(analyze.band_level(s, sr, 1000), -120.0)

    def test_stereo_takes_channel_zero(self):
        p = self._path()
        write_wav(p, sine(1000, amp=0.1), ch=2)
        s, sr = analyze.read_mono(p)
        self.assertAlmostEqual(analyze.goertzel(s, sr, 1000), peak_dbfs(0.1), delta=0.5)


if __name__ == "__main__":
    unittest.main()
