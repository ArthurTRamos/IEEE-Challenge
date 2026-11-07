"""Shared ranking operations for submission and local experiments."""

import math


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
