"""Lexical ablations, JSON settings and shared manual annotation pool."""

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.lexical import LexicalPreprocessor, build_bm25
from tools import run_retrieval as runner
from tools import run_experiments as experiments

ROOT = Path(__file__).resolve().parents[1]


class LexicalExperimentsTests(unittest.TestCase):
    def test_default_preserves_original_normalization_including_scientific_tokens(self):
        self.assertEqual(LexicalPreprocessor()("Be-7 AND Be7; Lithium!"), ["be", "7", "and", "be7", "lithium"])

    def test_stopwords_are_applied_to_documents_and_questions_without_downloads(self):
        lexical = LexicalPreprocessor(stopwords=True)
        self.assertEqual(lexical("the lithium and target"), ["lithium", "target"])
        self.assertEqual(lexical("Lithium AND the TARGET?"), ["lithium", "target"])
        self.assertGreater(lexical.metadata["stopwords_count"], 100)

    def test_stemming_links_inflected_forms(self):
        lexical = LexicalPreprocessor(stemming=True)
        self.assertEqual(lexical("classifications learning"), lexical("classification learned"))
        self.assertEqual(lexical("Be7 lithium 53"), ["be7", "lithium", "53"])

    def test_stopwords_before_stemming_and_negations_can_be_preserved(self):
        lexical = LexicalPreprocessor(True, True, preserve_words=["not"])
        self.assertEqual(lexical("the target is not learning"), ["target", "not", "learn"])
        self.assertNotIn("not", LexicalPreprocessor(True)("not learning"))

    def test_custom_stopwords_and_empty_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "words.txt"
            path.write_text("# comment\ntarget\nlithium\n")
            lexical = LexicalPreprocessor(True, stopwords_file=path)
            self.assertEqual(lexical("target lithium neutron"), ["neutron"])
        self.assertIsNone(build_bm25([[], []]))

    def test_parameters_reach_library_and_change_scores(self):
        corpus = [["lithium"] * 5 + ["target"] * 8, ["lithium", "target"], ["neutron"], ["network"], ["radiation"]]
        first = build_bm25(corpus, k1=0.5, b=0.5)
        second = build_bm25(corpus, k1=1.5, b=1)
        self.assertEqual((first.k1, first.b), (0.5, 0.5))
        self.assertNotEqual(first.get_scores(["target"]).tolist(), second.get_scores(["target"]).tolist())
        for kwargs in ({"k1": 0}, {"k1": float("nan")}, {"b": 1.1}, {"epsilon": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_bm25(corpus, **kwargs)


class ExperimentConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def config_file(self, values):
        path = self.directory / "config.json"
        path.write_text(json.dumps(values))
        return path

    def test_json_settings_and_explicit_overrides(self):
        path = self.config_file({"bm25_k1": 0.5, "bm25_b": 1, "bm25_stopwords": True,
                                 "bm25_stemming": True, "chunk_size": 900, "preserve_words": [], "corpus": "data/download_pdfs"})
        args = runner.parse_args(["--config", str(path), "--bm25-k1", "0.75", "--no-bm25-stemming"])
        self.assertEqual(args.bm25_k1, 0.75)
        self.assertEqual(args.bm25_b, 1)
        self.assertTrue(args.bm25_stopwords)
        self.assertFalse(args.bm25_stemming)
        self.assertEqual(args.chunk_size, 900)
        self.assertEqual(args.preserve_words, [])
        self.assertEqual(args.corpus, ROOT / "data/download_pdfs")

    def test_bad_keys_types_choices_and_ranges_fail(self):
        for values in ({"unknown": 1}, {"bm25_b": 2}, {"bm25_k1": 0},
                       {"bm25_stopwords": "yes"}, {"variants": ["typo"]}, {"variants": []}):
            with self.subTest(values=values), self.assertRaises(SystemExit):
                runner.parse_args(["--config", str(self.config_file(values))])

    def test_cache_boolean_can_be_overridden_both_directions(self):
        args = runner.parse_args(["--config", str(self.config_file({"no_cache": True})), "--use-cache"])
        self.assertFalse(args.no_cache)
        args = runner.parse_args(["--config", str(self.config_file({"no_cache": False})), "--no-cache"])
        self.assertTrue(args.no_cache)

    def test_requested_grid_has_exact_combinations(self):
        config = experiments.load_grid(ROOT / "experiments/configs/bm25-grid.json")
        # User-editable parameter values must not change this regression fixture.
        config = {**config, "k1": [0.5, 0.75, 1, 1.5], "b": [0.5, 0.75, 1]}
        cases = experiments.build_cases(config)
        self.assertEqual(len(cases), 48)
        self.assertEqual(len({case["id"] for case in cases}), 48)
        self.assertEqual({case["k1"] for case in cases}, {0.5, 0.75, 1, 1.5})
        self.assertEqual({case["b"] for case in cases}, {0.5, 0.75, 1})
        self.assertEqual(len(config["controls"]) + len(cases) * len(config["variants"]), 195)
        for variant in config["controls"]:
            self.assertNotIn("bm25", runner.variant_weights(variant))

    def test_invalid_grids_and_missing_controls_are_rejected(self):
        original = experiments.load_grid(ROOT / "experiments/configs/bm25-grid.json")
        for name, value in (("k1", [0.5, 0.5]), ("b", [1.1]), ("controls", ["dense"]),
                            ("preserve_words", "not"), ("unrecognized", 1)):
            config = copy.deepcopy(original)
            config[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                experiments.load_grid(self.config_file(config))

    def test_review_pool_deduplicates_across_grid_and_controls(self):
        chunks = [{"index": 0, "chunk_id": "paper.pdf#0", "document_id": "paper", "title": "Paper", "text": "Full evidence.",
                   "pdf_path": str(self.directory / "paper.pdf"), "section": None, "text_sha256": "text", "document_sha256": "pdf"}]
        results = [{"case_id": case, "question_id": "1", "variant": variant,
                    "hits": [{"index": 0, "rank": 1, "score": 0.1}]} for case, variant in (("controls", "dense"), ("case", "hybrid"))]
        count = experiments.export_suite_review(self.directory, [{"id": "1", "question": "Question?"}], chunks, results)
        self.assertEqual(count, 1)
        with (self.directory / "judgments.csv").open(newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["relevance"], "")
        self.assertEqual(row["text_sha256"], "text")
        self.assertEqual(row["text"], "Full evidence.")
        comparison = experiments.compare_rankings([{"index": 0}], [{"index": 1}])
        self.assertEqual(comparison["jaccard"], 0)
        self.assertTrue(comparison["top1_changed"])


if __name__ == "__main__":
    unittest.main()
