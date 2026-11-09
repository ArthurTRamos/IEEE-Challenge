"""Retrieval-role prompts, cache identity and offline asset verification."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.embedding import embedding_inputs, encode_documents, encode_queries
from tools.prepare_embedding_model import digest, verify
from tools.run_retrieval import tree_fingerprint


class EmbeddingTests(unittest.TestCase):
    def test_query_instruction_does_not_leak_into_passages(self):
        encoder = SimpleNamespace(prompts={"query": "Find evidence: "}, default_prompt_name="query", encode=Mock())
        encode_queries(encoder, ["why?"], normalize_embeddings=True)
        encoder.encode.assert_called_with(["why?"], normalize_embeddings=True, prompt="Find evidence: ")
        encode_documents(encoder, ["evidence"], normalize_embeddings=True)
        encoder.encode.assert_called_with(["evidence"], normalize_embeddings=True, prompt="")
        self.assertEqual(embedding_inputs(encoder, ["why?"], "query"), ["Find evidence: why?"])
        self.assertEqual(embedding_inputs(encoder, ["evidence"], "document"), ["evidence"])

    def test_unprompted_baseline_keeps_existing_encode_contract(self):
        encoder = SimpleNamespace(prompts={}, default_prompt_name=None, encode=Mock())
        encode_documents(encoder, ["passage"], batch_size=8)
        encoder.encode.assert_called_once_with(["passage"], batch_size=8)
        encode_queries(encoder, ["query"])
        encoder.encode.assert_called_with(["query"])

    def test_document_prefix_is_included_in_audited_text(self):
        encoder = SimpleNamespace(prompts={"query": "query: ", "document": "passage: "},
                                  default_prompt_name=None, encode=Mock())
        encode_documents(encoder, ["text"])
        encoder.encode.assert_called_once_with(["text"], prompt="passage: ")
        self.assertEqual(embedding_inputs(encoder, ["text"], "document"), ["passage: text"])

    def test_model_under_cache_root_still_has_a_fingerprint(self):
        with tempfile.TemporaryDirectory() as root:
            model = Path(root) / ".cache" / "model"
            model.mkdir(parents=True)
            (model / "model.safetensors").write_bytes(b"weights")
            (model / "config.json").write_text('{"prompts": {}}')
            before = tree_fingerprint(model)
            (model / ".cache").mkdir()
            (model / ".cache/hub.json").write_text("ignored")
            self.assertEqual(before, tree_fingerprint(model))
            (model / "config.json").write_text('{"prompts": {"query": "instruction"}}')
            self.assertNotEqual(before, tree_fingerprint(model))

    def test_verification_detects_corrupt_weights_and_wrong_model(self):
        with tempfile.TemporaryDirectory() as root:
            model = Path(root)
            (model / "modules.json").write_text("[]")
            (model / "model.safetensors").write_bytes(b"weights")
            manifest = {"model_id": "model", "revision": "immutable-revision",
                        "files": {p.name: {"sha256": digest(p)} for p in model.iterdir()}}
            (model / "embedding-manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(verify(model, "model")["revision"], "immutable-revision")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                verify(model, "other-model")
            (model / "model.safetensors").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "Invalid embedding asset"):
                verify(model, "model")


if __name__ == "__main__":
    unittest.main()
