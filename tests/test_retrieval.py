"""Indexing, fusion, context budgets and official entry point; models are mocked."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, call

import numpy as np
import torch
from rank_bm25 import BM25Okapi

from src import indexing, retrieval, generation
from src.context import build_context
from src.settings import PipelineConfig
from src.evidence import section_chunks
from src.lexical import LexicalPreprocessor
from src.kg_retrieval import EntityMatcher, KGChunkIndex, LINK_PREDICATE


class LexicalIndexTests(unittest.TestCase):
    def test_tokenization_preserves_unicode_numbers_and_normalizes_case(self):
        self.assertEqual(
            LexicalPreprocessor()("IFMIF-DONES: Nêutrons, H100; 3.12!"),
            ["ifmif", "dones", "nêutrons", "h100", "3", "12"],
        )
        self.assertEqual(LexicalPreprocessor()(" \n---!?"), [])

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
            with patch("src.documents.create_converter", return_value=converter), patch(
                "sentence_transformers.SentenceTransformer", return_value=embedder
            ):
                index = indexing.build_index(directory, PipelineConfig())
                result = (index.chunks, index.embeddings, index.embedder, index.bm25, index.sources)
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
        scores = bm25.get_scores(LexicalPreprocessor()("LITHIUM target!"))
        self.assertGreater(scores[0], 0)
        self.assertEqual(int(np.argmax(scores)), 0)
        self.assertIn("lithium", chunks[0])
        np.testing.assert_array_equal(scores[1:], [0, 0])
        self.assertEqual(bm25.doc_freqs[0]["lithium"], 1)
        self.assertNotIn("lithium", bm25.doc_freqs[1])
        self.assertEqual({key: sources[0][key] for key in ("chunk_id", "document", "section")},
                         {"chunk_id": "a.pdf#0", "document": "a.pdf", "section": None})
        self.assertEqual(sources[1]["document"], "b.pdf")
        embedder.encode.assert_called_once_with(
            chunks, normalize_embeddings=True, show_progress_bar=False, batch_size=PipelineConfig().batch_size
        )

    def test_long_documents_index_every_generated_chunk(self):
        paragraphs = [f"Section {i}: " + "lithium " * 70 for i in range(4)]
        text = "\n\n".join(paragraphs)
        (chunks, embeddings, _, bm25, sources), _, _ = self.build_index({"a.pdf": text})
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks, section_chunks(text))
        self.assertEqual(bm25.corpus_size, len(chunks))
        self.assertEqual(len(embeddings), len(chunks))
        self.assertEqual(len(sources), len(chunks))
        self.assertEqual(len({s["chunk_id"] for s in sources}), len(chunks))
        for chunk, frequencies in zip(chunks, bm25.doc_freqs):
            self.assertEqual(frequencies["lithium"], LexicalPreprocessor()(chunk).count("lithium"))

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
        self.assertIsNone(embeddings)
        self.assertIsNone(bm25)
        self.assertEqual(sources, [])
        embedder.encode.assert_not_called()

    def test_gpu_encoder_returns_to_cpu_before_answer_model_loading(self):
        with patch.object(torch.cuda, "is_available", return_value=True), \
             patch.object(torch.cuda, "empty_cache"):
            (_, _, _, _, _), _, embedder = self.build_index({"a.pdf": "Lithium loop."})
        self.assertEqual(embedder.to.call_args_list, [call("cuda"), call("cpu")])

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
        self.candidate_depth = 100
        self.embeddings = np.array([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32)
        self.embedder = Mock()
        self.embedder.encode.return_value = np.array([[1, 0]], dtype=np.float32)

    def index(self, chunks, embeddings, embedder, bm25, kg=None, sources=None):
        return indexing.CorpusIndex(chunks=chunks, sources=sources, embeddings=embeddings,
                                    embedder=embedder, bm25=bm25,
                                    lexical=LexicalPreprocessor(True, True), kg_index=kg)

    def config(self, kg=None, kg_weight=0.5):
        return PipelineConfig(variant="mentions" if kg is not None else "hybrid",
                              candidate_depth=self.candidate_depth, kg_weight=kg_weight)

    def rank(self, question, embeddings, embedder, bm25, kg_index=None, kg_weight=0.5, sources=None):
        index = self.index(["fixture"] * len(embeddings), embeddings, embedder, bm25, kg_index, sources)
        return retrieval.rank_candidates(question, index, self.config(kg_index, kg_weight))[0]

    def context(self, question, chunks, embeddings, embedder, tokenizer, bm25,
                max_tokens=10000, kg_index=None, sources=None):
        index = self.index(chunks, embeddings, embedder, bm25, kg_index, sources)
        order = retrieval.retrieve(question, index, self.config(kg_index))
        return build_context(chunks, order, tokenizer, sources, max_tokens)

    def test_rrf_promotes_agreement_between_rankings(self):
        bm25 = Mock()
        bm25.get_scores.return_value = np.array([0, 2, 10])
        # Dense candidates: [0, 1]; lexical candidates: [2, 1].
        # Chunk 1 has 2/62, while chunks 0 and 2 each have 1/61.
        with patch.object(self, "candidate_depth", 2):
            order = self.rank("LITHIUM!", self.embeddings, self.embedder, bm25)
        self.assertEqual(order, [1, 0, 2])
        self.assertEqual(len(order), len(set(order)))
        bm25.get_scores.assert_called_once_with(["lithium"])

    def test_rrf_uses_ranks_instead_of_raw_bm25_score_scale(self):
        bm25 = Mock()
        orders = []
        for scores in ([0, 2, 10], [0, 2000, 1_000_000]):
            bm25.get_scores.return_value = np.array(scores)
            with patch.object(self, "candidate_depth", 2):
                orders.append(self.rank("target", self.embeddings, self.embedder, bm25))
        self.assertEqual(orders, [[1, 0, 2], [1, 0, 2]])

    def test_real_bm25_adds_a_match_outside_dense_candidates(self):
        chunks = ["Neural networks.", "Fusion materials.", "Lithium target."]
        bm25 = BM25Okapi([LexicalPreprocessor()(chunk) for chunk in chunks])
        with patch.object(self, "candidate_depth", 1):
            order = self.rank("LITHIUM", self.embeddings, self.embedder, bm25)
        self.assertEqual(order, [0, 2])

    def test_unmatched_query_does_not_add_zero_score_candidates(self):
        bm25 = BM25Okapi([["neural"], ["fusion"], ["lithium"]])
        with patch.object(self, "candidate_depth", 1):
            order = self.rank("unknown", self.embeddings, self.embedder, bm25)
        self.assertEqual(order, [0])

    def test_missing_lexical_index_uses_dense_ranking(self):
        self.assertEqual(
            self.rank("target", self.embeddings, self.embedder, None), [0, 1, 2]
        )
        self.embedder.encode.assert_called_once_with(
            ["target"], normalize_embeddings=True, show_progress_bar=False
        )

    def test_empty_index_does_not_encode_query(self):
        bm25 = Mock()
        self.assertEqual(
            self.rank("target", np.empty((0, 0)), self.embedder, bm25), []
        )
        self.embedder.encode.assert_not_called()
        bm25.get_scores.assert_not_called()

    def test_equal_dense_scores_have_deterministic_chunk_order(self):
        embeddings = np.tile([1, 0], (3, 1))
        self.assertEqual(
            self.rank("target", embeddings, self.embedder, None), [0, 1, 2]
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
        with patch.object(self, "candidate_depth", 2):
            context = self.context(
                "target", chunks, self.embeddings, self.embedder, tokenizer, bm25, max_tokens=budget
            )
        self.assertEqual(context, expected)
        self.assertLessEqual(len(tokenizer.encode(context)), budget)
        self.assertIn("[Fragment 1]\nshared evidence", context)
        self.assertIn("[Fragment 2]\ndense evidence", context)
        self.assertNotIn("lexical evidence", context)

    def test_context_keeps_top_ten_anchors_without_inserting_neighbors(self):
        chunks = [f"Evidence chunk {i}" for i in range(14)]
        order = [5, 12, 1, 9, 3, 7, 0, 11, 8, 2, 6, 4, 10, 13]
        sources = [{"chunk_id": f"paper.pdf#{i}", "document": "paper.pdf", "section": "Methods",
                    "section_id": 0, "local_chunk_index": i} for i in range(14)]
        tokenizer = Mock()
        tokenizer.encode.side_effect = str.split
        with patch("src.retrieval.rank_candidates", return_value=(order, {i: 1/(p+1) for p, i in enumerate(order)})):
            context = self.context("question", chunks, None, None, tokenizer, None, sources=sources)
        import re
        self.assertEqual([int(i) for i in re.findall(r"Source: paper.pdf#(\d+)", context)], order[:10])

    def test_kg_adds_candidates_and_uses_configured_rrf_weight(self):
        entity = {"uri": "http://dbpedia.org/resource/Beryllium-7", "label": "Beryllium-7", "aliases": ["Be7"]}
        kg = KGChunkIndex(EntityMatcher([entity]), ["Beryllium-7", "neural networks", "Be7"])
        bm25 = Mock()
        bm25.get_scores.return_value = np.array([0, 10, 0])
        with patch.object(self, "candidate_depth", 2):
            order = self.rank("Be7", self.embeddings, self.embedder, bm25, kg, kg_weight=0.5)
        # c1 = 1/62 + 1/61; c0 = 1/61 + 0.5/61; c2 = 0.5/62.
        self.assertEqual(order, [1, 0, 2])
        self.assertEqual(len(set(order)), 3)
        self.embedder.encode.assert_called_once()

    def test_kg_without_matches_preserves_baseline_order(self):
        kg = KGChunkIndex(EntityMatcher([{
            "uri": "http://dbpedia.org/resource/Lithium", "label": "Lithium", "aliases": []
        }]), ["Lithium", "networks", "fusion"])
        baseline = self.rank("unknown", self.embeddings, self.embedder, None)
        self.assertEqual(self.rank("unknown", self.embeddings, self.embedder, None, kg), baseline)

    def test_graph_only_candidate_enters_rrf_and_context(self):
        prefix = "http://dbpedia.org/resource/"
        nodes = [{"uri": prefix + name, "label": name, "aliases": []} for name in ("Alpha", "Beta")]
        chunks = ["dense evidence", "lexical evidence", "Beta evidence"]
        edges = [{"source": prefix + "Alpha", "target": prefix + "Beta", "predicate": LINK_PREDICATE}]
        graph = KGChunkIndex(EntityMatcher(nodes), chunks, edges=edges, mode="graph")
        mentions = KGChunkIndex(EntityMatcher(nodes), chunks)
        bm25 = Mock()
        bm25.get_scores.return_value = np.array([0, 10, 0])
        with patch.object(self, "candidate_depth", 1):
            baseline = self.rank("Alpha", self.embeddings, self.embedder, bm25, mentions)
            expanded = self.rank("Alpha", self.embeddings, self.embedder, bm25, graph)
            tokenizer = Mock()
            tokenizer.encode.side_effect = str.split
            context = self.context("Alpha", chunks, self.embeddings, self.embedder, tokenizer, bm25, kg_index=graph)
        self.assertEqual(baseline, [0, 1])
        self.assertEqual(expanded, [0, 1, 2])
        self.assertIn("Beta evidence", context)

    def test_zero_kg_weight_disables_channel(self):
        kg = Mock()
        self.assertEqual(self.rank("target", self.embeddings, self.embedder, None, kg, kg_weight=0), [0, 1, 2])
        kg.rank.assert_not_called()

    def test_truncated_context_keeps_source_and_respects_complete_budget(self):
        tokenizer = Mock()
        tokenizer.encode.side_effect = list  # Count characters, including labels and separators.
        sources = [{"chunk_id": "paper.pdf#0", "section": "Methods"}]
        context = self.context(
            "target", ["x" * 1000], self.embeddings[:1], self.embedder, tokenizer, None,
            max_tokens=150, sources=sources,
        )
        self.assertIn("[Source: paper.pdf#0]", context)
        self.assertIn("[Section: Methods]", context)
        self.assertIn("xxx", context)
        self.assertLessEqual(len(tokenizer.encode(context)), 150)
        self.assertEqual(self.context(
            "target", ["evidence"], self.embeddings[:1], self.embedder, tokenizer, None,
            max_tokens=1, sources=sources,
        ), "")

class AnswerPromptTests(unittest.TestCase):
    def test_generation_receives_separate_question_and_cited_evidence(self):
        question = r"Why does $x_{m,n} \in Y$ hold?"
        context = "[Fragment 1] [Source: proof.pdf#3]\nWitnesses belong to Y."
        tokenizer, model = Mock(), Mock()
        batch = Mock()
        batch.to.return_value = {"input_ids": np.array([[1, 2, 3]])}
        tokenizer.apply_chat_template.return_value = batch
        tokenizer.decode.return_value = "Answer [Fragment 1]."
        model.generate.return_value = np.array([[1, 2, 3, 4]])
        self.assertEqual(generation.generate_answer(question, context, tokenizer, model), "Answer [Fragment 1].")
        messages = tokenizer.apply_chat_template.call_args.args[0]
        self.assertEqual(messages[0], {"role": "system", "content": generation.SYSTEM_PROMPT})
        self.assertIn("QUESTION:\n" + question, messages[1]["content"])
        self.assertIn("REFERENCE EXCERPTS:\n" + context, messages[1]["content"])
        self.assertLess(messages[1]["content"].index(question), messages[1]["content"].index(context))
        self.assertFalse(model.generate.call_args.kwargs["do_sample"])
