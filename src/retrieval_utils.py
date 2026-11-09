"""Shared ranking operations for submission and local experiments."""

import math

VARIANTS = ("dense", "bm25", "hybrid", "mentions", "graph", "dense_mentions", "dense_graph")


def variant_weights(variant, dense_weight=1.0, bm25_weight=1.0, kg_weight=0.5):
    """A single definition of the channels used by submission and experiments."""
    channels = {"dense": {"dense": dense_weight}, "bm25": {"bm25": bm25_weight},
                "hybrid": {"dense": dense_weight, "bm25": bm25_weight},
                "mentions": {"dense": dense_weight, "bm25": bm25_weight, "kg_mentions": kg_weight},
                "graph": {"dense": dense_weight, "bm25": bm25_weight, "kg_graph": kg_weight},
                "dense_mentions": {"dense": dense_weight, "kg_mentions": kg_weight},
                "dense_graph": {"dense": dense_weight, "kg_graph": kg_weight}}
    if variant not in channels:
        raise ValueError(f"Unknown retrieval variant: {variant}")
    return channels[variant]


def rrf_fuse(rankings, weights, k=60):
    """Return chunk order and scores; absent/zero-weight channels contribute nothing."""
    if not math.isfinite(k) or k < 0:
        raise ValueError("RRF k must be finite and nonnegative")
    scores = {}
    for channel, ranking in rankings.items():
        weight = weights.get(channel, 0.0)
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"Invalid RRF weight: {channel}")
        if not weight:
            continue
        seen = set()
        for position, index in enumerate(ranking, 1):
            index = int(index)
            if index in seen:
                raise ValueError(f"Duplicate chunk in ranking: {channel}")
            seen.add(index)
            scores[index] = scores.get(index, 0.0) + weight / (k + position)
    return sorted(scores, key=lambda index: (-scores[index], index)), scores
