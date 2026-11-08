"""
Hybrid RAG — IEEE-CIS Technical Challenge on Domain-Specific Question
Answering with LLMs.

Blind retrieval over the whole corpus: every PDF in corpus_dir is parsed with
Docling, chunked and embedded once per run, then for each question every
chunk is ranked by BM25 and cosine similarity. An optional DBpedia entity
index adds a third ranking of corpus chunks. Reciprocal Rank Fusion (RRF)
combines the rankings, and the best-ranked chunks are packed
into a fixed context budget before asking the base model. No document_id is
known to this code — the same "search has to find it" design as a real
participant would face.

Needs a local copy of Docling's layout model and of the embedding model next
to this file (see build.sh): the evaluation environment has no internet
access, so neither can be downloaded there the first time they're used.
"""

import os
import re
from pathlib import Path

import numpy as np
import torch
from rank_bm25 import BM25Okapi
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForCausalLM, AutoTokenizer

if __package__:
    from .kg_retrieval import GraphConfig, KGChunkIndex
    from .retrieval_utils import rrf_fuse
    from .prompts import SYSTEM_PROMPT, build_user_message
    from .lexical import LexicalPreprocessor
    from .evidence import EvidenceConfig, section_chunks, chunk_sources, penalize_order, continuity_order
else:
    from kg_retrieval import GraphConfig, KGChunkIndex
    from retrieval_utils import rrf_fuse
    from prompts import SYSTEM_PROMPT, build_user_message
    from lexical import LexicalPreprocessor
    from evidence import EvidenceConfig, section_chunks, chunk_sources, penalize_order, continuity_order

MAX_NEW_TOKENS = 2048
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
RETRIEVAL_TOP_K = 100
RRF_K = 60
KG_RRF_WEIGHT = 0.5  # Experimental: evaluate against KG_MODE=off.
KG_PATH = Path(__file__).parent / "kg"

# A local copy, not the "sentence-transformers/all-MiniLM-L6-v2" repo id:
# same reason as the Docling model below — small, but still a model the
# evaluation environment doesn't have pre-downloaded, and there's no
# internet there to fetch it by name (see build.sh).
EMBED_MODEL_PATH = str(Path(__file__).parent / "embed_model")

# Budget for the evidence block only, excluding system/user instructions.
# Full latency and VRAM with the new formula stage still require an H100 run.
MAX_CONTEXT_TOKENS = 10_000

# Loaded once and reused across every question in the run (answer() is
# called once per question, in the same process).
_cache = {}
_model_cache = {}
_bm25_preprocessor = None


def _docling_converter(device=None, num_threads=None, formula_enrichment=False) -> DocumentConverter:
    pipeline_options = PdfPipelineOptions(
        artifacts_path=str(Path(__file__).parent / "docling_models"),
        do_ocr=False,              # the corpus is born-digital text, not scans
        do_table_structure=False,  # TableFormer is a separate, untested ablation.
        do_formula_enrichment=formula_enrichment,
    )
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.object_detection_engine_options import TransformersObjectDetectionEngineOptions
    pipeline_options.layout_options.engine_options = TransformersObjectDetectionEngineOptions(compile_model=False)
    pipeline_options.accelerator_options = AcceleratorOptions(
        device=device or "auto", num_threads=num_threads or 4,
        cuda_use_flash_attention2=False,
    )
    if formula_enrichment:
        from docling.datamodel.pipeline_options import CodeFormulaVlmOptions
        from docling.datamodel.vlm_engine_options import TransformersVlmEngineOptions
        formula_path = Path(__file__).parent / "docling_models/docling-project--CodeFormulaV2"
        if not (formula_path / "model.safetensors").is_file():
            raise FileNotFoundError("Missing offline formula model; run src/build.sh")
        pipeline_options.code_formula_options = CodeFormulaVlmOptions.from_preset("codeformulav2")
        pipeline_options.code_formula_options.model_spec.max_new_tokens = 1024
        pipeline_options.code_formula_options.engine_options = TransformersVlmEngineOptions(
            torch_dtype="float32" if device == "cpu" else "bfloat16", compile_model=False,
        )
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})


def _chunk_markdown(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    """Preserve section boundaries and atomic display formulas."""
    return section_chunks(text, chunk_size, overlap)


def _build_index(corpus_dir: str):
    """Parse, chunk, embed and index every PDF once per corpus/model pair."""
    converter = _docling_converter()
    embedder = SentenceTransformer(EMBED_MODEL_PATH, device="cpu")

    all_chunks = []
    sources = []
    pdfs = sorted(Path(corpus_dir).glob("*.pdf"))
    for pdf_path in pdfs:
        try:
            result = converter.convert(str(pdf_path))
            text = result.document.export_to_markdown()
            del result
        except Exception as e:
            # One bad PDF shouldn't take down the whole run.
            print(f"[rag] skipping {pdf_path.name}: {e}")
            continue
        document_chunks = _chunk_markdown(text)
        sources.extend(_chunk_sources(pdf_path.name, document_chunks))
        all_chunks.extend(document_chunks)

    del converter
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print(f"[rag] parsed {len(pdfs)} PDFs into {len(all_chunks)} chunks")
    if not all_chunks:
        return [], np.empty((0, 0), dtype=np.float32), embedder, None, []

    embeddings = embedder.encode(
        all_chunks, normalize_embeddings=True, show_progress_bar=False, batch_size=64,
    )
    tokenized_chunks = [_bm25_tokens(chunk) for chunk in all_chunks]
    # BM25 cannot initialize a corpus with no tokens (e.g. punctuation only).
    bm25 = BM25Okapi(tokenized_chunks, k1=1.2, b=0.75, epsilon=0.25) if any(tokenized_chunks) else None
    return all_chunks, np.asarray(embeddings, dtype=np.float32), embedder, bm25, sources


def _lexical_tokens(text: str) -> list[str]:
    """Use the same Unicode word tokenization for documents and queries."""
    return re.findall(r"\w+", text.casefold())


def _bm25_tokens(text):
    global _bm25_preprocessor
    if _bm25_preprocessor is None:
        _bm25_preprocessor = LexicalPreprocessor(stopwords=True, stemming=True)
    return _bm25_preprocessor(text)


def _chunk_sources(document, chunks):
    """Preserve section identity and content kind in all retrieval paths."""
    return chunk_sources(document, chunks)


def _hybrid_order(question, embeddings, embedder, bm25, kg_index=None, kg_weight=KG_RRF_WEIGHT, sources=None):
    """Fuse dense, lexical and optional entity-mention rankings of chunk IDs."""
    if len(embeddings) == 0:
        return []
    query_emb = embedder.encode([question], normalize_embeddings=True, show_progress_bar=False)[0]
    dense_order = np.argsort(-(embeddings @ query_emb), kind="stable")[:RETRIEVAL_TOP_K]
    rankings = [(dense_order, 1.0)]
    if bm25 is not None:
        lexical_scores = np.asarray(bm25.get_scores(_bm25_tokens(question)))
        lexical_order = np.argsort(-lexical_scores, kind="stable")
        # Zero-score chunks provide no lexical evidence for the question.
        rankings.append((lexical_order[lexical_scores[lexical_order] != 0][:RETRIEVAL_TOP_K], 1.0))

    if kg_index is not None and kg_weight > 0:
        rankings.append((kg_index.rank(question, top_k=RETRIEVAL_TOP_K), kg_weight))

    named = {str(i): ranking for i, (ranking, _) in enumerate(rankings)}
    weights = {str(i): weight for i, (_, weight) in enumerate(rankings)}
    order, scores = rrf_fuse(named, weights, RRF_K)
    if sources is not None:
        order, _ = penalize_order(order, scores, sources, question)
    return order


def _load(model_id: str, corpus_dir: str):
    kg_mode = os.environ.get("KG_MODE", "off")
    if kg_mode not in ("off", "mentions", "graph"):
        raise ValueError("KG_MODE must be 'off', 'mentions' or 'graph'")
    graph_config = GraphConfig.from_env() if kg_mode == "graph" else None
    cache_key = (model_id, str(Path(corpus_dir).resolve()), kg_mode, graph_config)
    if cache_key not in _cache:
        chunks, embeddings, embedder, bm25, sources = _build_index(corpus_dir)
        kg_index = None
        if kg_mode != "off" and KG_PATH.exists():
            # A present but corrupt artifact fails explicitly, rather than
            # silently switching the submitted experiment back to the baseline.
            kg_index = KGChunkIndex.from_directory(KG_PATH, chunks, mode=kg_mode, config=graph_config)
            print(f"[kg] mode={kg_mode}; indexed {len(kg_index.postings)} entities mentioned in corpus chunks")
        if model_id not in _model_cache:
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            model = AutoModelForCausalLM.from_pretrained(
                model_id, dtype=torch.bfloat16, device_map="cuda",
            )
            model.eval()
            _model_cache[model_id] = (tokenizer, model)
        tokenizer, model = _model_cache[model_id]
        _cache[cache_key] = (tokenizer, model, chunks, embeddings, embedder, bm25, kg_index, sources)
    return _cache[cache_key]


def _build_context(question, chunks, embeddings, embedder, tokenizer, bm25, max_tokens=MAX_CONTEXT_TOKENS, kg_index=None, sources=None):
    """Pack ranked evidence and source labels within the total context budget.

    If the first fragment is too long, truncate its text while retaining its
    source. Return no context if even the labels cannot fit.
    """
    order = _hybrid_order(question, embeddings, embedder, bm25, kg_index=kg_index, sources=sources)
    if sources is not None:
        order = continuity_order(order, sources)
    prefix = "Context extracted from a blind search over the corpus:\n\n"
    suffix = "\n\n---\n\n"
    selected = []
    for i in order:
        label = f"[Fragment {len(selected) + 1}]"
        if sources is not None:
            source = sources[i]
            label += f" [Source: {source['chunk_id']}]"
            if source.get("section"):
                label += f" [Section: {source['section']}]"
        def context_with(text):
            return prefix + "\n\n".join([*selected, f"{label}\n{text}"]) + suffix
        chunk = chunks[i]
        if len(tokenizer.encode(context_with(chunk))) > max_tokens:
            if not selected:
                # Keep source labels intact and truncate only evidence text.
                low, high = 0, len(chunk)
                while low < high:
                    mid = (low + high + 1) // 2
                    if len(tokenizer.encode(context_with(chunk[:mid]))) <= max_tokens:
                        low = mid
                    else:
                        high = mid - 1
                if low and len(tokenizer.encode(context_with(chunk[:low]))) <= max_tokens:
                    selected.append(f"{label}\n{chunk[:low]}")
            break
        selected.append(f"{label}\n{chunk}")

    if not selected:
        return ""
    return prefix + "\n\n".join(selected) + suffix


def answer(question: str, corpus_dir: str, model_id: str) -> str:
    tokenizer, model, chunks, embeddings, embedder, bm25, kg_index, sources = _load(model_id, corpus_dir)
    context = _build_context(question, chunks, embeddings, embedder, tokenizer, bm25, kg_index=kg_index, sources=sources)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(question, context)},
    ]
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True,
    ).to(model.device)

    with torch.no_grad():
        output = model.generate(
            **inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )
    input_len = inputs["input_ids"].shape[-1]
    return tokenizer.decode(output[0][input_len:], skip_special_tokens=True).strip()
