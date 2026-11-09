#!/usr/bin/env python3
"""Materialize curated public-question annotations; never infer grades from search terms."""

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.evaluate_retrieval import load_judgments

BASE = ROOT / "data/local_eval"
OFFICIAL = ROOT / "starter-kit/IEEE-CIS-DSQA-Starter-Kit/sample/sample_qa.json"
LABELS = {0: "não relevante", 1: "possivelmente relevante", 2: "relevante"}
STATUSES = {"supported_text", "partial_text", "requires_figure", "scope_warning", "missing_source"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_text(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def build():
    official = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    annotations = json.loads((BASE / "annotation-spec.json").read_text(encoding="utf-8"))
    if annotations["official_questions_sha256"] != sha(OFFICIAL.read_bytes()):
        raise ValueError("Official questions changed; review the annotations first")
    documents = [json.loads(line) for line in (BASE / "documents.jsonl").read_text(encoding="utf-8").splitlines()]
    catalog = {row["document_id"]: row for row in documents}
    if len(catalog) != len(documents):
        raise ValueError("Duplicate document ID")
    fingerprints = annotations["source_fingerprints"]
    if set(fingerprints) != set(catalog):
        raise ValueError("Corpus changed; review the annotations before adding/removing documents")
    texts = {}
    for doc_id, doc in catalog.items():
        if any(doc[key] != fingerprints[doc_id][key] for key in ("pdf_sha256", "markdown_sha256")):
            raise ValueError(f"Annotated source changed; review evidence first: {doc_id}")
        for path_key, hash_key in (("pdf_path", "pdf_sha256"), ("markdown", "markdown_sha256")):
            if sha((ROOT / doc[path_key]).read_bytes()) != doc[hash_key]:
                raise ValueError(f"Source changed: {doc_id}/{path_key}")
        texts[doc_id] = (ROOT / doc["markdown"]).read_text(encoding="utf-8")
    specs = {str(q["id"]): q for q in annotations["questions"]}
    ids = [str(q["id"]) for q in official]
    if len(specs) != 25 or len(ids) != len(set(ids)) or set(ids) != set(specs):
        raise ValueError("Annotations must cover exactly the 25 official questions")
    questions, passages, coverage = [], [], []
    for question in official:
        qid = str(question["id"])
        spec = specs[qid]
        if spec["coverage_status"] not in STATUSES:
            raise ValueError(f"Unknown coverage status: {qid}")
        positives = {row["document_id"]: row for row in spec["judgments"]}
        if len(positives) != len(spec["judgments"]) or not set(positives) <= set(catalog):
            raise ValueError(f"Duplicate or unknown positive document: {qid}")
        judgments = []
        for doc_id, doc in catalog.items():
            row = positives.get(doc_id)
            if row is None:
                judgments.append({"document_id": doc_id, "grade": 0, "label": LABELS[0],
                                  "review_status": "triage_no_support_identified",
                                  "rationale": "Nenhuma evidência útil identificada na triagem para esta pergunta; nota estimada, sujeita a revisão.",
                                  "evidence": []})
                continue
            if type(row["grade"]) is not int or row["grade"] not in (1, 2) or not row["passages"]:
                raise ValueError(f"Positive judgment needs a grade and evidence: {qid}/{doc_id}")
            evidence = []
            text = texts[doc_id]
            for index, selector in enumerate(row["passages"], 1):
                if "anchor" in selector:
                    anchor = selector["anchor"]
                    count = text.count(anchor)
                    if not anchor or count != 1:
                        raise ValueError(f"Evidence anchor must be unique: {qid}/{doc_id}: {anchor!r} ({count})")
                    position = text.index(anchor)
                    start = max(0, position - selector.get("before", 80))
                    end = min(len(text), position + len(anchor) + selector.get("after", 400))
                else:
                    start, end = selector["start_char"], selector["end_char"]
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                    raise ValueError(f"Invalid evidence offsets: {qid}/{doc_id}")
                pages = selector.get("pdf_pages", [])
                if any(type(p) is not int or not 1 <= p <= doc["pages"] for p in pages):
                    raise ValueError(f"Invalid PDF page: {qid}/{doc_id}")
                passage = {"evidence_id": f"Q{int(qid):02d}-{doc_id}-E{index:02d}",
                           "question_id": qid, "document_id": doc_id, "grade": row["grade"],
                           "markdown": doc["markdown"], "markdown_sha256": doc["markdown_sha256"],
                           "start_char": start, "end_char": end, "excerpt": text[start:end],
                           "excerpt_sha256": sha(text[start:end].encode("utf-8")),
                           "pdf_path": doc["pdf_path"], "pdf_sha256": doc["pdf_sha256"],
                           "pdf_pages": pages, "modality": selector.get("modality", "text"),
                           "supports": selector.get("supports", []),
                           "note": selector.get("note", row["rationale"])}
                if passage["modality"] == "figure" and not pages:
                    raise ValueError("Figure evidence must specify a PDF page")
                evidence.append(passage)
                passages.append(passage)
            judgments.append({"document_id": doc_id, "grade": row["grade"], "label": LABELS[row["grade"]],
                              "review_status": "positive_evidence_review", "rationale": row["rationale"],
                              "evidence": evidence})
        questions.append({"id": qid, "question": question["question"], "expected_answer": question["answer"],
                          "coverage_status": spec["coverage_status"], "assessment_notes": spec["notes"],
                          "required_evidence": spec["required_evidence"], "judgments": judgments})
        coverage.append({"id": qid, "domain": question["domain"], "question": question["question"],
                         "status": spec["coverage_status"], "grade_2_documents": [j["document_id"] for j in judgments if j["grade"] == 2],
                         "grade_1_documents": [j["document_id"] for j in judgments if j["grade"] == 1],
                         "evidence_count": sum(len(j["evidence"]) for j in judgments), "notes": spec["notes"]})
    payload = {"schema_version": 1, "unit": "document", "status": "assistant_estimate",
               "date": "2026-11-08", "coverage": "all_local_documents", "assessor": "AI assistant; not independently human-validated",
               "method": "Curated positive judgments supported by source passages; other pairs receive provisional zero after triage. No ranking or lexical score determines the labels.",
               "reference_answers_used_for_assessment": True,
               "reference_questions": str(OFFICIAL.relative_to(ROOT)),
               "reference_questions_sha256": sha(OFFICIAL.read_bytes()),
               "annotation_spec": "data/local_eval/annotation-spec.json",
               "labels": {str(k): v for k, v in LABELS.items()},
               "criteria": {"0": "No useful support identified in triage; provisional negative.",
                            "1": "Related context or conflicting design/version; insufficient to establish the requested fact.",
                            "2": "Direct evidence for at least one material part of the question; does not imply the whole answer is covered."},
               "limitations": ["Assistant estimates, with provisional negatives; human audit remains necessary.",
                               "Document relevance is distinct from useful-chunk retrieval and final QA accuracy.",
                               "Some questions have missing primary sources, visual evidence, or scope/version differences.",
                               "This is public development data, not an independent hidden test set."],
               "corpus_documents": documents, "questions": questions}
    load_judgments(payload)
    cohort_payload = {"schema_version": 1, "judgment_status": "assistant_estimate",
                      "question_count": len(questions), "document_count": len(documents),
                      "document_question_pairs": len(questions) * len(documents),
                      "grade_counts": dict(Counter(str(j["grade"]) for q in questions for j in q["judgments"])),
                      "evidence_count": len(passages), "status_counts": dict(Counter(q["status"] for q in coverage)),
                      "cohorts": {"all_public": ids,
                                  "has_direct_evidence": [q["id"] for q in coverage if q["grade_2_documents"]],
                                  "supported_text": [q["id"] for q in coverage if q["status"] == "supported_text"],
                                  "missing_source": [q["id"] for q in coverage if q["status"] == "missing_source"]},
                      "questions": coverage}
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(["question_id", "domain", "coverage_status", "grade_2_documents", "grade_1_documents", "evidence_count", "notes"])
    for q in coverage:
        writer.writerow([q["id"], q["domain"], q["status"], ";".join(q["grade_2_documents"]), ";".join(q["grade_1_documents"]), q["evidence_count"], q["notes"]])
    return {
        ROOT / "experiments/judgments/public-25-2026-11-08.json": json_text(payload),
        BASE / "questions.json": json_text(official),
        BASE / "evidence.jsonl": "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in passages),
        BASE / "coverage.json": json_text(cohort_payload),
        BASE / "coverage.csv": csv_buffer.getvalue(),
        BASE / "qrels.tsv": "".join(f"{q['id']}\t0\t{j['document_id']}\t{j['grade']}\n" for q in questions for j in q["judgments"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate sources and compare generated files without rewriting")
    args = parser.parse_args()
    outputs = build()
    for path, text in outputs.items():
        if args.check:
            if not path.exists() or path.read_bytes() != text.encode("utf-8"):
                raise ValueError(f"Stale generated annotations: {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="")
    print(f"{'Validated' if args.check else 'Generated'} {len(outputs)} artifacts for 25 questions")


if __name__ == "__main__":
    main()
