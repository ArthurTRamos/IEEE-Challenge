#!/usr/bin/env python3
"""Export retrieved PDF chunks for manual review, without loading an LLM."""

import argparse
import csv
import gc
import hashlib
import inspect
import json
import math
import os
import platform
import re
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.embedding import encode_documents, encode_queries, embedding_inputs, retrieval_prefix
from src.retrieval_utils import VARIANTS, variant_weights
from src.retrieval import dense_ranking, lexical_ranking, select_evidence as select_ranked_evidence
from src.settings import PipelineConfig
from src.runtime import resolve_device, device_report


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def key_for(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def format_score(value):
    return "—" if value is None else f"{value:.6g}"


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def save_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def tree_fingerprint(directory):
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Missing local model directory: {directory}")
    files = {path.relative_to(directory).as_posix(): digest(path)
             for path in sorted(directory.rglob("*"))
             if path.is_file() and ".cache" not in path.relative_to(directory).parts
             and path.suffix in (".json", ".safetensors", ".bin", ".txt", ".onnx")}
    if not files:
        raise ValueError(f"No model files in {directory}")
    return key_for(files)


def discover_documents(root, document_ids=None):
    """Metadata is descriptive; selection roles/question hints are never labels."""
    root = Path(root).resolve()
    metadata = {}
    pdfs = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(name for name in subdirectories if not name.startswith(".") and name != "__pycache__")
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.lower() == ".pdf":
                pdfs.append(path)
            elif path.suffix.lower() == ".jsonl":
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        row = json.loads(line)
                        if "id" in row and "title" in row:
                            metadata[str(row["id"])] = row
    pdfs.sort(key=lambda path: path.relative_to(root).as_posix())
    found = {path.stem for path in pdfs}
    if document_ids:
        missing = set(document_ids) - found
        if missing:
            raise ValueError(f"Requested PDF IDs not found: {sorted(missing)}")
        pdfs = [path for path in pdfs if path.stem in document_ids]
    documents = []
    for path in pdfs:
        row = metadata.get(path.stem, {})
        documents.append({"document_id": path.stem, "relative_path": path.relative_to(root).as_posix(),
                          "pdf_path": str(path), "sha256": digest(path), "bytes": path.stat().st_size,
                          "title": row.get("title", path.stem),
                          "domain": "DONES" if path.stem.startswith("DONES-") else "AI Papers" if path.stem.startswith("AI-") else None,
                          "article_url": row.get("article_url", row.get("landing_url")), "pdf_url": row.get("pdf_url")})
    return documents, sorted(set(metadata) - found)


def load_questions(path, question_ids=None):
    path = Path(path)
    rows = ([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if path.suffix == ".jsonl" else json.loads(path.read_text(encoding="utf-8")))
    seen = set()
    for position, row in enumerate(rows, 1):
        identity = str(row.get("id", position))
        if identity in seen or not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError(f"Invalid/duplicate question: {identity}")
        seen.add(identity)
        row["id"] = identity
    if not rows:
        raise ValueError("No questions supplied")
    if question_ids is not None:
        requested = [str(identity) for identity in question_ids]
        if not requested or len(requested) != len(set(requested)):
            raise ValueError("Question IDs must be nonempty and unique")
        by_id = {row["id"]: row for row in rows}
        missing = set(requested) - set(by_id)
        if missing:
            raise ValueError(f"Unknown question IDs: {sorted(missing)}")
        rows = [by_id[identity] for identity in requested]
    return rows


def prepare_chunks(documents, output, cache, extraction_key, converter_factory, chunker, source_builder):
    """Parse sequentially and checkpoint each PDF. Cache only successful text."""
    output = Path(output)
    (output / "markdown").mkdir(parents=True, exist_ok=True)
    if cache:
        (Path(cache) / "text").mkdir(parents=True, exist_ok=True)
    converter = None
    chunks, processed = [], []
    for position, document in enumerate(documents, 1):
        started = time.perf_counter()
        record = dict(document)
        cache_key = key_for({"pdf_sha256": document["sha256"], "extraction": extraction_key})
        cached_path = Path(cache) / "text" / f"{cache_key}.json" if cache else None
        cached = json.loads(cached_path.read_text(encoding="utf-8")) if cached_path and cached_path.exists() else None
        record["text_cache_hit"] = cached is not None
        try:
            if cached is not None:
                if cached.get("key") != cache_key or cached.get("markdown_sha256") != key_for(cached["markdown"]):
                    raise ValueError("Invalid text cache; delete the entry or run with --no-cache")
                text, pages = cached["markdown"], cached["pages"]
                conversion_status, conversion_errors = "success", []
            else:
                if converter is None:
                    converter = converter_factory()
                result = converter.convert(document["pdf_path"])
                conversion_status = getattr(getattr(result, "status", None), "value", "success")
                if conversion_status not in ("success", "partial_success"):
                    raise ValueError(f"Docling status: {conversion_status}")
                text = result.document.export_to_markdown()
                pages = len(getattr(result.document, "pages", {}))
                conversion_errors = [str(error) for error in getattr(result, "errors", [])]
                del result
                if not text.strip():
                    raise ValueError("PDF produced empty Markdown")
                if cached_path and conversion_status == "success":
                    save_json(cached_path, {"key": cache_key, "markdown": text, "markdown_sha256": key_for(text), "pages": pages})
            record["extraction_seconds"] = time.perf_counter() - started
            markdown_name = f"{position:03d}-{document['sha256'][:12]}.md"
            (output / "markdown" / markdown_name).write_text(text, encoding="utf-8")
            record.update({"status": conversion_status, "conversion_errors": conversion_errors,
                           "pages": pages, "markdown": f"markdown/{markdown_name}", "markdown_characters": len(text)})
            started = time.perf_counter()
            texts = chunker(text)
            sources = source_builder(document["relative_path"], texts)
            for local_id, (body, source) in enumerate(zip(texts, sources)):
                chunks.append({**source, "index": len(chunks), "document_id": document["document_id"],
                               "document_sha256": document["sha256"], "local_chunk_index": local_id,
                               "title": document["title"], "document_domain": document["domain"],
                               "pdf_path": document["pdf_path"], "article_url": document.get("article_url"),
                               "text": body, "text_sha256": hashlib.sha256(body.encode()).hexdigest()})
            record.update({"chunking_seconds": time.perf_counter() - started, "chunks": len(texts)})
        except Exception as exc:
            record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "chunks": 0,
                           "extraction_seconds": time.perf_counter() - started})
        processed.append(record)
        save_jsonl(output / "documents.jsonl", processed)
        print(f"[pdf {position}/{len(documents)}] {document['document_id']}: {record['status']}; chunks={record['chunks']}; cache={record['text_cache_hit']}", flush=True)
        gc.collect()
    del converter
    gc.collect()
    save_jsonl(output / "chunks.jsonl", chunks)
    if not chunks:
        raise ValueError("No chunks were extracted; inspect documents.jsonl")
    return chunks, processed


def graph_configuration(args):
    from src.kg_retrieval import GraphConfig
    path = getattr(args, "graph_config", None)
    if path is None:
        return GraphConfig.from_env()
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("Graph config must be a JSON object")
    try:
        return GraphConfig(**values)
    except TypeError as exc:
        raise ValueError(f"Invalid graph config: {exc}") from exc


def evidence_configuration(args):
    return PipelineConfig.from_namespace(args).evidence_config()


def select_evidence(order, scores, chunks, question, args):
    return select_ranked_evidence(order, scores, chunks, question, PipelineConfig.from_namespace(args))


def document_embeddings(texts, embedder, model_key, cache, batch_size):
    """Shared cache contract for single runs and parameter sweeps."""
    import numpy as np
    embedding_key = key_for({"texts": texts, "model": model_key, "sentence_transformers": version("sentence-transformers"), "normalized": True})
    path = Path(cache) / "embeddings" / f"{embedding_key}.npy" if cache else None
    hit = bool(path and path.exists() and path.with_suffix(".json").exists())
    if hit:
        metadata = json.loads(path.with_suffix(".json").read_text())
        if metadata.get("sha256") != digest(path):
            raise ValueError("Embedding cache checksum mismatch")
        matrix = np.load(path, allow_pickle=False)
    else:
        matrix = np.asarray(encode_documents(embedder, texts, normalize_embeddings=True, batch_size=batch_size, show_progress_bar=True), dtype=np.float32)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, matrix, allow_pickle=False)
            save_json(path.with_suffix(".json"), {"sha256": digest(path), "shape": list(matrix.shape)})
    if matrix.ndim != 2 or matrix.shape != (len(texts), embedder.get_embedding_dimension()) or not np.isfinite(matrix).all():
        raise ValueError("Invalid embedding matrix shape or values")
    return matrix, hit


def export_review(output, questions, chunks, results, variants, include_answers=False):
    """Full text in JSONL/Markdown, one blank judgment per question/chunk union."""
    output = Path(output)
    (output / "questions").mkdir(exist_ok=True)
    save_jsonl(output / "retrieval.jsonl", results)
    from tools.export_llm_inputs import export_llm_inputs
    export_llm_inputs(output / "llm_inputs", questions, chunks, results, include_answers=include_answers)
    grouped = {}
    for result in results:
        grouped.setdefault(result["question_id"], {})[result["variant"]] = result
    columns = ["question_id", "chunk_id", "relevance", "evidence_quote", "notes", "document_id", "title", "section",
               *[f"{variant}_rank" for variant in variants], "text"]
    index_lines = ["# Revisão manual da recuperação", "", "Relevância ainda não julgada. Candidatos recuperados, sem geração pelo OLMo.", "",
                   "Preencha `judgments.csv`: vazio = não julgado; 0 = não relevante; 1 = apoio parcial; 2 = evidência direta.",
                   "Use `answerability.csv` para indicar se o conjunto de chunks é suficiente (yes/partial/no/unsure).", "",
                   "Os rankings não representam o contexto final do OLMo: não foi aplicado seu orçamento/tokenizer.", ""]
    with (output / "judgments.csv").open("w", newline="", encoding="utf-8") as handle, \
         (output / "answerability.csv").open("w", newline="", encoding="utf-8") as answer_handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        answers = csv.DictWriter(answer_handle, fieldnames=["question_id", "variant", "sufficient_evidence", "notes"])
        answers.writeheader()
        for number, question in enumerate(questions, 1):
            by_variant = grouped[question["id"]]
            filename = f"q-{number:03d}.md"
            index_lines.append(f"- [{question['id']} — {question.get('domain', '')}](questions/{filename})")
            lines = [f"# Pergunta {question['id']}", "", question["question"], "",
                     f"Domínio: {question.get('domain', 'não informado')}; tipo: {question.get('question_type', 'não informado')}.", "",
                     "Julgar suporte por passagem. Scores e posições são sinais de recuperação, não relevância anotada.", ""]
            if include_answers:
                lines += ["## Resposta de referência fornecida", "", question.get("answer", "Não fornecida."), ""]
            ranks = {}
            for variant in variants:
                result = by_variant[variant]
                lines += [f"## Ranking: {variant}", "", "| Posição | Chunk | Documento | Score de ordenação |", "| --- | --- | --- | --- |"]
                for hit in result["hits"]:
                    chunk = chunks[hit["index"]]
                    ranks.setdefault(hit["index"], {})[variant] = hit["rank"]
                    title = chunk["title"].replace("|", "\\|").replace("\n", " ")
                    lines.append(f"| {hit['rank']} | [C{hit['index']:06d}](#c{hit['index']:06d}) | {title} | {format_score(hit['score'])} |")
                lines.append("")
                answers.writerow({"question_id": question["id"], "variant": variant, "sufficient_evidence": "", "notes": ""})
            for chunk_index in sorted(ranks, key=lambda i: (min(ranks[i].values()), i)):
                chunk = chunks[chunk_index]
                relative_pdf = quote(os.path.relpath(chunk["pdf_path"], output / "questions").replace(os.sep, "/"))
                lines += [f'<a id="c{chunk_index:06d}"></a>', f"### C{chunk_index:06d}", "",
                          f"ID: `{chunk['chunk_id']}`", "", f"[Abrir PDF]({relative_pdf}) — {chunk['title']}", "",
                          f"Seção: {chunk.get('section') or 'não identificada'}", "",
                          "Posições: " + "; ".join(f"{variant}={rank}" for variant, rank in ranks[chunk_index].items()), ""]
                fence = "~" * max(3, 1 + max((len(s) for s in re.findall(r"~+", chunk["text"])), default=0))
                lines += [fence + "text", chunk["text"], fence, ""]
                writer.writerow({"question_id": question["id"], "chunk_id": chunk["chunk_id"], "relevance": "", "evidence_quote": "", "notes": "",
                                 "document_id": chunk["document_id"], "title": chunk["title"], "section": chunk.get("section"),
                                 **{f"{variant}_rank": ranks[chunk_index].get(variant, "") for variant in variants}, "text": chunk["text"]})
            (output / "questions" / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "review.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")


def run(args):
    wall_start = time.perf_counter()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output is not empty; choose a new directory to preserve reviews: {output}")
    output.mkdir(parents=True, exist_ok=True)
    args._owns_output = True
    save_json(output / "status.json", {"state": "running"})
    started = time.perf_counter()
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    from src import documents as pdf_documents
    from src.evidence import section_chunks, chunk_sources
    from src.kg_retrieval import EntityMatcher, GraphConfig, KGChunkIndex, load_artifact
    from src.retrieval_utils import rrf_fuse
    from src.lexical import LexicalPreprocessor, build_bm25
    timings = {"imports_seconds": time.perf_counter() - started}
    torch.set_num_threads(args.threads)
    cache = None if args.no_cache else args.cache.resolve()
    documents, missing_ids = discover_documents(args.corpus, args.document_ids)
    if args.limit_documents:
        documents = documents[:args.limit_documents]
    if not documents:
        raise ValueError("No PDFs found")
    questions = load_questions(args.questions, getattr(args, "question_ids", None))
    if args.limit_questions:
        questions = questions[:args.limit_questions]
    graph_config = graph_configuration(args)
    channels = {channel for variant in args.variants
                for channel, weight in variant_weights(variant, args.dense_weight, args.bm25_weight, args.kg_weight).items() if weight > 0}
    embedding_device = resolve_device(args.embedding_device) if "dense" in channels else None
    docling_device = resolve_device(getattr(args, "docling_device", "cpu"))
    print(f"[devices] embedding requested={args.embedding_device}, effective={embedding_device}; Docling={docling_device}", flush=True)
    started = time.perf_counter()
    extraction_key = {"docling_version": version("docling"), "device": docling_device, "threads": args.threads,
                      "converter_source": key_for(inspect.getsource(pdf_documents.create_converter)),
                      "layout_model_sha256": tree_fingerprint(ROOT / "src/docling_models"),
                      "formula_enrichment": getattr(args, "formula_enrichment", True)}
    model_key = tree_fingerprint(args.embed_model) if "dense" in channels else None
    timings["fingerprint_seconds"] = time.perf_counter() - started
    configuration = {"corpus": str(args.corpus.resolve()), "questions_file": str(args.questions.resolve()),
                     "question_ids": [q["id"] for q in questions],
                     "questions_sha256": digest(args.questions), "embedding_model": str(args.embed_model.resolve()),
                     "embedding_fingerprint": model_key, "embedding_device": embedding_device, "embedding_device_requested": args.embedding_device,
                     "device_report": device_report(), "channels_enabled": sorted(channels), "batch_size": args.batch_size,
                     "chunk_size": args.chunk_size, "chunk_overlap": args.chunk_overlap, "extraction": extraction_key,
                     "variants": args.variants, "top_k": args.top_k, "candidate_depth": args.candidate_depth, "rrf_k": args.rrf_k,
                     "weights": {v: variant_weights(v, args.dense_weight, args.bm25_weight, args.kg_weight) for v in args.variants},
                     "graph_config": vars(graph_config), "python": sys.version, "platform": platform.platform(),
                     "versions": {name: version(name) for name in ("torch", "numpy", "docling", "sentence-transformers", "rank-bm25")},
                     "code_sha256": {str(p.relative_to(ROOT)): digest(p) for p in (*sorted((ROOT / "src").glob("*.py")), Path(__file__))},
                     "cache_enabled": cache is not None, "missing_catalog_document_ids": missing_ids,
                     "include_reference_answers": args.include_reference_answers,
                     "evidence": {**evidence_configuration(args).to_dict(), "continuity": getattr(args, "continuity", True), "penalize_metadata": getattr(args, "penalize_metadata", True)},
                     "scope": "Retrieved candidates for manual review. No relevance ground truth, OLMo, accuracy or final prompt context."}
    save_json(output / "config.json", configuration)
    save_jsonl(output / "questions.jsonl", [{k: q[k] for k in ("id", "question", "domain", "question_type", *(["answer"] if args.include_reference_answers else [])) if k in q} for q in questions])
    started = time.perf_counter()
    chunks, documents = prepare_chunks(documents, output, cache, extraction_key,
                                      lambda: pdf_documents.create_converter(device=docling_device, num_threads=args.threads,
                                                                           formula_enrichment=getattr(args, "formula_enrichment", True)),
                                      lambda text: section_chunks(text, args.chunk_size, args.chunk_overlap), chunk_sources)
    timings["pdf_and_chunking_seconds"] = time.perf_counter() - started
    texts = [chunk["text"] for chunk in chunks]
    embedder, embeddings = None, None
    timings.update(embedding_model_load_seconds=0, embedding_token_audit_seconds=0,
                   document_embeddings_seconds=0, embeddings_cache_hit=None)
    configuration["embedding_settings"] = None
    if "dense" in channels:
        started = time.perf_counter()
        embedder = SentenceTransformer(str(args.embed_model.resolve()), device=embedding_device, local_files_only=True)
        timings["embedding_model_load_seconds"] = time.perf_counter() - started
        configuration["embedding_settings"] = {"max_seq_length": embedder.max_seq_length,
                                               "dimension": embedder.get_embedding_dimension(),
                                               "query_prefix": retrieval_prefix(embedder, "query"),
                                               "document_prefix": retrieval_prefix(embedder, "document")}
        started = time.perf_counter()
        for start in range(0, len(texts), 64):
            encoded = embedder.tokenizer(embedding_inputs(embedder, texts[start:start + 64], "document"), truncation=False, padding=False, verbose=False)["input_ids"]
            for chunk, ids in zip(chunks[start:start + 64], encoded):
                chunk.update(embedding_tokens_untruncated=len(ids), embedding_truncated=len(ids) > embedder.max_seq_length)
        timings["embedding_token_audit_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        embeddings, timings["embeddings_cache_hit"] = document_embeddings(texts, embedder, model_key, cache, args.batch_size)
        timings["document_embeddings_seconds"] = time.perf_counter() - started
    else:
        for chunk in chunks:
            chunk.update(embedding_tokens_untruncated=None, embedding_truncated=False)
    save_jsonl(output / "chunks.jsonl", chunks)
    started = time.perf_counter()
    lexical, bm25 = None, None
    lexical_config = PipelineConfig.from_namespace(args)
    bm25_parameters = {"k1": lexical_config.bm25_k1, "b": lexical_config.bm25_b, "epsilon": lexical_config.bm25_epsilon}
    if "bm25" in channels:
        lexical = LexicalPreprocessor(getattr(args, "bm25_stopwords", False), getattr(args, "bm25_stemming", False),
                                      getattr(args, "preserve_words", ()), getattr(args, "stopwords_file", None))
        bm25 = build_bm25([lexical(text) for text in texts], **bm25_parameters)
    configuration["bm25"] = {**bm25_parameters, "preprocessing": lexical.metadata if lexical else None}
    timings["bm25_index_seconds"] = time.perf_counter() - started
    kg_indices = {}
    needed_kg = {mode for mode in ("mentions", "graph") if f"kg_{mode}" in channels}
    if needed_kg:
        started = time.perf_counter()
        manifest, nodes, edges = load_artifact(args.kg)
        matcher = EntityMatcher(nodes)
        configuration["kg_manifest_sha256"] = digest(args.kg / "manifest.json")
        timings["kg_load_and_matcher_seconds"] = time.perf_counter() - started
        for mode in ("mentions", "graph"):
            if mode in needed_kg:
                started = time.perf_counter()
                kg_indices[mode] = KGChunkIndex(matcher, texts, edges=edges, mode=mode, config=graph_config)
                timings[f"kg_{mode}_index_seconds"] = time.perf_counter() - started
    results, query_timings, query_token_audit = [], [], []
    for question in questions:
        measured = {"question_id": question["id"]}
        rankings = {}
        dense_scores, lexical_scores = None, None
        if embedder is not None:
            started = time.perf_counter()
            query_embedding = encode_queries(embedder, [question["question"]], normalize_embeddings=True, show_progress_bar=False)[0]
            measured["query_embedding_seconds"] = time.perf_counter() - started
            query_tokens = embedder.tokenizer(embedding_inputs(embedder, [question["question"]], "query"), truncation=False, padding=False, verbose=False)["input_ids"][0]
            query_token_audit.append({"question_id": question["id"], "tokens": len(query_tokens),
                                      "max_seq_length": embedder.max_seq_length, "truncated": len(query_tokens) > embedder.max_seq_length})
            started = time.perf_counter()
            dense_scores = embeddings @ query_embedding
            rankings["dense"] = dense_ranking(dense_scores, args.candidate_depth)
            measured["dense_search_seconds"] = time.perf_counter() - started
        if lexical is not None:
            started = time.perf_counter()
            lexical_scores = np.asarray(bm25.get_scores(lexical(question["question"]))) if bm25 else np.zeros(len(chunks))
            rankings["bm25"] = lexical_ranking(lexical_scores, args.candidate_depth)
            measured["bm25_search_seconds"] = time.perf_counter() - started
        traces = {}
        for mode, kg_index in kg_indices.items():
            started = time.perf_counter()
            trace = kg_index.retrieve(question["question"], top_k=args.candidate_depth)
            rankings[f"kg_{mode}"] = [hit["chunk_id"] for hit in trace["hits"]]
            traces[mode] = trace
            measured[f"kg_{mode}_search_seconds"] = time.perf_counter() - started
        positions = {channel: {int(index): rank for rank, index in enumerate(order, 1)} for channel, order in rankings.items()}
        for variant in args.variants:
            started = time.perf_counter()
            order, scores = rrf_fuse(rankings, configuration["weights"][variant], args.rrf_k)
            measured[f"{variant}_fusion_seconds"] = time.perf_counter() - started
            selected, adjusted, anchors = select_evidence(order, scores, chunks, question["question"], args)
            hits = [{"rank": rank, "index": int(index), "chunk_id": chunks[index]["chunk_id"], "text": texts[index],
                     "document_id": chunks[index]["document_id"], "section": chunks[index]["section"], "score": adjusted.get(index), "rrf_score": scores.get(index),
                     "content_kind": chunks[index].get("content_kind", "body"),
                     "selection_role": "anchor" if index in anchors else "neighbor",
                     "dense_score": float(dense_scores[index]) if dense_scores is not None else None,
                     "bm25_score": float(lexical_scores[index]) if lexical_scores is not None else None,
                     "channel_ranks": {name: ranks.get(index) for name, ranks in positions.items()}}
                    for rank, index in enumerate(selected, 1)]
            results.append({"question_id": question["id"], "variant": variant, "hits": hits,
                            "kg_trace": traces.get(variant.removeprefix("dense_")), "relevance_judgments": None})
        query_timings.append(measured)
        print(f"[query {question['id']}] exported {len(args.variants)} rankings", flush=True)
    started = time.perf_counter()
    export_review(output, questions, chunks, results, args.variants, args.include_reference_answers)
    timings["review_export_seconds"] = time.perf_counter() - started
    save_json(output / "config.json", configuration)
    save_jsonl(output / "query-timings.jsonl", query_timings)
    save_json(output / "query-embedding-audit.json", query_token_audit)
    timings["total_run_seconds"] = time.perf_counter() - wall_start
    timings["query_stage_summary_seconds"] = {
        name: {"median": float(np.median([row[name] for row in query_timings])),
               "p95": float(np.percentile([row[name] for row in query_timings], 95))}
        for name in query_timings[0] if name != "question_id"}
    try:
        import resource
        timings["process_peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 if sys.platform != "darwin" else 1024 ** 2)
    except ImportError:
        timings["process_peak_rss_mib"] = None
    timings["cuda_peak_allocated_mib"] = torch.cuda.max_memory_allocated() / 1024 ** 2 if torch.cuda.is_available() else None
    summary = {"documents": len(documents), "failed_documents": sum(d["status"] == "failed" for d in documents),
               "partial_documents": sum(d["status"] == "partial_success" for d in documents), "chunks": len(chunks),
               "questions": len(questions), "variants": args.variants, "truncated_embedding_chunks": sum(c["embedding_truncated"] for c in chunks),
               "text_cache_hits": sum(d["text_cache_hit"] for d in documents), "missing_catalog_document_ids": missing_ids,
               "truncated_embedding_queries": sum(q["truncated"] for q in query_token_audit),
               "embedding_audit_performed": embedder is not None, "quality_metrics": None, "annotation_status": "unjudged", "output": str(output)}
    save_json(output / "timings.json", timings)
    save_json(output / "summary.json", summary)
    save_json(output / "status.json", {"state": "complete"})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def parse_args(argv=None):
    from tools.configuration import parse_with_config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Flat JSON settings; explicit flags override the file")
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/download_pdfs")
    parser.add_argument("--questions", type=Path, default=ROOT / "starter-kit/IEEE-CIS-DSQA-Starter-Kit/sample/sample_qa.json")
    parser.add_argument("--output", type=Path, default=ROOT / "experiments/runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/local-retrieval")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--use-cache", dest="no_cache", action="store_false", default=False)
    parser.add_argument("--embed-model", type=Path, default=ROOT / "src/embed_model")
    parser.add_argument("--embedding-device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--docling-device", choices=("auto", "cpu", "cuda"), default="cpu")
    parser.add_argument("--kg", type=Path, default=ROOT / "src/kg")
    parser.add_argument("--graph-config", type=Path, help="JSON GraphConfig fields; otherwise use KG_GRAPH_* environment variables")
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=["hybrid"])
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--candidate-depth", type=int, default=100)
    parser.add_argument("--rrf-k", type=float, default=60)
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--kg-weight", type=float, default=0.5)
    parser.add_argument("--bm25-stopwords", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--bm25-stemming", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--preserve-words", nargs="+")
    parser.add_argument("--stopwords-file", type=Path)
    parser.add_argument("--bm25-k1", type=float, default=1.2)
    parser.add_argument("--bm25-b", type=float, default=0.75)
    parser.add_argument("--bm25-epsilon", type=float, default=0.25)
    parser.add_argument("--formula-enrichment", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--continuity", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--penalize-metadata", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--reference-weight", type=float, default=0.5)
    parser.add_argument("--front-matter-weight", type=float, default=0.7)
    parser.add_argument("--neighbors-before", type=int, default=1)
    parser.add_argument("--neighbors-after", type=int, default=3)
    parser.add_argument("--small-section-chunks", type=int, default=6)
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--document-ids", nargs="+")
    parser.add_argument("--question-ids", nargs="+", help="Question IDs to keep, in the requested order")
    parser.add_argument("--limit-documents", type=int)
    parser.add_argument("--limit-questions", type=int)
    parser.add_argument("--include-reference-answers", action="store_true")
    args = parse_with_config(parser, sys.argv[1:] if argv is None else argv)
    if args.preserve_words is None:
        args.preserve_words = []
    if any(value is not None and value <= 0 for value in (args.top_k, args.candidate_depth, args.chunk_size, args.batch_size, args.threads, args.limit_documents, args.limit_questions)):
        parser.error("Counts and sizes must be positive")
    if args.top_k > args.candidate_depth or not 0 <= args.chunk_overlap < args.chunk_size:
        parser.error("top-k must not exceed candidate-depth; overlap must be between 0 and chunk-size - 1")
    if any(not math.isfinite(value) or value < 0 for value in (args.rrf_k, args.dense_weight, args.bm25_weight, args.kg_weight)):
        parser.error("Weights and RRF k must be finite and nonnegative")
    if len(set(args.variants)) != len(args.variants):
        parser.error("Variants must be unique")
    for variant in args.variants:
        if not any(variant_weights(variant, args.dense_weight, args.bm25_weight, args.kg_weight).values()):
            parser.error(f"All channels are disabled for variant {variant}")
    if not math.isfinite(args.bm25_k1) or args.bm25_k1 <= 0 or not math.isfinite(args.bm25_b) or not 0 <= args.bm25_b <= 1:
        parser.error("BM25 requires k1 > 0 and 0 <= b <= 1")
    if not math.isfinite(args.bm25_epsilon) or args.bm25_epsilon < 0:
        parser.error("BM25 epsilon must be finite and nonnegative")
    try:
        evidence_configuration(args)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main():
    args = parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("OMP_NUM_THREADS", str(args.threads))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    args._owns_output = False
    try:
        run(args)
    except Exception as exc:
        if args._owns_output:
            save_json(args.output / "failure.json", {"error": f"{type(exc).__name__}: {exc}"})
            save_json(args.output / "status.json", {"state": "failed"})
        raise


if __name__ == "__main__":
    main()
