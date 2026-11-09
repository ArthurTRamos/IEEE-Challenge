"""Consistent retrieval prompts for saved offline SentenceTransformer models."""


def retrieval_prefix(embedder, role):
    if role not in ("query", "document"):
        raise ValueError("Embedding role must be query or document")
    prompts = getattr(embedder, "prompts", {})
    if not isinstance(prompts, dict):
        return ""
    prefix = prompts.get(role, "")
    if not isinstance(prefix, str):
        raise ValueError(f"Invalid {role} embedding prompt")
    return prefix


def embedding_inputs(embedder, texts, role):
    """Texts actually tokenized, for truncation audits; never alter BM25 input."""
    prefix = retrieval_prefix(embedder, role)
    return [prefix + text for text in texts]


def _encode(embedder, texts, role, **kwargs):
    prefix = retrieval_prefix(embedder, role)
    # Explicitly bypass a model's default prompt for the other retrieval role.
    if prefix or isinstance(getattr(embedder, "default_prompt_name", None), str):
        kwargs["prompt"] = prefix
    return embedder.encode(texts, **kwargs)


def encode_queries(embedder, texts, **kwargs):
    return _encode(embedder, texts, "query", **kwargs)


def encode_documents(embedder, texts, **kwargs):
    return _encode(embedder, texts, "document", **kwargs)
