#!/usr/bin/env python3
"""Export self-contained question/top-k JSON files from saved retrieval runs."""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.prompts import SYSTEM_PROMPT, USER_MESSAGE_TEMPLATE


def export_llm_inputs(output, questions, chunks, results, top_k=10, include_answers=False):
    """One file per case/variant, keeping question and rank order and full text."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    by_id = {str(question["id"]): question for question in questions}
    groups = {}
    for result in results:
        question_id = str(result["question_id"])
        if question_id not in by_id:
            raise ValueError(f"Unknown question: {question_id}")
        identity = (result.get("case_id"), result["variant"])
        group = groups.setdefault(identity, {})
        if question_id in group:
            raise ValueError(f"Duplicate question in case/variant: {identity}, {question_id}")
        group[question_id] = result
    files = []
    for (case_id, variant), group in groups.items():
        for name in (case_id, variant):
            if name is not None and (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)):
                raise ValueError(f"Invalid export filename: {name}")
        records = []
        for question in questions:
            result = group.get(str(question["id"]))
            if result is None:
                continue
            chosen = []
            for hit in sorted(result["hits"], key=lambda item: item["rank"])[:top_k]:
                chunk = chunks[hit["index"]]
                chosen.append({"rank": hit["rank"], "chunk_id": chunk["chunk_id"],
                               "document_id": chunk.get("document_id"), "document": chunk.get("document"),
                               "title": chunk.get("title"), "section": chunk.get("section"),
                               "text": chunk["text"], "retrieval_score": hit.get("score")})
            records.append({"id": question["id"], "question": question["question"],
                            "domain": question.get("domain"), "question_type": question.get("question_type"), "chunks": chosen})
            if include_answers:
                records[-1]["expected_answer"] = question.get("answer")
        target = output / case_id / f"{variant}.json" if case_id else output / f"{variant}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "case_id": case_id, "variant": variant, "max_chunks": top_k,
                   "system_prompt": SYSTEM_PROMPT, "user_message_template": USER_MESSAGE_TEMPLATE, "questions": records}
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        files.append({"case_id": case_id, "variant": variant, "path": target.relative_to(output).as_posix(), "questions": len(records)})
    (output / "index.json").write_text(json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Default: <run>/llm_inputs")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--include-reference-answers", action="store_true")
    args = parser.parse_args()
    if args.top_k <= 0:
        parser.error("top-k must be positive")
    def read(name):
        return [json.loads(line) for line in (args.run / name).read_text(encoding="utf-8").splitlines() if line.strip()]
    output = args.output or args.run / "llm_inputs"
    files = export_llm_inputs(output, read("questions.jsonl"), read("chunks.jsonl"), read("retrieval.jsonl"), args.top_k, args.include_reference_answers)
    print(f"Exported {len(files)} JSON files to {output}")


if __name__ == "__main__":
    main()
