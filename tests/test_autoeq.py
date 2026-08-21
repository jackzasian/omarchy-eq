"""Searching the AutoEQ catalogue, and refusing to guess.

Nothing here touches the network: the index is plain text, so the parser and the
matcher can be exercised against a fixture. The matcher is the part worth
testing hard, because auto-setup acts on its answer unattended.
"""
import unittest

import context  # noqa: F401
import autoeq

INDEX = """# Index
This is a list of all equalization profiles.

- [Sennheiser HD 650](./oratory1990/over-ear/Sennheiser%20HD%20650) by oratory1990
- [Sennheiser HD 650](./crinacle/GRAS%2043AG-7%20over-ear/Sennheiser%20HD%20650) by crinacle on GRAS 43AG-7
- [Sennheiser HD 650](./Rtings/HMS%20II.3%20over-ear/Sennheiser%20HD%20650) by Rtings on HMS II.3
- [Sony WH-1000XM4](./oratory1990/over-ear/Sony%20WH-1000XM4) by oratory1990
- [Nothing ear](./DHRME/in-ear/Nothing%20ear) by DHRME
- [Jabra Elite 75t](./oratory1990/in-ear/Jabra%20Elite%2075t) by oratory1990
- [Jabra Elite Active 75t](./Rtings/HMS%20II.3%20in-ear/Jabra%20Elite%20Active%2075t) by Rtings on HMS II.3
- [Moondrop Blessing 2](./crinacle/711%20in-ear/Moondrop%20Blessing%202) by crinacle on 711
"""


class TestParseIndex(unittest.TestCase):
    def setUp(self):
        self.items = autoeq.parse_index(INDEX)

    def test_reads_every_entry(self):
        self.assertEqual(len(self.items), 8)

    def test_decodes_the_url_escaped_path(self):
        hd = self.items[0]
        self.assertEqual(hd["path"], "oratory1990/over-ear/Sennheiser HD 650")
        self.assertEqual(hd["dir"], "Sennheiser HD 650")

    def test_separates_source_from_measurement_target(self):
        self.assertEqual(self.items[0]["source"], "oratory1990")
        self.assertEqual(self.items[0]["target"], "")
        self.assertEqual(self.items[1]["source"], "crinacle")
        self.assertEqual(self.items[1]["target"], "GRAS 43AG-7")

    def test_ignores_prose(self):
        for item in self.items:
            self.assertTrue(item["path"])


class TestNormalise(unittest.TestCase):
    def test_model_numbers_compare_equal_however_they_are_punctuated(self):
        for variant in ("WH-1000XM4", "wh 1000xm4", "WH_1000XM4"):
            self.assertEqual(autoeq.norm(variant), "wh 1000xm4")


class TestScore(unittest.TestCase):
    def entry(self, name):
        return {"name": name, "source": "x", "target": "", "path": "p", "dir": name}

    def test_exact_match_scores_highest(self):
        self.assertEqual(autoeq.score(self.entry("Sony WH-1000XM4"),
                                      "sony wh-1000xm4"), 100.0)

    def test_a_missing_brand_still_matches_strongly(self):
        # The device name PipeWire reports often omits the manufacturer.
        s = autoeq.score(self.entry("Sony WH-1000XM4"), "WH-1000XM4")
        self.assertGreaterEqual(s, autoeq.STRONG)

    def test_an_extra_word_in_the_query_is_treated_as_a_different_product(self):
        # "Nothing Ear (open)" is not "Nothing ear". An earlier symmetric
        # scoring scored this pair 87 and would have installed the wrong curve.
        s = autoeq.score(self.entry("Nothing ear"), "Nothing Ear (open)")
        self.assertLess(s, autoeq.STRONG)

    def test_unrelated_names_score_nothing(self):
        self.assertEqual(autoeq.score(self.entry("Sony WH-1000XM4"),
                                      "Sonos Roam"), 0.0)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.items = autoeq.parse_index(INDEX)

    def test_ranks_the_preferred_source_first_among_equals(self):
        hits = autoeq.search("Sennheiser HD 650", 5, items=self.items)
        self.assertEqual([h[1]["source"] for h in hits][:3],
                         ["oratory1990", "crinacle", "Rtings"])

    def test_returns_nothing_for_an_unrelated_query(self):
        self.assertEqual(autoeq.search("Sonos Roam", 5, items=self.items), [])


class TestMatchDevice(unittest.TestCase):
    """Auto-setup's gatekeeper. Every test here is a refusal or a hit."""

    def setUp(self):
        self.items = autoeq.parse_index(INDEX)

    def match(self, description):
        return autoeq.match_device(description, items=self.items)

    def test_matches_an_exact_device_name(self):
        hit = self.match("Sony WH-1000XM4")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1]["name"], "Sony WH-1000XM4")

    def test_strips_the_transport_words_pipewire_adds(self):
        hit = self.match("WH-1000XM4 (Bluetooth Stereo)")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1]["name"], "Sony WH-1000XM4")

    def test_refuses_a_product_variant_it_does_not_have(self):
        self.assertIsNone(self.match("Nothing Ear (open)"))

    def test_refuses_the_built_in_speakers(self):
        self.assertIsNone(self.match("Built-in Audio Analog Stereo"))

    def test_refuses_an_output_that_is_not_a_headphone(self):
        self.assertIsNone(self.match("Sonos Roam"))

    def test_several_sources_for_one_model_is_not_ambiguity(self):
        # Three rigs measured the HD 650. That is one answer with a source to
        # pick, not a coin flip -- SOURCE_RANK picks it.
        hit = self.match("Sennheiser HD 650")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1]["source"], "oratory1990")

    def test_prefers_the_plain_model_over_a_similarly_named_variant(self):
        hit = self.match("Jabra Elite 75t")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1]["name"], "Jabra Elite 75t")


class TestFileUrl(unittest.TestCase):
    def setUp(self):
        self.entry = autoeq.parse_index(INDEX)[0]

    def test_names_the_file_after_the_directory(self):
        url = autoeq.file_url(self.entry, "parametric")
        self.assertTrue(url.endswith("Sennheiser%20HD%20650%20ParametricEQ.txt"))

    def test_impulse_response_url_carries_the_rate(self):
        url = autoeq.file_url(self.entry, "convolution", 44100)
        self.assertIn("minimum%20phase%2044100Hz.wav", url)

    def test_every_format_has_a_url(self):
        for fmt in autoeq.FORMATS:
            self.assertTrue(autoeq.file_url(self.entry, fmt).startswith("https://"))


if __name__ == "__main__":
    unittest.main()
