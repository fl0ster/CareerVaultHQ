"""Mapping evaluation scores onto the display relevance scale."""

from __future__ import annotations


def relevance(probability: float, threshold: float) -> float:
    """Map a match probability onto [-1, 1]: ``threshold`` -> 0, 1 -> 1 and 0 -> -1, each
    side scaled linearly by its distance to the threshold."""
    if probability >= threshold:
        value = (probability - threshold) / (1 - threshold) if threshold < 1 else 0.0
    else:
        value = (probability - threshold) / threshold
    return max(-1.0, min(1.0, value))
