#!/usr/bin/env python3
"""Evaluate notebook input/output JSON against estimated document judgments."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_judgments(payload):
    if payload.get("unit") != "document":
        raise ValueError("Judgments must declare unit=document")
    documents = payload["corpus_documents"]
    universe = {row["document_id"] for row in documents}
    if len(universe) != len(documents) or not universe:
        raise ValueError("Corpus document IDs must be nonempty and unique")
    qrels = {}
    for question in payload["questions"]:
        qid = str(question["id"])
        if qid in qrels:
            raise ValueError(f"Duplicate judgment question: {qid}")
        grades = {}
        for row in question["judgments"]:
            doc, grade = row["document_id"], row["grade"]
            if doc in grades or doc not in universe:
                raise ValueError(f"Duplicate or unknown judgment document: {qid}/{doc}")
            if type(grade) is not int or grade not in (0, 1, 2):
                raise ValueError(f"Grade must be 0, 1 or 2: {qid}/{doc}")
            grades[doc] = grade
        if payload.get("coverage") == "all_local_documents" and set(grades) != universe:
            raise ValueError(f"Incomplete corpus judgments for question {qid}")
        qrels[qid] = grades
    if not qrels:
        raise ValueError("No relevance judgments supplied")
    return qrels


def document_from_chunk_id(chunk_id):
    """Existing notebook outputs retain IDs of the form path/paper.pdf#N."""
    if not isinstance(chunk_id, str) or "#" not in chunk_id:
        raise ValueError(f"Cannot resolve document from chunk ID: {chunk_id!r}")
    document, local_id = chunk_id.rsplit("#", 1)
    if not local_id.isdigit() or not document:
        raise ValueError(f"Invalid chunk ID: {chunk_id!r}")
    return Path(document.replace("\\", "/")).stem


def ranked_chunks(question):
    if "chunks" in question:
        chunks = question["chunks"]
        ranks = [chunk["rank"] for chunk in chunks]
        if any(type(rank) is not int or rank <= 0 for rank in ranks) or len(set(ranks)) != len(ranks):
            raise ValueError(f"Chunk ranks must be positive and unique: {question['id']}")
        chunks = sorted(chunks, key=lambda chunk: chunk["rank"])
    elif "chunk_ids" in question:
        # The notebook saves only chunks actually included in the LLM context.
        chunks = [{"chunk_id": identity} for identity in question["chunk_ids"]]
    else:
        raise ValueError(f"Question {question['id']} needs chunks or chunk_ids")
    seen = set()
    for position, chunk in enumerate(chunks, 1):
        identity = chunk["chunk_id"]
        if identity in seen:
            raise ValueError(f"Repeated chunk ID in question {question['id']}: {identity}")
        seen.add(identity)
        yield {"chunk_id": identity, "document_id": chunk.get("document_id") or document_from_chunk_id(identity),
               "chunk_rank": chunk.get("rank", position)}


def dcg(grades):
    return sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, 1))


def scores(ranking, judgments, k):
    chosen = ranking[:k]
    grades = [judgments.get(doc, 0) for doc in chosen]
    ideal = dcg(sorted(judgments.values(), reverse=True)[:k])
    result = {"ndcg": dcg(grades) / ideal if ideal else None,
              "retrieved_documents": len(chosen)}
    for threshold in (1, 2):
        total = sum(grade >= threshold for grade in judgments.values())
        hits = sum(grade >= threshold for grade in grades)
        first = next((rank for rank, grade in enumerate(grades, 1) if grade >= threshold), None)
        result.update({f"relevant_total_ge{threshold}": total,
                       f"relevant_retrieved_ge{threshold}": hits,
                       f"recall_ge{threshold}": hits / total if total else None,
                       f"precision_ge{threshold}": hits / k,
                       f"mrr_ge{threshold}": 1 / first if first else (0.0 if total else None)})
    return result


def evaluate(payload, judgment_payload, cutoffs=(1, 3, 5, 10), unjudged="error"):
    if unjudged not in ("error", "zero"):
        raise ValueError("unjudged must be error or zero")
    if not cutoffs or any(type(k) is not int or k <= 0 for k in cutoffs):
        raise ValueError("Cutoffs must be positive integers")
    qrels = load_judgments(judgment_payload)
    if "questions" in payload:
        records, input_type = payload["questions"], "notebook_input"
    elif "answers" in payload:
        records, input_type = payload["answers"], "notebook_output_selected_context"
    else:
        raise ValueError("Input needs questions (notebook input) or answers (notebook output)")
    results, seen = [], set()
    for question in records:
        qid = str(question["id"])
        if qid in seen or qid not in qrels:
            raise ValueError(f"Duplicate question or missing question judgments: {qid}")
        seen.add(qid)
        chunks = list(ranked_chunks(question))
        documents = list(dict.fromkeys(chunk["document_id"] for chunk in chunks))
        missing = [doc for doc in documents if doc not in qrels[qid]]
        if missing and unjudged == "error":
            raise ValueError(f"Unjudged documents for question {qid}: {missing}")
        result = {"id": qid, "document_ranking": documents, "chunk_count": len(chunks),
                  "unjudged_documents": missing,
                  "at_document_k": {str(k): scores(documents, qrels[qid], k) for k in cutoffs},
                  "at_chunk_k_document_coverage": {}}
        for k in cutoffs:
            # Coverage inside the first k chunks: duplicates consume context slots.
            distinct = list(dict.fromkeys(chunk["document_id"] for chunk in chunks[:k]))
            metrics = scores(distinct, qrels[qid], len(distinct) or 1)
            result["at_chunk_k_document_coverage"][str(k)] = {
                "unique_documents": len(distinct),
                **{name: metrics[name] for name in ("recall_ge1", "recall_ge2")}}
        results.append(result)
    if not results:
        raise ValueError("No questions to evaluate")
    def mean(rows, key):
        values = [row[key] for row in rows if row[key] is not None]
        return {"value": sum(values) / len(values) if values else None, "questions": len(values)}
    macro = {}
    for k in cutoffs:
        rows = [row["at_document_k"][str(k)] for row in results]
        macro[str(k)] = {key: mean(rows, key) for key in
                         ("ndcg", "recall_ge1", "recall_ge2", "precision_ge1", "precision_ge2", "mrr_ge1", "mrr_ge2")}
    return {"schema_version": 1, "unit": "document", "input_type": input_type,
            "case_id": payload.get("case_id"), "variant": payload.get("variant"),
            "judgment_status": judgment_payload.get("status", "unspecified"),
            "definitions": {
                "ranking": "Unique documents in first-occurrence order among ranked chunks; k counts documents.",
                "ndcg": "Gain=2**grade-1; discount=log2(rank+1); ideal uses every judged document for the question.",
                "recall_ge1": "Grades 1 and 2 count as relevant; denominator is all such judged documents.",
                "recall_ge2": "Only grade 2 counts as relevant; denominator is all grade-2 judged documents.",
                "precision": "Relevant documents in first k divided by k, even when fewer than k were returned.",
                "macro": "Mean over input questions with a defined denominator; excluded questions have null scores.",
                "chunk_coverage": "Document recall inside the first k chunks, with duplicate documents counted once.",
                "limitations": "Estimated document relevance does not measure chunk usefulness or final answer correctness."},
            "unjudged_policy": unjudged, "questions": results, "macro_at_document_k": macro,
            "judged_questions_not_in_input": sorted(set(qrels) - seen)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Notebook input JSON or generated answers JSON")
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 3, 5, 10])
    parser.add_argument("--unjudged", choices=("error", "zero"), default="error")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = evaluate(load_json(args.input), load_json(args.judgments), args.k, args.unjudged)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    result["sources"] = {name: {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                         for name, path in (("input", args.input), ("judgments", args.judgments))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Evaluated {len(result['questions'])} questions -> {args.output}")
    for k, metrics in result["macro_at_document_k"].items():
        print(f"@{k}: " + "; ".join(f"{key}={metrics[key]['value']}" for key in ("ndcg", "recall_ge1", "recall_ge2")))


if __name__ == "__main__":
    main()
