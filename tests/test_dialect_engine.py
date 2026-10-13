"""Regression tests for dialect/engine.py — whole-word matching.

Bug fixed: enrich_context used raw substring matching, so "شلونك" ("how are
you") matched the dictionary entry "لون" (color). Matching is now token-level.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("yaml")

_ENGINE_PATH = Path(__file__).resolve().parents[1] / "dialect" / "engine.py"
_spec = importlib.util.spec_from_file_location("dialect_engine", _ENGINE_PATH)
assert _spec is not None and _spec.loader is not None
engine_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_mod)


@pytest.fixture(scope="module")
def engine():
    return engine_mod.DialectEngine()


def test_substring_is_not_a_match(engine):
    # "لون" is a dictionary term; it must NOT match inside "شلونك"/"شلونكم"
    assert engine.lookup("لون") is not None
    assert engine.enrich_context("شلونك") == ""
    assert engine.enrich_context("شلونكم اليوم") == ""


def test_whole_word_still_matches(engine):
    assert "[لون]" in engine.enrich_context("لون")
    # "هلا والله" is now a CURATED phrase entry (warmth=medium) — the longest
    # phrase wins over the bare "هلا" token. Both are greetings; the phrase
    # is the correct hit.
    assert "[هلا والله]" in engine.enrich_context("هلا والله")
    assert "[هلا]" in engine.enrich_context("هلا والله بيك") or "[هلا]" in engine.enrich_context("هلا")


def test_clitics_resolve_to_stem(engine):
    # ب + لون  /  ال + دكّان (diacritics normalized)
    assert "[لون]" in engine.enrich_context("بلون احمر")
    assert "[دكّان]" in engine.enrich_context("الدكان قريب")


def test_multiword_term_matches_as_phrase(engine):
    assert "[باب البحرين]" in engine.enrich_context("عطني باب البحرين")
    # a single word of the phrase alone is not the phrase
    assert "[باب البحرين]" not in engine.enrich_context("باب")


def test_every_term_resolves_to_itself(engine):
    # A term whose surface carries a pronunciation gloss — "مطعم (بضم الميم)" —
    # is indexed under its bare key ("مطعم"), so scanning its own (gloss-stripped)
    # tokens returns the bare entry when both exist. That is the intended
    # canonicalization: the user typing "مطعم" gets the plain entry.
    # A declared SYNONYM ("الدهليز" of "دهريز") resolves to its canonical entry.
    # Synonym comparison is NORMALIZED: the stored synonym may be an
    # orthographic variant ("ام طرة" vs "أم طرة", "قطاوه" vs "قطاوة").
    missed = []
    for term in engine._entries:
        cleaned = engine_mod._PAREN_RE.sub(" ", term).strip()
        if not cleaned:
            continue
        toks = engine_mod.tokenize(cleaned)
        if not toks:
            continue
        hits = engine._scan(toks, engine._term_phrases, engine._term_lengths, True)
        if not hits:
            missed.append(term)
            continue
        hit_term = hits[0]["term"]
        bare = engine_mod._PAREN_RE.sub("", term).strip()
        if hit_term == term or hit_term == bare:
            continue
        # is `term` a declared synonym of the hit? (normalized both sides)
        syn_norm = {engine_mod.normalize_term(s) for s in (hits[0].get("synonyms") or [])}
        if engine_mod.normalize_term(term) in syn_norm or engine_mod.normalize_term(bare) in syn_norm:
            continue
        missed.append(term)
    assert missed == []


def test_concept_label_matches_whole_word_only(engine):
    assert "AHMAD.CONCEPT.AHNA" in engine.enrich_context("احنا نشتغل")
    assert "AHMAD.CONCEPT.AHNA" not in engine.enrich_context("واحنا")  # no clitic on concepts


def test_max_terms_and_empty(engine):
    assert engine.enrich_context("hello world") == ""
    ctx = engine.enrich_context("هلا لون باب البحرين", max_terms=1)
    assert sum(1 for ln in ctx.splitlines() if ln.startswith("- [")) == 1
