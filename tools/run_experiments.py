#!/usr/bin/env python3
"""Run a configured BM25 grid, reusing PDFs/embeddings and nonlexical rankings."""

import argparse
import copy
import csv
import gc
import itertools
import json
import math
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import run_retrieval as runner

CONTROL_VARIANTS = {"dense", "dense_mentions", "dense_graph"}
BM25_VARIANTS = {"bm25", "hybrid", "mentions", "graph"}
REFERENCES = {"bm25": "dense", "hybrid": "dense", "mentions": "dense_mentions", "graph": "dense_graph"}


def load_grid(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {"schema_version", "pipeline_config", "output_root", "preprocessing", "k1", "b", "epsilon", "preserve_words", "stopwords_file", "controls", "variants"}
    if not isinstance(config, dict) or set(config) - allowed or config.get("schema_version") != 1:
        raise ValueError("Invalid experiment schema or unknown configuration keys")
    for name in ("pipeline_config", "output_root"):
        if not isinstance(config.get(name), str) or not config[name]:
            raise ValueError(f"{name} must be a path string")
    for name, choices in (("controls", CONTROL_VARIANTS), ("variants", BM25_VARIANTS)):
        values = config.get(name)
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v in choices for v in values) or len(set(values)) != len(values):
            raise ValueError(f"Invalid {name}")
    if any(REFERENCES[v] not in config["controls"] for v in config["variants"]):
        raise ValueError("Include the corresponding no-BM25 control for every variant")
    for name in ("k1", "b"):
        values = config.get(name)
        if not isinstance(values, list) or not values or not all(type(v) in (int, float) and math.isfinite(v) for v in values) or len(set(values)) != len(values):
            raise ValueError(f"Invalid/duplicate {name} grid values")
        if name == "k1" and any(v <= 0 for v in values) or name == "b" and any(not 0 <= v <= 1 for v in values):
            raise ValueError(f"Values out of range: {name}")
    epsilon = config.get("epsilon", 0.25)
    if type(epsilon) not in (int, float) or not math.isfinite(epsilon) or epsilon < 0:
        raise ValueError("Invalid epsilon")
    config["epsilon"] = epsilon
    preserved = config.get("preserve_words", [])
    if not isinstance(preserved, list) or not all(isinstance(v, str) for v in preserved):
        raise ValueError("preserve_words must be a list of strings")
    config["preserve_words"] = preserved
    if config.get("stopwords_file") is not None and not isinstance(config["stopwords_file"], str):
        raise ValueError("stopwords_file must be a path or null")
    preprocessors = config.get("preprocessing")
    if not isinstance(preprocessors, list) or not preprocessors:
        raise ValueError("preprocessing must be a nonempty list")
    names, modes = set(), set()
    for item in preprocessors:
        if not isinstance(item, dict) or set(item) != {"name", "stopwords", "stemming"}:
            raise ValueError("Each preprocessor needs name, stopwords and stemming")
        if not isinstance(item["name"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", item["name"]):
            raise ValueError("Preprocessor names must be simple lowercase identifiers")
        if type(item["stopwords"]) is not bool or type(item["stemming"]) is not bool:
            raise ValueError("Preprocessing flags must be booleans")
        mode = (item["stopwords"], item["stemming"])
        if item["name"] in names or mode in modes:
            raise ValueError("Duplicate preprocessor name or configuration")
        names.add(item["name"])
        modes.add(mode)
    return config


def build_cases(config):
    def number(value):
        return format(value, ".12g").replace(".", "p").replace("-", "m")
    cases = [{"id": f"{p['name']}-k1-{number(k1)}-b-{number(b)}", "preprocessing": p, "k1": k1, "b": b, "epsilon": config["epsilon"]}
             for p, k1, b in itertools.product(config["preprocessing"], config["k1"], config["b"])]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Numeric values produce colliding case IDs")
    return cases


def compare_rankings(hits, reference):
    left, right = [hit["index"] for hit in hits], [hit["index"] for hit in reference]
    union = set(left) | set(right)
    return {"overlap": len(set(left) & set(right)), "jaccard": len(set(left) & set(right)) / len(union) if union else 1.0,
            "top1_changed": (left[:1] != right[:1]), "new_chunks": len(set(left) - set(right))}


def export_suite_review(output, questions, chunks, results, include_answers=False):
    """One global annotation pool; compact per-case tables link to full text."""
    output = Path(output)
    from tools.export_llm_inputs import export_llm_inputs
    export_llm_inputs(output / "llm_inputs", questions, chunks, results, include_answers=include_answers)
    (output / "cases").mkdir(exist_ok=True)
    (output / "questions").mkdir(exist_ok=True)
    question_files = {q["id"]: f"q-{i:03d}.md" for i, q in enumerate(questions, 1)}
    pools = {q["id"]: {} for q in questions}
    by_case = {}
    for result in results:
        by_case.setdefault(result["case_id"], []).append(result)
        for hit in result["hits"]:
            pools[result["question_id"]].setdefault(hit["index"], []).append((result["case_id"], result["variant"], hit["rank"]))
    with (output / "rankings.csv").open("w", newline="", encoding="utf-8") as handle, \
         (output / "answerability.csv").open("w", newline="", encoding="utf-8") as answer_handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "variant", "question_id", "rank", "chunk_id", "score"])
        answers = csv.DictWriter(answer_handle, fieldnames=["case_id", "variant", "question_id", "sufficient_evidence", "notes"])
        writer.writeheader()
        answers.writeheader()
        for case_id, rows in by_case.items():
            lines = [f"# Configuração {case_id}", "", "Julgamentos compartilhados em `../judgments.csv`. Posições não representam relevância.", ""]
            for row in rows:
                filename = question_files[row["question_id"]]
                lines += [f"## Pergunta {row['question_id']} — {row['variant']}", "",
                          "| Posição | Texto completo | Documento | Score |", "| --- | --- | --- | --- |"]
                for hit in row["hits"]:
                    chunk = chunks[hit["index"]]
                    lines.append(f"| {hit['rank']} | [C{hit['index']:06d}](../questions/{filename}#c{hit['index']:06d}) | {chunk['document_id']} | {runner.format_score(hit['score'])} |")
                    writer.writerow({"case_id": case_id, "variant": row["variant"], "question_id": row["question_id"],
                                     "rank": hit["rank"], "chunk_id": chunk["chunk_id"], "score": hit["score"]})
                lines.append("")
                answers.writerow({"case_id": case_id, "variant": row["variant"], "question_id": row["question_id"], "sufficient_evidence": "", "notes": ""})
            (output / "cases" / f"{case_id}.md").write_text("\n".join(lines), encoding="utf-8")
    pairs = 0
    with (output / "judgments.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["question_id", "chunk_id", "document_sha256", "text_sha256", "relevance", "evidence_quote", "notes", "document_id", "title", "section", "text"])
        writer.writeheader()
        for question in questions:
            lines = [f"# Pergunta {question['id']}", "", question["question"], "",
                     "Vazio = não julgado; 0 = irrelevante; 1 = apoio parcial; 2 = evidência direta.", ""]
            for index in sorted(pools[question["id"]]):
                chunk = chunks[index]
                lines += [f'<a id="c{index:06d}"></a>', f"## C{index:06d} — {chunk['document_id']}", "",
                          chunk["title"], "", f"ID: `{chunk['chunk_id']}`; seção: {chunk.get('section') or 'não identificada'}.", "",
                          f"[Abrir PDF]({runner.quote(os.path.relpath(chunk['pdf_path'], output / 'questions').replace(os.sep, '/'))})", "",
                          f"Aparece em {len(pools[question['id']][index])} rankings; detalhes em `rankings.csv`.", ""]
                fence = "~" * max(3, 1 + max((len(s) for s in re.findall(r"~+", chunk["text"])), default=0))
                lines += [fence + "text", chunk["text"], fence, ""]
                writer.writerow({"question_id": question["id"], **{key: chunk.get(key, "") for key in
                                 ("chunk_id", "document_sha256", "text_sha256", "document_id", "title", "section", "text")},
                                 "relevance": "", "evidence_quote": "", "notes": ""})
                pairs += 1
            (output / "questions" / question_files[question["id"]]).write_text("\n".join(lines), encoding="utf-8")
    index_lines = ["# Grade de experimentos BM25", "", "Sem relevância anotada: não há configuração vencedora automática.", "",
                   "- `judgments.csv`: pool único para julgar cada par pergunta/chunk uma vez.",
                   "- `rankings.csv`: posições de cada candidato por configuração/variante.",
                   "- `comparisons.csv`: mudanças em relação ao controle sem BM25; não é acurácia.",
                   "- `answerability.csv`: suficiência por pergunta/configuração/variante.", "", "## Configurações", ""]
    index_lines += [f"- [{case_id}](cases/{case_id}.md)" for case_id in by_case]
    index_lines += ["", "## Texto completo por pergunta", ""]
    index_lines += [f"- [{q['id']} — {q.get('domain', '')}](questions/{question_files[q['id']]})" for q in questions]
    (output / "review.md").write_text("\n".join(index_lines), encoding="utf-8")
    return pairs


def execute(args, config, cases):
    started = time.perf_counter()
    output = args.output
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    args._owns_output = True
    runner.save_json(output / "status.json", {"state": "running"})
    pipeline_args = runner.parse_args(["--config", str((ROOT / config["pipeline_config"]).resolve())])
    pipeline_snapshot = json.loads((ROOT / config["pipeline_config"]).read_text(encoding="utf-8"))
    runner.save_json(output / "pipeline-config.json", pipeline_snapshot)
    for variant in config["variants"] + config["controls"]:
        if not any(runner.variant_weights(variant, pipeline_args.dense_weight, pipeline_args.bm25_weight, pipeline_args.kg_weight).values()):
            raise ValueError(f"Variant has no active channels: {variant}")
    runner.save_json(output / "experiment-config.json", config)
    runner.save_json(output / "case-plan.json", cases)
    prepared = copy.copy(pipeline_args)
    prepared.output = output / "prepared"
    prepared.variants = ["dense"]
    runner.run(prepared)
    gc.collect()
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    from src.lexical import LexicalPreprocessor, build_bm25
    from src.kg_retrieval import EntityMatcher, KGChunkIndex, load_artifact
    from src.retrieval_utils import rrf_fuse
    torch.set_num_threads(pipeline_args.threads)
    chunks = [json.loads(line) for line in (prepared.output / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    questions = runner.load_questions(pipeline_args.questions, pipeline_args.question_ids)
    if pipeline_args.limit_questions:
        questions = questions[:pipeline_args.limit_questions]
    texts = [chunk["text"] for chunk in chunks]
    runner.save_jsonl(output / "chunks.jsonl", chunks)
    runner.save_jsonl(output / "questions.jsonl", [{key: q[key] for key in ("id", "question", "domain", "question_type", *(["answer"] if pipeline_args.include_reference_answers else [])) if key in q} for q in questions])
    encoder = SentenceTransformer(str(pipeline_args.embed_model.resolve()), device=pipeline_args.embedding_device, local_files_only=True)
    matrix, embedding_cache_hit = runner.document_embeddings(texts, encoder, runner.tree_fingerprint(pipeline_args.embed_model),
                                                           None if pipeline_args.no_cache else pipeline_args.cache, pipeline_args.batch_size)
    kg_needed = {mode for mode in ("mentions", "graph") if mode in config["variants"] or f"dense_{mode}" in config["controls"]}
    kg_indices = {}
    graph_config = runner.graph_configuration(pipeline_args)
    runner.save_json(output / "effective-retrieval.json", {
        "top_k": pipeline_args.top_k, "candidate_depth": pipeline_args.candidate_depth, "rrf_k": pipeline_args.rrf_k,
        "graph_config": vars(graph_config),
        "weights": {v: runner.variant_weights(v, pipeline_args.dense_weight, pipeline_args.bm25_weight, pipeline_args.kg_weight)
                    for v in config["variants"] + config["controls"]}})
    if kg_needed:
        _, nodes, edges = load_artifact(pipeline_args.kg)
        matcher = EntityMatcher(nodes)
        for mode in sorted(kg_needed):
            kg_indices[mode] = KGChunkIndex(matcher, texts, edges=edges, mode=mode, config=graph_config)
    shared = {}
    for question in questions:
        embedding = encoder.encode([question["question"]], normalize_embeddings=True, show_progress_bar=False)[0]
        dense_scores = matrix @ embedding
        ranking = {"dense": np.argsort(-dense_scores, kind="stable")[:pipeline_args.candidate_depth].tolist()}
        traces = {}
        for mode, index in kg_indices.items():
            traces[mode] = index.retrieve(question["question"], top_k=pipeline_args.candidate_depth)
            ranking[f"kg_{mode}"] = [hit["chunk_id"] for hit in traces[mode]["hits"]]
        shared[question["id"]] = {"rankings": ranking, "dense_scores": dense_scores, "kg_traces": traces}
    runner.save_jsonl(output / "shared-channels.jsonl", [{"question_id": qid, "rankings": row["rankings"], "kg_traces": row["kg_traces"]} for qid, row in shared.items()])
    results, comparisons, timings, control_hits = [], [], [], {}

    def get_result(qid, variant, case_id, rankings, lexical_scores=None):
        weights = runner.variant_weights(variant, pipeline_args.dense_weight, pipeline_args.bm25_weight, pipeline_args.kg_weight)
        order, scores = rrf_fuse(rankings, weights, pipeline_args.rrf_k)
        selected, adjusted, anchors = runner.select_evidence(order, scores, chunks, next(q["question"] for q in questions if q["id"] == qid), pipeline_args)
        return {"case_id": case_id, "variant": variant, "question_id": qid,
                "hits": [{"index": index, "chunk_id": chunks[index]["chunk_id"], "rank": rank, "score": adjusted.get(index), "rrf_score": scores.get(index),
                          "content_kind": chunks[index].get("content_kind", "body"),
                          "selection_role": "anchor" if index in anchors else "neighbor",
                          "dense_score": float(shared[qid]["dense_scores"][index]),
                          "bm25_score": float(lexical_scores[index]) if lexical_scores is not None else None}
                         for rank, index in enumerate(selected, 1)]}

    for qid, row in shared.items():
        for variant in config["controls"]:
            result = get_result(qid, variant, "controls", row["rankings"])
            control_hits[(qid, variant)] = result["hits"]
            results.append(result)
    lexical, tokenized, query_tokens, current_mode = None, None, None, None
    for position, case in enumerate(cases, 1):
        mode = case["preprocessing"]
        tokenize_seconds = 0.0
        if mode["name"] != current_mode:
            begin = time.perf_counter()
            lexical = LexicalPreprocessor(mode["stopwords"], mode["stemming"], config["preserve_words"],
                                          ROOT / config["stopwords_file"] if config.get("stopwords_file") else None)
            tokenized = [lexical(text) for text in texts]
            query_tokens = {q["id"]: lexical(q["question"]) for q in questions}
            current_mode = mode["name"]
            tokenize_seconds = time.perf_counter() - begin
            runner.save_json(output / "preprocessing" / f"{current_mode}.json", {
                **lexical.metadata, "total_tokens": sum(map(len, tokenized)),
                "vocabulary_size": len({word for chunk in tokenized for word in chunk}),
                "empty_chunks": sum(not chunk for chunk in tokenized)})
        begin = time.perf_counter()
        bm25 = build_bm25(tokenized, case["k1"], case["b"], case["epsilon"])
        build_seconds = time.perf_counter() - begin
        begin = time.perf_counter()
        for question in questions:
            qid = question["id"]
            scores = np.asarray(bm25.get_scores(query_tokens[qid])) if bm25 else np.zeros(len(chunks))
            order = np.argsort(-scores, kind="stable")
            rankings = {**shared[qid]["rankings"], "bm25": order[scores[order] != 0][:pipeline_args.candidate_depth].tolist()}
            for variant in config["variants"]:
                result = get_result(qid, variant, case["id"], rankings, scores)
                results.append(result)
                reference = REFERENCES[variant]
                comparisons.append({"case_id": case["id"], "preprocessing": mode["name"], "k1": case["k1"], "b": case["b"],
                                    "variant": variant, "question_id": qid, "reference": reference,
                                    **compare_rankings(result["hits"], control_hits[(qid, reference)])})
        elapsed = time.perf_counter() - begin
        timings.append({"case_id": case["id"], "tokenization_seconds": tokenize_seconds, "index_seconds": build_seconds,
                        "all_queries_and_fusion_seconds": elapsed, "preprocessing_metadata": lexical.metadata})
        runner.save_json(output / "status.json", {"state": "running", "completed_cases": position, "total_cases": len(cases)})
        print(f"[grid {position}/{len(cases)}] {case['id']}", flush=True)
        del bm25
    runner.save_jsonl(output / "retrieval.jsonl", results)
    runner.save_jsonl(output / "case-timings.jsonl", timings)
    with (output / "comparisons.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparisons[0]))
        writer.writeheader()
        writer.writerows(comparisons)
    pairs = export_suite_review(output, questions, chunks, results, pipeline_args.include_reference_answers)
    runner.save_json(output / "provenance.json", {"grid_settings_sha256": runner.key_for(config),
                    "pipeline_settings_sha256": runner.key_for(pipeline_snapshot), "graph_config": vars(graph_config),
                    "source_sha256": {name: runner.digest(ROOT / name) for name in ("src/lexical.py", "tools/run_experiments.py", "tools/configuration.py")},
                    "embedding_cache_hit_after_preparation": embedding_cache_hit})
    summary = {"bm25_cases": len(cases), "no_bm25_controls": len(config["controls"]),
               "retrieval_configurations": len(cases) * len(config["variants"]) + len(config["controls"]),
               "questions": len(questions), "chunks": len(chunks), "rankings": len(results), "review_pairs": pairs,
               "total_seconds": time.perf_counter() - started, "quality_metrics": None, "annotation_status": "unjudged"}
    runner.save_json(output / "summary.json", summary)
    runner.save_json(output / "status.json", {"state": "complete"})
    print(json.dumps({"output": str(output), **summary}, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "experiments/configs/bm25-grid.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-only", action="store_true", help="Validate and enumerate the grid without loading models or writing output")
    args = parser.parse_args()
    config = load_grid(args.config)
    cases = build_cases(config)
    runner.parse_args(["--config", str(ROOT / config["pipeline_config"])])
    if args.plan_only:
        print(json.dumps({"bm25_cases": len(cases), "controls": config["controls"], "variants": config["variants"],
                          "retrieval_configurations": len(cases) * len(config["variants"]) + len(config["controls"]), "cases": cases}, indent=2))
        return
    if args.output is None:
        args.output = ROOT / config["output_root"] / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6])
    args.output = args.output.resolve()
    args._owns_output = False
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    try:
        execute(args, config, cases)
    except Exception as exc:
        if args._owns_output:
            runner.save_json(args.output / "status.json", {"state": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise


if __name__ == "__main__":
    main()
