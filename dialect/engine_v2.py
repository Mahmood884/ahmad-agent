#!/usr/bin/env python3
"""
engine_v2 — compatibility alias.

The canonical engine is engine.py (whole-word matching + full context
payload + greeting warmth, built from the v1 substring version via
build_engine_v2.py). This module re-exports it so importlib loaders that
target `engine_v2` keep working.

    from dialect.engine_v2 import DialectEngine   # == dialect.engine.DialectEngine
"""

from engine import DialectEngine, normalize_term, tokenize  # noqa: F401

__all__ = ["DialectEngine", "normalize_term", "tokenize"]
