"""Validated settings shared by submission and local retrieval experiments."""

import json
import math
import os
from dataclasses import dataclass, fields
from pathlib import Path

if __package__:
    from .retrieval_utils import VARIANTS, variant_weights
else:
    from retrieval_utils import VARIANTS, variant_weights

ASSETS = Path(__file__).resolve().parent
MAX_NEW_TOKENS = 2048
MAX_CONTEXT_TOKENS = 10_000


@dataclass(frozen=True)
class PipelineConfig:
    variant: str = "hybrid"
    embed_model: Path = ASSETS / "embed_model"
    kg: Path = ASSETS / "kg"
    embedding_device: str = "auto"
    docling_device: str = "cpu"
    query_device: str = "cpu"
    llm_device: str = "cuda"
    threads: int = 4
    batch_size: int = 8
    chunk_size: int = 800
    chunk_overlap: int = 150
    top_k: int = 10
    candidate_depth: int = 100
    rrf_k: float = 60
    dense_weight: float = 1.0
    bm25_weight: float = 1.0
    kg_weight: float = 0.5
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    bm25_epsilon: float = 0.25
    bm25_stopwords: bool = True
    bm25_stemming: bool = True
    preserve_words: tuple[str, ...] = ()
    stopwords_file: Path | None = None
    formula_enrichment: bool = False
    continuity: bool = False
    penalize_metadata: bool = True
    reference_weight: float = 0.5
    front_matter_weight: float = 0.7
    neighbors_before: int = 1
    neighbors_after: int = 3
    small_section_chunks: int = 6
    max_context_tokens: int = MAX_CONTEXT_TOKENS
    max_new_tokens: int = MAX_NEW_TOKENS

    def __post_init__(self):
        if self.variant not in VARIANTS:
            raise ValueError(f"Unknown retrieval variant: {self.variant}")
        for name in ("embedding_device", "docling_device", "query_device", "llm_device"):
            if getattr(self, name) not in ("auto", "cpu", "cuda"):
                raise ValueError(f"{name} must be auto, cpu or cuda")
        for name in ("threads", "batch_size", "chunk_size", "top_k", "candidate_depth", "max_context_tokens", "max_new_tokens"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.chunk_overlap) is not int or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("chunk_overlap must be between zero and chunk_size - 1")
        for name in ("rrf_k", "dense_weight", "bm25_weight", "kg_weight", "bm25_epsilon"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (self.bm25_k1, self.bm25_b)):
            raise ValueError("BM25 k1 and b must be finite numbers")
        if self.bm25_k1 <= 0 or not 0 <= self.bm25_b <= 1:
            raise ValueError("BM25 requires k1 > 0 and 0 <= b <= 1")
        for name in ("formula_enrichment", "continuity", "penalize_metadata", "bm25_stopwords", "bm25_stemming"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if not isinstance(self.preserve_words, (tuple, list)) or not all(isinstance(w, str) for w in self.preserve_words):
            raise ValueError("preserve_words must contain strings")
        object.__setattr__(self, "preserve_words", tuple(self.preserve_words))
        for name in ("embed_model", "kg", "stopwords_file"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, Path(getattr(self, name)))
        if not any(self.weights.values()):
            raise ValueError("The selected variant has no active retrieval channels")
        self.evidence_config()  # Validate neighborhood sizes and penalty factors.

    @property
    def weights(self):
        return variant_weights(self.variant, self.dense_weight, self.bm25_weight, self.kg_weight)

    def uses(self, channel):
        return self.weights.get(channel, 0) > 0

    def evidence_config(self):
        if __package__:
            from .evidence import EvidenceConfig
        else:
            from evidence import EvidenceConfig
        return EvidenceConfig(reference_weight=self.reference_weight,
                              front_matter_weight=self.front_matter_weight,
                              neighbors_before=self.neighbors_before, neighbors_after=self.neighbors_after,
                              small_section_chunks=self.small_section_chunks, max_chunks=self.top_k)

    @classmethod
    def from_namespace(cls, args, **overrides):
        """CLI-only paths/output settings stay with the local runner."""
        values = {field.name: getattr(args, field.name) for field in fields(cls) if hasattr(args, field.name)}
        if "variant" not in values and getattr(args, "variants", None):
            values["variant"] = args.variants[0]
        return cls(**{**values, **overrides})


def load_config(path=None):
    """Submission JSON paths resolve beside the file; legacy KG_MODE still works."""
    path = Path(path or os.environ.get("RAG_CONFIG", ASSETS / "pipeline.json")).resolve()
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict) or set(values) - {f.name for f in fields(PipelineConfig)}:
        raise ValueError(f"Unknown configuration keys in {path}")
    for name in ("embed_model", "kg", "stopwords_file"):
        if values.get(name) is not None:
            values[name] = path.parent / values[name]
    if "KG_MODE" in os.environ:
        mode = os.environ["KG_MODE"]
        if mode not in ("off", "mentions", "graph"):
            raise ValueError("KG_MODE must be off, mentions or graph")
        variant = values.get("variant", "hybrid")
        if mode == "off":
            values["variant"] = {"mentions": "hybrid", "graph": "hybrid", "dense_mentions": "dense", "dense_graph": "dense"}.get(variant, variant)
        elif variant.startswith("dense"):
            values["variant"] = f"dense_{mode}"
        else:
            values["variant"] = mode
    return PipelineConfig(**values)
