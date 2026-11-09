#!/usr/bin/env python3
"""Prepare stable Markdown/native-page sources for annotation, without embeddings."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/local_eval")
    args = parser.parse_args()
    output = args.output.resolve()
    (output / "markdown").mkdir(parents=True, exist_ok=True)
    (output / "page-text").mkdir(parents=True, exist_ok=True)
    # The canonical catalog survives cleanup of dated experiment judgments.
    catalog_path = ROOT / "data/local_eval/documents.jsonl"
    legacy = {"corpus_documents": [json.loads(line) for line in catalog_path.read_text().splitlines()
                                   if line.strip()]}
    metadata = {}
    for path in (ROOT / "data/download_pdfs").rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if "id" in row:
                    metadata[str(row["id"])] = row
    catalog = []
    for doc in legacy["corpus_documents"]:
        if doc.get("origin") == "public_qa_expansion":
            continue
        pdf = ROOT / "data/download_pdfs" / doc["relative_path"]
        if digest(pdf) != doc["pdf_sha256"]:
            raise ValueError(f"Legacy PDF changed; do not reuse its evidence: {pdf}")
        source = ROOT / doc["markdown"]
        if digest(source) != doc["markdown_sha256"]:
            raise ValueError(f"Legacy Markdown changed: {source}")
        target = output / "markdown" / f"{doc['document_id']}.md"
        if not target.exists():
            shutil.copy2(source, target)
        elif digest(target) != doc["markdown_sha256"]:
            raise ValueError(f"Canonical Markdown differs: {target}")
        descriptive = metadata.get(doc["document_id"], {})
        catalog.append({**doc, "pdf_path": str(pdf.relative_to(ROOT)),
                        "markdown": str(target.relative_to(ROOT)),
                        "article_url": descriptive.get("article_url", descriptive.get("landing_url")),
                        "pdf_url": descriptive.get("pdf_url"),
                        "domain": "DONES" if doc["document_id"].startswith("DONES-") else "AI Papers",
                        "origin": "existing_local_corpus"})
    downloads = json.loads((ROOT / "data/download_pdfs/public_qa_expansion/download-manifest.json").read_text())
    if any(doc["status"] != "success" for doc in downloads):
        raise ValueError("Some public documents were not downloaded; inspect download-manifest.json")
    converter = None
    for doc in downloads:
        if doc["status"] != "success":
            continue
        pdf = ROOT / doc["relative_path"]
        target = output / "markdown" / f"{doc['id']}.md"
        if not target.exists():
            if converter is None:
                from src.documents import create_converter
                converter = create_converter(device="cpu", num_threads=4, formula_enrichment=False)
            result = converter.convert(str(pdf))
            status = getattr(getattr(result, "status", None), "value", "success")
            if status != "success":
                raise ValueError(f"Document conversion incomplete: {doc['id']}: {status}")
            text = result.document.export_to_markdown()
            if not text.strip():
                raise ValueError(f"No text from {doc['id']}")
            target.write_text(text)
            del result
        catalog.append({"document_id": doc["id"], "title": doc["title"], "domain": doc["domain"],
                        "relative_path": str(pdf.relative_to(ROOT / "data/download_pdfs")),
                        "pdf_path": str(pdf.relative_to(ROOT)), "pdf_sha256": digest(pdf),
                        "markdown": str(target.relative_to(ROOT)), "markdown_sha256": digest(target),
                        "article_url": doc["article_url"], "pdf_url": doc["pdf_url"],
                        "license": doc["license"], "origin": "public_qa_expansion"})
        print(f"[new source] {doc['id']}: Markdown ready", flush=True)
    for doc in catalog:
        pdf = ROOT / doc["pdf_path"]
        target = output / "page-text" / f"{doc['document_id']}.jsonl"
        with pymupdf.open(pdf) as pages:
            doc["pages"] = len(pages)
            if not target.exists():
                target.write_text("".join(json.dumps({"page": i + 1, "text": p.get_text(sort=True)}, ensure_ascii=False) + "\n"
                                           for i, p in enumerate(pages)))
        doc["native_pages"] = str(target.relative_to(ROOT))
    catalog.sort(key=lambda d: d["document_id"])
    (output / "documents.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in catalog))
    print(f"Prepared {len(catalog)} documents, {sum(d['pages'] for d in catalog)} pages -> {output}", flush=True)


if __name__ == "__main__":
    main()
