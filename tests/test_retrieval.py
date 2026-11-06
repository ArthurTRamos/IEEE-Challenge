"""Run with: .venv/bin/python -m unittest discover -s tests -v.

Uses real NumPy and BM25, with PDF parsing and model calls replaced by mocks.
No model weights, GPU, network access or evaluation corpus are needed.
"""

import tempfile
import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from rank_bm25 import BM25Okapi

from src import main as rag
from src.kg_retrieval import EntityMatcher, GraphConfig, KGChunkIndex, LINK_PREDICATE


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
        (chunks, embeddings, _, bm25, sources), _, embedder = self.build_index({
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
        self.assertEqual(sources[0], {"chunk_id": "a.pdf#0", "document": "a.pdf", "section": None})
        self.assertEqual(sources[1]["document"], "b.pdf")
        embedder.encode.assert_called_once_with(
            chunks, normalize_embeddings=True, show_progress_bar=False, batch_size=64
        )

    def test_long_documents_index_every_generated_chunk(self):
        paragraphs = [f"Section {i}: " + "lithium " * 70 for i in range(4)]
        text = "\n\n".join(paragraphs)
        (chunks, embeddings, _, bm25, sources), _, _ = self.build_index({"a.pdf": text})
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks, rag._chunk_markdown(text))
        self.assertEqual(bm25.corpus_size, len(chunks))
        self.assertEqual(len(embeddings), len(chunks))
        self.assertEqual(len(sources), len(chunks))
        self.assertEqual(len({s["chunk_id"] for s in sources}), len(chunks))
        for chunk, frequencies in zip(chunks, bm25.doc_freqs):
            self.assertEqual(frequencies["lithium"], rag._lexical_tokens(chunk).count("lithium"))

    def test_unreadable_pdf_does_not_shift_chunk_alignment(self):
        (chunks, embeddings, _, bm25, sources), converter, _ = self.build_index({
            "a.pdf": ValueError("invalid PDF"),
            "b.pdf": "Lithium target.",
            "c.pdf": "Neural networks.",
            "d.pdf": "Particle accelerator.",
        })
        self.assertEqual(converter.convert.call_count, 4)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(embeddings), bm25.corpus_size)
        self.assertIn("Lithium", chunks[0])
        self.assertEqual(sources[0]["document"], "b.pdf")
        self.assertEqual(int(np.argmax(bm25.get_scores(["lithium"]))), 0)

    def test_empty_corpus_skips_embedding_and_bm25_construction(self):
        (chunks, embeddings, _, bm25, sources), _, embedder = self.build_index({})
        self.assertEqual(chunks, [])
        self.assertEqual(embeddings.shape, (0, 0))
        self.assertIsNone(bm25)
        self.assertEqual(sources, [])
        embedder.encode.assert_not_called()

    def test_punctuation_only_chunks_have_no_lexical_index(self):
        (chunks, embeddings, _, bm25, _), _, _ = self.build_index({"a.pdf": "--- !!!"})
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(embeddings), 1)
        self.assertIsNone(bm25)

    def test_sources_preserve_document_sections(self):
        text = "# Methods\n\n" + "lithium " * 200 + "\n\n## Results\n\nNeutron flux."
        (_, _, _, _, sources), _, _ = self.build_index({"paper.pdf": text})
        self.assertEqual(sources[0]["section"], "Methods")
        self.assertEqual(sources[-1]["section"], "Results")
        self.assertTrue(all(s["document"] == "paper.pdf" for s in sources))


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
        expected = (
            "Context extracted from a blind search over the corpus:\n\n"
            "[Fragment 1]\nshared evidence\n\n[Fragment 2]\ndense evidence\n\n---\n\n"
        )
        budget = len(expected.split())
        with patch.object(rag, "RETRIEVAL_TOP_K", 2):
            context = rag._build_context(
                "target", chunks, self.embeddings, self.embedder, tokenizer, bm25, max_tokens=budget
            )
        self.assertEqual(context, expected)
        self.assertLessEqual(len(tokenizer.encode(context)), budget)
        self.assertIn("[Fragment 1]\nshared evidence", context)
        self.assertIn("[Fragment 2]\ndense evidence", context)
        self.assertNotIn("lexical evidence", context)

    def test_kg_adds_candidates_and_uses_configured_rrf_weight(self):
        entity = {"uri": "http://dbpedia.org/resource/Beryllium-7", "label": "Beryllium-7", "aliases": ["Be7"]}
        kg = KGChunkIndex(EntityMatcher([entity]), ["Beryllium-7", "neural networks", "Be7"])
        bm25 = Mock()
        bm25.get_scores.return_value = np.array([0, 10, 0])
        with patch.object(rag, "RETRIEVAL_TOP_K", 2):
            order = rag._hybrid_order("Be7", self.embeddings, self.embedder, bm25, kg, kg_weight=0.5)
        # c1 = 1/62 + 1/61; c0 = 1/61 + 0.5/61; c2 = 0.5/62.
        self.assertEqual(order, [1, 0, 2])
        self.assertEqual(len(set(order)), 3)
        self.embedder.encode.assert_called_once()

    def test_kg_without_matches_preserves_baseline_order(self):
        kg = KGChunkIndex(EntityMatcher([{
            "uri": "http://dbpedia.org/resource/Lithium", "label": "Lithium", "aliases": []
        }]), ["Lithium", "networks", "fusion"])
        baseline = rag._hybrid_order("unknown", self.embeddings, self.embedder, None)
        self.assertEqual(rag._hybrid_order("unknown", self.embeddings, self.embedder, None, kg), baseline)

    def test_graph_only_candidate_enters_rrf_and_context(self):
        prefix = "http://dbpedia.org/resource/"
        nodes = [{"uri": prefix + name, "label": name, "aliases": []} for name in ("Alpha", "Beta")]
        chunks = ["dense evidence", "lexical evidence", "Beta evidence"]
        edges = [{"source": prefix + "Alpha", "target": prefix + "Beta", "predicate": LINK_PREDICATE}]
        graph = KGChunkIndex(EntityMatcher(nodes), chunks, edges=edges, mode="graph")
        mentions = KGChunkIndex(EntityMatcher(nodes), chunks)
        bm25 = Mock()
        bm25.get_scores.return_value = np.array([0, 10, 0])
        with patch.object(rag, "RETRIEVAL_TOP_K", 1):
            baseline = rag._hybrid_order("Alpha", self.embeddings, self.embedder, bm25, mentions)
            expanded = rag._hybrid_order("Alpha", self.embeddings, self.embedder, bm25, graph)
            tokenizer = Mock()
            tokenizer.encode.side_effect = str.split
            context = rag._build_context("Alpha", chunks, self.embeddings, self.embedder, tokenizer, bm25, kg_index=graph)
        self.assertEqual(baseline, [0, 1])
        self.assertEqual(expanded, [0, 1, 2])
        self.assertIn("Beta evidence", context)

    def test_zero_kg_weight_disables_channel(self):
        kg = Mock()
        self.assertEqual(rag._hybrid_order("target", self.embeddings, self.embedder, None, kg, kg_weight=0), [0, 1, 2])
        kg.rank.assert_not_called()

    def test_truncated_context_keeps_source_and_respects_complete_budget(self):
        tokenizer = Mock()
        tokenizer.encode.side_effect = list  # Count characters, including labels and separators.
        sources = [{"chunk_id": "paper.pdf#0", "section": "Methods"}]
        context = rag._build_context(
            "target", ["x" * 1000], self.embeddings[:1], self.embedder, tokenizer, None,
            max_tokens=150, sources=sources,
        )
        self.assertIn("[Source: paper.pdf#0]", context)
        self.assertIn("[Section: Methods]", context)
        self.assertIn("xxx", context)
        self.assertLessEqual(len(tokenizer.encode(context)), 150)
        self.assertEqual(rag._build_context(
            "target", ["evidence"], self.embeddings[:1], self.embedder, tokenizer, None,
            max_tokens=1, sources=sources,
        ), "")


class KGLoadingTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(rag._model_cache, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_kg_postings_are_built_once_per_corpus(self):
        chunks = ["Lithium target"]
        index = (chunks, np.ones((1, 2)), Mock(), Mock(), [{"chunk_id": "a.pdf#0"}])
        with patch.dict(os.environ, {"KG_MODE": "mentions"}), patch.dict(rag._cache, {}, clear=True), \
             patch.object(rag, "_build_index", return_value=index) as build, \
             patch.object(rag, "KG_PATH") as path, \
             patch.object(rag.KGChunkIndex, "from_directory") as load_kg, \
             patch.object(rag.AutoTokenizer, "from_pretrained"), \
             patch.object(rag.AutoModelForCausalLM, "from_pretrained"):
            path.exists.return_value = True
            first = rag._load("fake-model", "fake-corpus")
            second = rag._load("fake-model", "fake-corpus")
            self.assertIs(first, second)
            build.assert_called_once()
            load_kg.assert_called_once_with(path, chunks, mode="mentions", config=None)

    def test_graph_is_default_and_configuration_is_in_cache_key(self):
        index = ([], np.empty((0, 0)), Mock(), None, [])
        with patch.dict(os.environ, {}, clear=True), patch.dict(rag._cache, {}, clear=True), \
             patch.object(rag, "_build_index", return_value=index), \
             patch.object(rag, "KG_PATH") as path, \
             patch.object(rag.KGChunkIndex, "from_directory") as load_kg, \
             patch.object(rag.AutoTokenizer, "from_pretrained"), \
             patch.object(rag.AutoModelForCausalLM, "from_pretrained") as load_model:
            path.exists.return_value = True
            first = rag._load("fake", "corpus")
            self.assertIs(first, rag._load("fake", "corpus"))
            load_kg.assert_called_once_with(path, [], mode="graph", config=GraphConfig())
            os.environ["KG_GRAPH_MAX_NEIGHBORS"] = "2"
            self.assertIsNot(first, rag._load("fake", "corpus"))
            self.assertEqual(load_kg.call_count, 2)
            load_model.assert_called_once()

    def test_off_mode_never_loads_kg(self):
        with patch.dict(os.environ, {"KG_MODE": "off"}), patch.dict(rag._cache, {}, clear=True), \
             patch.object(rag, "_build_index", return_value=([], np.empty((0, 0)), Mock(), None, [])), \
             patch.object(rag.KGChunkIndex, "from_directory") as load_kg, \
             patch.object(rag.AutoTokenizer, "from_pretrained"), \
             patch.object(rag.AutoModelForCausalLM, "from_pretrained"):
            loaded = rag._load("fake-model", "fake-corpus")
            self.assertIsNone(loaded[-2])
            load_kg.assert_not_called()

    def test_corrupt_kg_fails_before_loading_llm(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"KG_MODE": "mentions"}), patch.dict(rag._cache, {}, clear=True), \
             patch.object(rag, "KG_PATH", Path(directory)), \
             patch.object(rag, "_build_index", return_value=([], np.empty((0, 0)), Mock(), None, [])), \
             patch.object(rag.AutoModelForCausalLM, "from_pretrained") as load_llm:
            with self.assertRaises(FileNotFoundError):
                rag._load("fake-model", "fake-corpus")
            load_llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
