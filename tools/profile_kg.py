#!/usr/bin/env python3
"""Profile linking or graph retrieval; never interpret this as answer accuracy."""

import argparse
import json
import resource
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.kg_retrieval import EntityMatcher, GraphConfig, KGChunkIndex, load_artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=ROOT / "src/kg")
    parser.add_argument("--questions", type=Path, default=ROOT / "starter-kit/IEEE-CIS-DSQA-Starter-Kit/sample/sample_qa.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", choices=("linking", "graph"), default="linking")
    parser.add_argument("--chunks", type=Path, help='JSONL with {"text": "...", "chunk_id": "..."}; chunk_id is optional')
    parser.add_argument("--synthetic-label-chunks", action="store_true", help="Use one artificial chunk per KG label; no evidence-quality evaluation")
    args = parser.parse_args()
    if args.mode == "graph" and (bool(args.chunks) == args.synthetic_label_chunks):
        parser.error("graph mode needs exactly one of --chunks or --synthetic-label-chunks")
    if args.mode == "linking" and (args.chunks or args.synthetic_label_chunks):
        parser.error("chunk inputs are only used in graph mode")
    output = args.output or ROOT / f"docs/reports/kg-{args.mode}-report.json"
    start = time.perf_counter()
    manifest, nodes, edges = load_artifact(args.artifact)
    load_seconds = time.perf_counter() - start
    start = time.perf_counter()
    matcher = EntityMatcher(nodes)
    matcher_seconds = time.perf_counter() - start
    labels = {node["uri"]: node["label"] for node in nodes}
    graph_index = None
    graph_metrics = {}
    if args.mode == "graph":
        if args.synthetic_label_chunks:
            records = [{"text": n["label"], "chunk_id": n["uri"]} for n in nodes]
            chunk_source = "Synthetic: one canonical KG label per chunk. These are not scientific document passages."
        else:
            records = [json.loads(line) for line in args.chunks.read_text(encoding="utf-8").splitlines() if line.strip()]
            chunk_source = str(args.chunks)
        if not all(isinstance(record.get("text"), str) for record in records):
            parser.error("Each chunk record must contain a string 'text'")
        chunks = [record["text"] for record in records]
        config = GraphConfig.from_env()
        start = time.perf_counter()
        graph_index = KGChunkIndex(matcher, chunks, edges=edges, mode="graph", config=config)
        graph_seconds = time.perf_counter() - start
        start = time.perf_counter()
        mention_index = KGChunkIndex(matcher, chunks)
        mentions_seconds = time.perf_counter() - start
        graph_metrics = {"chunk_source": chunk_source, "chunk_count": len(chunks), "config": asdict(config),
                         "graph_index_build_seconds": graph_seconds, "mentions_index_build_seconds": mentions_seconds,
                         "entities_with_postings": len(graph_index.postings),
                         "seeds_with_eligible_neighbors": len(graph_index.neighbors)}
    results, times = [], []
    for question in json.loads(args.questions.read_text(encoding="utf-8")):
        durations = []
        for _ in range(5):
            start = time.perf_counter()
            if graph_index is None:
                uris = sorted(matcher.match(question["question"]))
            else:
                trace = graph_index.retrieve(question["question"])
                uris = trace["matched_entities"]
            durations.append((time.perf_counter() - start) * 1000)
        times.append(statistics.median(durations))
        results.append({"id": question["id"], "question": question["question"],
                        "entities": [{"uri": uri, "label": labels[uri]} for uri in uris]})
        if graph_index is not None:
            direct_ids = mention_index.rank(question["question"])
            graph_ids = [hit["chunk_id"] for hit in trace["hits"]]
            results[-1].update({
                "mentions_chunk_ids": direct_ids, "graph_chunk_ids": graph_ids,
                "new_chunk_ids": sorted(set(graph_ids) - set(direct_ids)),
                "expansion_seeds": trace["expansion_seeds"],
                "expansions": [{**item, "label": labels[item["entity"]]} for item in trace["expansions"]],
                "top_hits": [{**hit, "source_chunk_id": records[hit["chunk_id"]].get("chunk_id", hit["chunk_id"])} for hit in trace["hits"][:5]],
            })
    report = {
        "scope": ("Local CPU diagnostic on public questions. No answer references, evidence relevance labels, LLM or H100 evaluation. "
                  + (graph_metrics.get("chunk_source", "Entity linking only; no corpus index."))),
        "mode": args.mode,
        "counts": manifest["counts"], "input_hashes": manifest["inputs"],
        "artifact_bytes": sum(path.stat().st_size for path in args.artifact.iterdir() if path.is_file()),
        "load_seconds": load_seconds, "matcher_build_seconds": matcher_seconds,
        "process_peak_rss_mib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "median_query_ms": statistics.median(times) if times else None,
        "max_query_ms": max(times) if times else None,
        "questions_with_entities": sum(bool(r["entities"]) for r in results),
        "question_count": len(results), "results": results,
        **graph_metrics,
    }
    if graph_index is not None:
        report["questions_with_new_chunks"] = sum(bool(row["new_chunk_ids"]) for row in results)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
