"""Technique switches, cache identity and import of the packaged entry point."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import main, indexing, generation
from src.runtime import resolve_device
from src.settings import PipelineConfig, load_config

ROOT = Path(__file__).resolve().parents[1]


class PipelineSettingsTests(unittest.TestCase):
    def test_settings_validate_switches_and_weights(self):
        for changes in ({"variant": "typo"}, {"rrf_k": -1}, {"dense_weight": float("nan")},
                        {"formula_enrichment": "false"}, {"bm25_k1": 0}, {"threads": 0},
                        {"embedding_device": "gpu"}, {"variant": "dense", "dense_weight": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                PipelineConfig(**changes)
        config = PipelineConfig(variant="bm25", embedding_device="cuda")
        self.assertFalse(config.uses("dense"))
        self.assertTrue(config.uses("bm25"))
        self.assertEqual(PipelineConfig(variant="mentions", kg_weight=0).weights["kg_mentions"], 0)

    def test_json_paths_and_legacy_kg_override(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "pipeline.json"
            path.write_text(json.dumps({"embed_model": "encoder", "variant": "dense"}))
            config = load_config(path)
            self.assertEqual(config.embed_model, Path(directory) / "encoder")
            os.environ["KG_MODE"] = "graph"
            self.assertEqual(load_config(path).variant, "dense_graph")
            path.write_text('{"unused_typo": true}')
            with self.assertRaises(ValueError):
                load_config(path)

    def test_cli_adapter_preserves_kg_only_selection(self):
        args = SimpleNamespace(variants=["graph"], dense_weight=0, bm25_weight=0, kg_weight=1)
        config = PipelineConfig.from_namespace(args)
        self.assertTrue(config.uses("kg_graph"))
        self.assertFalse(config.uses("dense"))

    def test_explicit_cuda_fails_and_auto_falls_back(self):
        with patch("torch.cuda.is_available", return_value=False):
            self.assertEqual(resolve_device("auto"), "cpu")
            with self.assertRaisesRegex(RuntimeError, "CUDA was requested"):
                resolve_device("cuda")
        with patch("torch.cuda.is_available", return_value=True):
            self.assertEqual(resolve_device("auto"), "cuda")
            self.assertEqual(resolve_device("cpu"), "cpu")

    def test_bm25_only_does_not_construct_encoder(self):
        converter = Mock()
        converter.convert.return_value = SimpleNamespace(document=SimpleNamespace(export_to_markdown=lambda: "Lithium target."))
        with tempfile.TemporaryDirectory() as directory, patch("src.documents.create_converter", return_value=converter), \
             patch("sentence_transformers.SentenceTransformer") as encoder:
            Path(directory, "paper.pdf").touch()
            index = indexing.build_index(directory, PipelineConfig(variant="bm25", embedding_device="cuda"))
            self.assertIsNone(index.embedder)
            self.assertIsNotNone(index.bm25)
            encoder.assert_not_called()

    def test_dense_only_does_not_construct_bm25(self):
        converter, encoder = Mock(), Mock()
        converter.convert.return_value = SimpleNamespace(document=SimpleNamespace(export_to_markdown=lambda: "Lithium target."))
        encoder.encode.return_value = [[1.0, 0.0]]
        with tempfile.TemporaryDirectory() as directory, patch("src.documents.create_converter", return_value=converter), \
             patch("sentence_transformers.SentenceTransformer", return_value=encoder), patch("src.indexing.build_bm25") as lexical:
            Path(directory, "paper.pdf").touch()
            index = indexing.build_index(directory, PipelineConfig(variant="dense", embedding_device="cpu"))
            lexical.assert_not_called()
            self.assertIsNone(index.lexical)

    def test_retrieval_cache_includes_settings_corpus_and_graph(self):
        config = PipelineConfig(variant="graph")
        with patch.dict(main._indices, {}, clear=True), patch.object(main, "build_index", side_effect=lambda *a: object()) as build, \
             patch.dict(os.environ, {}, clear=True):
            first = main.get_index("corpus", config)
            self.assertIs(main.get_index("corpus", config), first)
            self.assertIsNot(main.get_index("corpus", replace(config, bm25_stemming=False)), first)
            self.assertIsNot(main.get_index("other", config), first)
            os.environ["KG_GRAPH_MAX_NEIGHBORS"] = "2"
            self.assertIsNot(main.get_index("corpus", config), first)
            self.assertEqual(build.call_count, 4)

    def test_missing_requested_kg_fails_before_answer_model_load(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(main._indices, {}, clear=True), \
             patch.object(main, "load_config", return_value=PipelineConfig(variant="mentions", kg=Path(directory))), \
             patch.object(main, "load_model") as model:
            with self.assertRaises(FileNotFoundError):
                main.answer("question", directory, "unused")
            model.assert_not_called()

    def test_answer_model_cache_is_independent_of_retrieval(self):
        with patch.dict(generation._models, {}, clear=True), patch.object(generation, "resolve_device", return_value="cpu"), \
             patch("transformers.AutoTokenizer.from_pretrained") as tokenizer, \
             patch("transformers.AutoModelForCausalLM.from_pretrained") as model:
            self.assertIs(generation.load_model("local-model", "cpu"), generation.load_model("local-model", "cpu"))
            model.assert_called_once()
            tokenizer.assert_called_once_with("local-model", local_files_only=True)

    def test_official_answer_coordinates_retrieval_before_model_loading(self):
        events = []
        index = indexing.CorpusIndex(chunks=["evidence"], sources=[{"chunk_id": "paper.pdf#0"}])
        tokenizer = Mock()
        tokenizer.encode.side_effect = str.split
        config = PipelineConfig()
        with patch.object(main, "load_config", return_value=config), \
             patch.object(main, "get_index", side_effect=lambda *a: events.append("index") or index), \
             patch.object(main, "retrieve", return_value=[0]), \
             patch.object(main, "load_model", side_effect=lambda *a: events.append("model") or (tokenizer, Mock())), \
             patch.object(main, "generate_answer", return_value="answer") as generate:
            self.assertEqual(main.answer("question", "corpus", "model"), "answer")
            self.assertEqual(events, ["index", "model"])
            self.assertIn("Source: paper.pdf#0", generate.call_args.args[1])

    def test_build_whitelist_imports_without_assets_or_answer_libraries(self):
        script = (ROOT / "src/build.sh").read_text()
        files = shlex.split(re.search(r"files=\((.*?)\)", script, re.S).group(1))
        with tempfile.TemporaryDirectory() as directory:
            for name in files:
                if name.endswith((".py", ".json")):
                    shutil.copy2(ROOT / "src" / name, Path(directory) / name)
            subprocess.run([sys.executable, "-c", "import main, sys; assert callable(main.answer); assert 'transformers' not in sys.modules; assert 'docling' not in sys.modules; c=main.load_config(); assert c.variant=='hybrid'"],
                           cwd=directory, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
