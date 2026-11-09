"""Build a corpus index without loading the answer model."""

import gc
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

if __package__:
    from .embedding import encode_documents
    from .evidence import section_chunks, chunk_sources
    from .lexical import LexicalPreprocessor, build_bm25
    from .runtime import resolve_device
else:
    from embedding import encode_documents
    from evidence import section_chunks, chunk_sources
    from lexical import LexicalPreprocessor, build_bm25
    from runtime import resolve_device


@dataclass
class CorpusIndex:
    chunks: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    embeddings: object = None
    embedder: object = None
    lexical: object = None
    bm25: object = None
    kg_index: object = None


def build_index(corpus_dir, config, graph_config=None):
    import torch
    if __package__:
        from .documents import create_converter
        from .kg_retrieval import KGChunkIndex
    else:
        from documents import create_converter
        from kg_retrieval import KGChunkIndex
    index = CorpusIndex()
    converter = None
    for path in sorted(Path(corpus_dir).glob("*.pdf")):
        if converter is None:
            converter = create_converter(device=resolve_device(config.docling_device),
                                         num_threads=config.threads, formula_enrichment=config.formula_enrichment)
        try:
            result = converter.convert(str(path))
            text = result.document.export_to_markdown()
            del result
        except Exception as error:
            print(f"[rag] skipping {path.name}: {error}")
            continue
        chunks = section_chunks(text, config.chunk_size, config.chunk_overlap)
        index.sources.extend(chunk_sources(path.name, chunks))
        index.chunks.extend(chunks)
    del converter
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print(f"[rag] indexed {len(index.chunks)} chunks")
    if config.uses("dense") and index.chunks:
        from sentence_transformers import SentenceTransformer
        device = resolve_device(config.embedding_device)
        query_device = resolve_device(config.query_device)
        index.embedder = SentenceTransformer(str(config.embed_model), device="cpu", local_files_only=True)
        torch.set_num_threads(config.threads)
        started = time.perf_counter()
        try:
            index.embedder.to(device)
            index.embeddings = np.asarray(encode_documents(
                index.embedder, index.chunks, normalize_embeddings=True,
                show_progress_bar=False, batch_size=config.batch_size,
            ), dtype=np.float32)
        finally:
            index.embedder.to(query_device)
            if device == "cuda":
                torch.cuda.empty_cache()
        print(f"[rag] embeddings device={device}; seconds={time.perf_counter()-started:.2f}; query_device={query_device}")
    if config.uses("bm25"):
        index.lexical = LexicalPreprocessor(config.bm25_stopwords, config.bm25_stemming,
                                           config.preserve_words, config.stopwords_file)
        index.bm25 = build_bm25([index.lexical(t) for t in index.chunks],
                                config.bm25_k1, config.bm25_b, config.bm25_epsilon)
    mode = "graph" if config.uses("kg_graph") else "mentions" if config.uses("kg_mentions") else None
    if mode:
        index.kg_index = KGChunkIndex.from_directory(config.kg, index.chunks, mode=mode, config=graph_config)
    return index
