"""Backward-compatible re-export — renamed to arrange_features.py.

.. deprecated::
    This module is deprecated. Use ``arrange_features.ArrangeFeaturesAlgorithm``
    directly. Kept only for backward compatibility with user scripts that may
    import ``ResolveOverlapsAlgorithm``.
"""
from .arrange_features import ArrangeFeaturesAlgorithm as ResolveOverlapsAlgorithm

__all__ = ['ResolveOverlapsAlgorithm']
