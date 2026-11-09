#!/usr/bin/env python3
"""Download explicitly listed public evaluation PDFs and record provenance."""

import argparse
import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import pymupdf

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def collect(document, output):
    record = dict(document)
    target = output / f"{document['id']}.pdf"
    try:
        if not target.exists():
            request = Request(document["pdf_url"], headers={"User-Agent": "IEEE-Challenge-local-evaluation/1.0"})
            with tempfile.NamedTemporaryFile(dir=output, suffix=".download", delete=False) as stream:
                temporary = Path(stream.name)
            try:
                with urlopen(request, timeout=60) as response, temporary.open("wb") as stream:
                    size = 0
                    for block in iter(lambda: response.read(1024 * 1024), b""):
                        size += len(block)
                        if size > 50_000_000:
                            raise ValueError("PDF exceeds the 50 MB collection limit")
                        stream.write(block)
                    record["resolved_url"] = response.url
                with pymupdf.open(temporary) as pdf:
                    if not pdf.is_pdf or not len(pdf):
                        raise ValueError("Response is not a readable PDF")
                temporary.rename(target)
            finally:
                temporary.unlink(missing_ok=True)
        with pymupdf.open(target) as pdf:
            record["pages"] = len(pdf)
        record.update({"status": "success", "relative_path": str(target.relative_to(ROOT)),
                       "sha256": digest(target), "bytes": target.stat().st_size,
                       "accessed_at": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "tools/public_qa_sources.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/download_pdfs/public_qa_expansion")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    documents = json.loads(args.manifest.read_text())["documents"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda doc: collect(doc, output), documents))
    # Only descriptive metadata enters corpus discovery; hints and labels stay out.
    successful = [{key: row[key] for key in ("id", "title", "domain", "article_url", "pdf_url")}
                  for row in records if row["status"] == "success"]
    (output / "documents.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in successful))
    (output / "download-manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    for row in records:
        print(row["id"], row["status"], row.get("pages", row.get("error")), flush=True)
    if any(row["status"] != "success" for row in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
