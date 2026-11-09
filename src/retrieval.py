"""Candidate ranking, RRF and evidence selection shared by both entry points."""

import numpy as np

if __package__:
    from .embedding import encode_queries
    from .evidence import penalize_order, continuity_order
    from .retrieval_utils import rrf_fuse
else:
    from embedding import encode_queries
    from evidence import penalize_order, continuity_order
    from retrieval_utils import rrf_fuse


def dense_ranking(scores, depth):
    return np.argsort(-np.asarray(scores), kind="stable")[:depth].tolist()


def lexical_ranking(scores, depth):
    scores = np.asarray(scores)
    order = np.argsort(-scores, kind="stable")
    return order[scores[order] != 0][:depth].tolist()


def select_evidence(order, scores, sources, question, config):
    evidence = config.evidence_config()
    if config.penalize_metadata and sources is not None:
        order, adjusted = penalize_order(order, scores, sources, question, evidence)
    else:
        adjusted = dict(scores)
    anchors = order[:config.top_k]
    if config.continuity and sources is not None:
        selected = continuity_order(order, sources, evidence)
    else:
        selected = anchors
    return selected, adjusted, set(anchors)


def rank_candidates(question, index, config):
    """Only execute channels enabled by the selected variant and nonzero weights."""
    if not index.chunks:
        return [], {}
    rankings = {}
    if config.uses("dense"):
        query = encode_queries(index.embedder, [question], normalize_embeddings=True, show_progress_bar=False)[0]
        rankings["dense"] = dense_ranking(index.embeddings @ query, config.candidate_depth)
    if config.uses("bm25") and index.bm25 is not None:
        rankings["bm25"] = lexical_ranking(index.bm25.get_scores(index.lexical(question)), config.candidate_depth)
    for channel in ("kg_mentions", "kg_graph"):
        if config.uses(channel) and index.kg_index is not None:
            rankings[channel] = index.kg_index.rank(question, top_k=config.candidate_depth)
    return rrf_fuse(rankings, config.weights, config.rrf_k)


def retrieve(question, index, config):
    order, scores = rank_candidates(question, index, config)
    return select_evidence(order, scores, index.sources, question, config)[0]
