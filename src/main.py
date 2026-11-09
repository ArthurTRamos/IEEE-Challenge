"""Official participant entry point: answer(question, corpus_dir, model_id).

Retrieval techniques and devices are configured in pipeline.json. Local
experiments use tools/run_retrieval.py and never load the answer model.
"""

from pathlib import Path

if __package__:
    from .settings import load_config
    from .indexing import build_index
    from .retrieval import retrieve
    from .context import build_context
    from .generation import load_model, generate_answer
    from .kg_retrieval import GraphConfig
else:
    from settings import load_config
    from indexing import build_index
    from retrieval import retrieve
    from context import build_context
    from generation import load_model, generate_answer
    from kg_retrieval import GraphConfig

_indices = {}


def get_index(corpus_dir, config):
    graph = GraphConfig.from_env() if config.uses("kg_graph") else None
    key = (str(Path(corpus_dir).resolve()), config, graph)
    if key not in _indices:
        _indices[key] = build_index(corpus_dir, config, graph)
    return _indices[key]


def answer(question: str, corpus_dir: str, model_id: str) -> str:
    config = load_config()
    # Index first, then release encoder VRAM before loading the answer model.
    index = get_index(corpus_dir, config)
    order = retrieve(question, index, config)
    tokenizer, model = load_model(model_id, config.llm_device)
    context = build_context(index.chunks, order, tokenizer, index.sources, config.max_context_tokens)
    return generate_answer(question, context, tokenizer, model, config.max_new_tokens)
