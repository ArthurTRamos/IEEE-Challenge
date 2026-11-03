"""Run with: .venv/bin/python -m unittest discover -s tests -v.

Uses real NumPy and BM25, with PDF parsing and model calls replaced by mocks.
No model weights, GPU, network access or evaluation corpus are needed.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from rank_bm25 import BM25Okapi

from src import main as rag


class LexicalIndexTests(unittest.TestCase):
    def test_tokenization_preserves_unicode_numbers_and_normalizes_case(self):
        self.assertEqual(
            rag._lexical_tokens("IFMIF-DONES: Nêutrons, H100; 3.12!"),
            ["ifmif", "dones", "nêutrons", "h100", "3", "12"],
        )
        self.assertEqual(rag._lexical_tokens(" \n---!?"), [])

    def build_index(self, documents):
        """Build the real index from fake PDFs and fixed embedding vectors."""
        converter = Mock()

        def convert(path):
            text = documents[Path(path).name]
            if isinstance(text, Exception):
                raise text
            return SimpleNamespace(document=SimpleNamespace(export_to_markdown=lambda: text))

        converter.convert.side_effect = convert
        embedder = Mock()
        embedder.encode.side_effect = lambda chunks, **kwargs: np.eye(len(chunks))
        with tempfile.TemporaryDirectory() as directory:
            for name in documents:
                Path(directory, name).touch()
            with patch.object(rag, "_docling_converter", return_value=converter), patch.object(
                rag, "SentenceTransformer", return_value=embedder
            ):
                result = rag._build_index(directory)
        return result, converter, embedder

    def test_bm25_and_embeddings_share_chunk_positions(self):
        (chunks, embeddings, _, bm25), _, embedder = self.build_index({
            "c.pdf": "Neural networks learn representations.",
            "a.pdf": "IFMIF DONES uses a lithium target.",
            "b.pdf": "Fusion materials withstand irradiation.",
        })
        self.assertIsInstance(bm25, BM25Okapi)
        self.assertEqual(bm25.corpus_size, len(chunks))
        self.assertEqual(embeddings.shape[0], len(chunks))
        self.assertEqual(embeddings.dtype, np.float32)
        scores = bm25.get_scores(rag._lexical_tokens("LITHIUM target!"))
        self.assertGreater(scores[0], 0)
        self.assertEqual(int(np.argmax(scores)), 0)
        self.assertIn("lithium", chunks[0])
        np.testing.assert_array_equal(scores[1:], [0, 0])
        self.assertEqual(bm25.doc_freqs[0]["lithium"], 1)
        self.assertNotIn("lithium", bm25.doc_freqs[1])
        embedder.encode.assert_called_once_with(
            chunks, normalize_embeddings=True, show_progress_bar=False, batch_size=64
        )

    def test_long_documents_index_every_generated_chunk(self):
        paragraphs = [f"Section {i}: " + "lithium " * 70 for i in range(4)]
        text = "\n\n".join(paragraphs)
        (chunks, embeddings, _, bm25), _, _ = self.build_index({"a.pdf": text})
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks, rag._chunk_markdown(text))
        self.assertEqual(bm25.corpus_size, len(chunks))
        self.assertEqual(len(embeddings), len(chunks))
        for chunk, frequencies in zip(chunks, bm25.doc_freqs):
            self.assertEqual(frequencies["lithium"], rag._lexical_tokens(chunk).count("lithium"))

    def test_unreadable_pdf_does_not_shift_chunk_alignment(self):
        (chunks, embeddings, _, bm25), converter, _ = self.build_index({
            "a.pdf": ValueError("invalid PDF"),
            "b.pdf": "Lithium target.",
            "c.pdf": "Neural networks.",
            "d.pdf": "Particle accelerator.",
        })
        self.assertEqual(converter.convert.call_count, 4)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(embeddings), bm25.corpus_size)
        self.assertIn("Lithium", chunks[0])
        self.assertEqual(int(np.argmax(bm25.get_scores(["lithium"]))), 0)

    def test_empty_corpus_skips_embedding_and_bm25_construction(self):
        (chunks, embeddings, _, bm25), _, embedder = self.build_index({})
        self.assertEqual(chunks, [])
        self.assertEqual(embeddings.shape, (0, 0))
        self.assertIsNone(bm25)
        embedder.encode.assert_not_called()

    def test_punctuation_only_chunks_have_no_lexical_index(self):
        (chunks, embeddings, _, bm25), _, _ = self.build_index({"a.pdf": "--- !!!"})
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(embeddings), 1)
        self.assertIsNone(bm25)


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self):
        # Dot products with [1, 0] give dense ranks 0, 1, 2.
        self.embeddings = np.array([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32)
        self.embedder = Mock()
        self.embedder.encode.return_value = np.array([[1, 0]], dtype=np.float32)

    def test_rrf_promotes_agreement_between_rankings(self):
        bm25 = Mock()
        bm25.get_scores.return_value = np.array([0, 2, 10])
        # Dense candidates: [0, 1]; lexical candidates: [2, 1].
        # Chunk 1 has 2/62, while chunks 0 and 2 each have 1/61.
        with patch.object(rag, "RETRIEVAL_TOP_K", 2):
            order = rag._hybrid_order("LITHIUM!", self.embeddings, self.embedder, bm25)
        self.assertEqual(order, [1, 0, 2])
        self.assertEqual(len(order), len(set(order)))
        bm25.get_scores.assert_called_once_with(["lithium"])

    def test_rrf_uses_ranks_instead_of_raw_bm25_score_scale(self):
        bm25 = Mock()
        orders = []
        for scores in ([0, 2, 10], [0, 2000, 1_000_000]):
            bm25.get_scores.return_value = np.array(scores)
            with patch.object(rag, "RETRIEVAL_TOP_K", 2):
                orders.append(rag._hybrid_order("target", self.embeddings, self.embedder, bm25))
        self.assertEqual(orders, [[1, 0, 2], [1, 0, 2]])

    def test_real_bm25_adds_a_match_outside_dense_candidates(self):
        chunks = ["Neural networks.", "Fusion materials.", "Lithium target."]
        bm25 = BM25Okapi([rag._lexical_tokens(chunk) for chunk in chunks])
        with patch.object(rag, "RETRIEVAL_TOP_K", 1):
            order = rag._hybrid_order("LITHIUM", self.embeddings, self.embedder, bm25)
        self.assertEqual(order, [0, 2])

    def test_unmatched_query_does_not_add_zero_score_candidates(self):
        bm25 = BM25Okapi([["neural"], ["fusion"], ["lithium"]])
        with patch.object(rag, "RETRIEVAL_TOP_K", 1):
            order = rag._hybrid_order("unknown", self.embeddings, self.embedder, bm25)
        self.assertEqual(order, [0])

    def test_missing_lexical_index_uses_dense_ranking(self):
        self.assertEqual(
            rag._hybrid_order("target", self.embeddings, self.embedder, None), [0, 1, 2]
        )
        self.embedder.encode.assert_called_once_with(
            ["target"], normalize_embeddings=True, show_progress_bar=False
        )

    def test_empty_index_does_not_encode_query(self):
        bm25 = Mock()
        self.assertEqual(
            rag._hybrid_order("target", np.empty((0, 0)), self.embedder, bm25), []
        )
        self.embedder.encode.assert_not_called()
        bm25.get_scores.assert_not_called()

    def test_equal_dense_scores_have_deterministic_chunk_order(self):
        embeddings = np.tile([1, 0], (3, 1))
        self.assertEqual(
            rag._hybrid_order("target", embeddings, self.embedder, None), [0, 1, 2]
        )

    def test_context_consumes_fused_order_within_chunk_budget(self):
        bm25 = Mock()
        bm25.get_scores.return_value = np.array([0, 2, 10])
        chunks = ["dense evidence", "shared evidence", "lexical evidence"]
        tokenizer = Mock()
        tokenizer.encode.side_effect = str.split
        with patch.object(rag, "RETRIEVAL_TOP_K", 2):
            context = rag._build_context(
                "target", chunks, self.embeddings, self.embedder, tokenizer, bm25, max_tokens=4
            )
        self.assertIn("[Fragment 1]\nshared evidence", context)
        self.assertIn("[Fragment 2]\ndense evidence", context)
        self.assertNotIn("lexical evidence", context)


if __name__ == "__main__":
    unittest.main()
