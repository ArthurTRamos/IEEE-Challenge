"""Local review workflow: cache validity, provenance and unjudged exports."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.retrieval_utils import rrf_fuse
from tools import run_retrieval as runner


class LocalRetrievalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_recursive_discovery_ignores_virtualenv_and_does_not_infer_relevance(self):
        folder = self.root / "nested"
        folder.mkdir()
        (folder / "AI-001.pdf").write_bytes(b"pdf")
        (self.root / ".venv").mkdir()
        (self.root / ".venv/ignored.pdf").write_bytes(b"pdf")
        (folder / "catalog.jsonl").write_text(json.dumps({"id": "AI-001", "title": "Paper", "questions": "1", "selection_role": "central", "relevance_judgment": "relevant"}) + "\n"
                                                   + json.dumps({"id": "AI-002", "title": "Missing"}) + "\n")
        documents, missing = runner.discover_documents(self.root)
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["relative_path"], "nested/AI-001.pdf")
        self.assertEqual(missing, ["AI-002"])
        self.assertNotIn("relevance_judgment", documents[0])
        self.assertNotIn("questions", documents[0])
        with self.assertRaisesRegex(ValueError, "not found"):
            runner.discover_documents(self.root, ["unknown"])

    def test_duplicate_question_ids_are_rejected(self):
        path = self.root / "questions.json"
        path.write_text(json.dumps([{"id": 1, "question": "first"}, {"id": "1", "question": "second"}]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            runner.load_questions(path)

    def test_question_selection_preserves_requested_order_and_answers(self):
        path = self.root / "questions.json"
        path.write_text(json.dumps([{"id": i, "question": f"Question {i}", "answer": f"Answer {i}"}
                                    for i in (1, 5, 7, 13, 23)]))
        selected = runner.load_questions(path, [7, 1, 5, 13, 23])
        self.assertEqual([q["id"] for q in selected], ["7", "1", "5", "13", "23"])
        self.assertEqual(selected[0]["answer"], "Answer 7")
        for ids in ([99], [7, 7], []):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                runner.load_questions(path, ids)

    def test_text_cache_avoids_reparsing_and_is_invalidated_by_extractor(self):
        output = self.root / "output"
        output.mkdir()
        document = {"sha256": "pdf-hash", "relative_path": "nested/paper.pdf", "document_id": "paper",
                    "pdf_path": "unused.pdf", "title": "Paper", "domain": "DONES"}
        converter = Mock()
        converter.convert.return_value = SimpleNamespace(document=SimpleNamespace(export_to_markdown=lambda: "Evidence", pages={1: None}), status=SimpleNamespace(value="success"), errors=[])
        factory = Mock(return_value=converter)
        sources = lambda name, texts: [{"chunk_id": name + "#0", "document": name, "section": None}]
        first, _ = runner.prepare_chunks([document], output, self.root / "cache", {"v": 1}, factory, lambda t: [t], sources)
        second, documents = runner.prepare_chunks([document], output, self.root / "cache", {"v": 1}, factory, lambda t: [t], sources)
        self.assertEqual(first, second)
        self.assertTrue(documents[0]["text_cache_hit"])
        converter.convert.assert_called_once()
        runner.prepare_chunks([document], output, self.root / "cache", {"v": 2}, factory, lambda t: [t], sources)
        self.assertEqual(converter.convert.call_count, 2)

    def test_failed_pdf_is_recorded_and_other_sources_stay_aligned(self):
        output = self.root / "output"
        output.mkdir()
        documents = [{"sha256": name, "relative_path": name + ".pdf", "document_id": name,
                      "pdf_path": name, "title": name, "domain": "DONES"} for name in ("bad", "good")]
        converter = Mock()
        converter.convert.side_effect = [ValueError("broken"), SimpleNamespace(document=SimpleNamespace(export_to_markdown=lambda: "Evidence", pages={}), errors=[])]
        sources = lambda name, texts: [{"chunk_id": name + "#0", "document": name, "section": None}]
        chunks, processed = runner.prepare_chunks(documents, output, None, {}, lambda: converter, lambda t: [t], sources)
        self.assertEqual(processed[0]["status"], "failed")
        self.assertEqual(chunks[0]["index"], 0)
        self.assertEqual(chunks[0]["document_id"], "good")

    def test_review_has_one_unjudged_row_per_question_chunk_and_full_text(self):
        text = "Complete evidence\nwith | tables and ~~~ symbols."
        chunks = [{"index": 0, "chunk_id": "a.pdf#0", "document_id": "a", "title": "Title | Pipe",
                   "section": "Methods", "pdf_path": str(self.root / "a.pdf"), "text": text}]
        questions = [{"id": "1", "question": "Question?", "answer": "GOLD"}]
        results = [{"question_id": "1", "variant": variant, "hits": [{"index": 0, "rank": 1, "score": 0.1}]} for variant in ("dense", "graph")]
        runner.export_review(self.root, questions, chunks, results, ["dense", "graph"])
        with (self.root / "judgments.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relevance"], "")
        self.assertEqual(rows[0]["text"], text)
        self.assertEqual(rows[0]["dense_rank"], "1")
        self.assertEqual(rows[0]["graph_rank"], "1")
        markdown = (self.root / "questions/q-001.md").read_text()
        self.assertIn(text, markdown)
        self.assertIn("~~~~text", markdown)
        self.assertNotIn("GOLD", markdown)

    def test_weights_isolate_dense_and_recover_original_hybrid_formula(self):
        rankings = {"dense": [0, 1], "bm25": [2, 1], "kg_graph": [2]}
        self.assertEqual(rrf_fuse(rankings, runner.variant_weights("dense"))[0], [0, 1])
        order, scores = rrf_fuse(rankings, runner.variant_weights("hybrid"))
        self.assertEqual(order, [1, 0, 2])
        self.assertAlmostEqual(scores[1], 2 / 62)
        with self.assertRaises(ValueError):
            rrf_fuse(rankings, {"dense": float("nan")})
        with self.assertRaises(ValueError):
            rrf_fuse({"dense": [0, 0]}, {"dense": 1})

    def test_runner_never_loads_olmo_or_uses_reference_answers_for_retrieval(self):
        from src import documents as pipeline
        corpus = self.root / "corpus"
        corpus.mkdir()
        (corpus / "DONES-001.pdf").write_bytes(b"fixture")
        questions = self.root / "questions.json"
        questions.write_text(json.dumps([{"id": 1, "question": "Lithium?", "answer": "GOLD_DO_NOT_SEARCH"}]))
        converter = Mock()
        converter.convert.return_value = SimpleNamespace(document=SimpleNamespace(export_to_markdown=lambda: "Lithium evidence.", pages={1: None}), errors=[])
        encoder = Mock()
        encoded_texts = []
        def encode(texts, **kwargs):
            encoded_texts.extend(texts)
            return np.tile([1.0, 0.0], (len(texts), 1))
        encoder.encode.side_effect = encode
        encoder.tokenizer.side_effect = lambda texts, **kwargs: {"input_ids": [[1, 2] for _ in texts]}
        encoder.max_seq_length = 256
        encoder.get_embedding_dimension.return_value = 2
        args = SimpleNamespace(output=self.root / "run", corpus=corpus, questions=questions, embed_model=self.root / "model",
                               no_cache=True, cache=self.root / "cache", document_ids=None, limit_documents=None, limit_questions=None,
                               embedding_device="cpu", threads=1, batch_size=8, chunk_size=800, chunk_overlap=150, variants=["dense", "hybrid"],
                               top_k=1, candidate_depth=100, rrf_k=60, dense_weight=1, bm25_weight=1, kg_weight=0.5, include_reference_answers=False)
        with patch.object(runner, "tree_fingerprint", return_value="model-hash"), \
             patch.object(pipeline, "create_converter", new=lambda **kwargs: converter), \
             patch("sentence_transformers.SentenceTransformer", return_value=encoder) as encoder_factory, \
             patch("transformers.AutoModelForCausalLM.from_pretrained", side_effect=AssertionError("OLMo must not load")), \
             patch("transformers.AutoTokenizer.from_pretrained", side_effect=AssertionError("OLMo tokenizer must not load")):
            summary = runner.run(args)
            encoder_factory.reset_mock()
            args.output = self.root / "bm25-only"
            args.variants = ["bm25"]
            lexical_summary = runner.run(args)
            encoder_factory.assert_not_called()
            self.assertFalse(lexical_summary["embedding_audit_performed"])
        self.assertEqual(summary["annotation_status"], "unjudged")
        self.assertIsNone(summary["quality_metrics"])
        self.assertEqual(summary["questions"], 1)
        self.assertTrue(all("GOLD" not in text for text in encoded_texts))
        self.assertNotIn("GOLD", (args.output / "questions/q-001.md").read_text())
        self.assertEqual(json.loads((args.output / "status.json").read_text())["state"], "complete")
        with self.assertRaisesRegex(ValueError, "not empty"):
            runner.run(args)


if __name__ == "__main__":
    unittest.main()
