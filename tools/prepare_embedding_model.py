#!/usr/bin/env python3
"""Save a pinned SentenceTransformer with retrieval prompts for offline use."""

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

BGE_QUERY = "Represent this sentence for searching relevant passages: "
PRESETS = {
    "BAAI/bge-base-en-v1.5": (512, BGE_QUERY, ""),
    "BAAI/bge-small-en-v1.5": (512, BGE_QUERY, ""),
    "sentence-transformers/all-MiniLM-L6-v2": (256, "", ""),
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify(output, model_id=None, revision=None):
    output = Path(output)
    manifest = json.loads((output / "embedding-manifest.json").read_text())
    if model_id and manifest["model_id"] != model_id:
        raise ValueError(f"Embedding model mismatch: {manifest['model_id']} != {model_id}")
    if revision and manifest["revision"] != revision:
        raise ValueError("Embedding revision mismatch")
    for name, record in manifest["files"].items():
        path = output / name
        if not path.is_file() or digest(path) != record["sha256"]:
            raise ValueError(f"Invalid embedding asset: {name}")
    if not (output / "modules.json").is_file() or not list(output.glob("*.safetensors")):
        raise ValueError("Missing SentenceTransformer modules or weights")
    return manifest


def prepare(model_id, output, revision=None, replace=False):
    from huggingface_hub import HfApi, snapshot_download
    from sentence_transformers import SentenceTransformer

    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()) and not replace:
        raise ValueError(f"Output already exists; use --replace: {output}")
    info = HfApi().model_info(model_id, revision=revision)
    pinned_revision = info.sha
    # Only one native weight format; no ONNX/OpenVINO copies of the embedding.
    snapshot = snapshot_download(model_id, revision=pinned_revision,
                                 allow_patterns=["*.json", "model.safetensors", "vocab.txt",
                                                 "tokenizer.model", "1_Pooling/*", "2_Normalize/*",
                                                 "README.md", "LICENSE*"])
    model = SentenceTransformer(snapshot, device="cpu", local_files_only=True)
    maximum, query, document = PRESETS[model_id]
    model.max_seq_length = maximum
    model.prompts = {name: text for name, text in (("query", query), ("document", document)) if text}
    model.default_prompt_name = None
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
        stage = Path(temporary) / "model"
        model.save_pretrained(str(stage), safe_serialization=True)
        for source in Path(snapshot).iterdir():
            if source.is_file() and (source.name == "README.md" or source.name.startswith("LICENSE")):
                shutil.copy2(source, stage / source.name)
        paths = sorted(p for p in stage.rglob("*") if p.is_file())
        manifest = {"schema_version": 1, "model_id": model_id, "revision": pinned_revision,
                    "source": f"https://huggingface.co/{model_id}/tree/{pinned_revision}",
                    "max_seq_length": maximum, "dimension": model.get_embedding_dimension(),
                    "parameters": sum(p.numel() for p in model.parameters()),
                    "query_prefix": query, "document_prefix": document,
                    "files": {p.relative_to(stage).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)} for p in paths}}
        (stage / "embedding-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        verify(stage, model_id, pinned_revision)
        previous = Path(temporary) / "previous"
        if output.exists():
            output.rename(previous)
        try:
            stage.rename(output)
        except BaseException:
            if previous.exists():
                previous.rename(output)
            raise
    print(f"Prepared {model_id}@{pinned_revision}: {manifest['parameters']:,} parameters, "
          f"{maximum} tokens, {manifest['dimension']} dimensions -> {output}", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", choices=PRESETS, default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", help="Immutable Hub revision; resolved and recorded when omitted")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        try:
            manifest = verify(args.output, args.model_id, args.revision)
        except (OSError, ValueError, KeyError) as exc:
            raise SystemExit(f"Embedding verification failed: {exc}") from exc
        print(f"Verified {manifest['model_id']}@{manifest['revision']}")
    else:
        prepare(args.model_id, args.output, args.revision, args.replace)


if __name__ == "__main__":
    main()
