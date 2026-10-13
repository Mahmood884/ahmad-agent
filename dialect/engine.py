#!/usr/bin/env python3
"""
Dialect Engine — runtime loader connecting the dictionary and ontology to
the agent's reasoning path.

محرك اللهجة — يحمّل القاموس الموحّد + سجل المفاهيم، ويعطي:
  - lookup(term)       → مدخل القاموس (مع تطبيع إملائي)
  - concept(id)        → مفهوم من الـ ontology
  - aliases_of(term)   → المرادفات + الألقاب المرتبطة
  - enrich_context(msg) → نص سياقي جاهز للحقن في system prompt
  - resolve_term(word) → term ↔ concept mapping للمصطلحات الخاصة

This closes the wiring gap identified in the 2026-10-13 review: the
dictionary and ontology existed as artifacts but nothing loaded them into
the inference path.

Usage:
    from dialect.engine import DialectEngine
    engine = DialectEngine()                     # auto-discovers paths
    ctx = engine.enrich_context("عطني أبشار")    # context block for prompt
    entry = engine.lookup("أبشار")               # single-entry lookup
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

# ── Arabic normalization (same rules as the merge script) ─────────────────────
_AR_DIACRITICS = re.compile(r"[\u064B-\u0652\u0640]")
_ALEF_VARIANTS = re.compile(r"[إأآا]")
_YA_VARIANTS = re.compile(r"[ىي]")


def normalize_term(term: str) -> str:
    t = _AR_DIACRITICS.sub("", term.strip())
    t = _ALEF_VARIANTS.sub("ا", t)
    t = _YA_VARIANTS.sub("ي", t)
    t = re.sub(r"ة$", "ه", t)
    return t


class DialectEngine:
    """Runtime access layer for the dialect dictionary + ontology."""

    def __init__(
        self,
        dictionary_path: Path | str | None = None,
        ontology_path: Path | str | None = None,
    ) -> None:
        base = Path(__file__).resolve().parent
        self._dict_path = Path(dictionary_path) if dictionary_path else base / "data" / "bahraini_dictionary_unified.json"
        self._onto_path = Path(ontology_path) if ontology_path else base / "ontology.yaml"

        self._entries: dict[str, dict] = {}
        self._norm_index: dict[str, dict] = {}
        self._synonym_index: dict[str, dict] = {}
        self._concepts: dict[str, dict] = {}
        self._alias_index: dict[str, dict] = {}
        self._rejected: set[str] = set()

        self._load()

    # ── Loading ───────────────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self._dict_path.exists():
            raise FileNotFoundError(f"dictionary not found: {self._dict_path}")
        if not self._onto_path.exists():
            raise FileNotFoundError(f"ontology not found: {self._onto_path}")

        data = json.loads(self._dict_path.read_text(encoding="utf-8"))
        for e in data.get("entries", []):
            term = e.get("term", "")
            if not term:
                continue
            self._entries[term] = e
            self._norm_index[normalize_term(term)] = e
            for syn in e.get("synonyms") or []:
                self._synonym_index.setdefault(syn, e)

        onto = yaml.safe_load(self._onto_path.read_text(encoding="utf-8"))
        for c in onto.get("concepts", []):
            cid = c.get("concept_id", "")
            if cid:
                self._concepts[cid] = c
            for alias in c.get("aliases") or []:
                self._alias_index[normalize_term(alias)] = c
        for r in onto.get("rejected_terms", []):
            self._rejected.add(r.get("term", ""))

    # ── Dictionary lookups ────────────────────────────────────────────────────
    def lookup(self, term: str) -> dict | None:
        """Exact, then normalized, then synonym-index lookup."""
        hit = self._entries.get(term)
        if hit:
            return hit
        return self._norm_index.get(normalize_term(term))

    def lookup_synonym(self, word: str) -> dict | None:
        return self._synonym_index.get(word)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    # ── Ontology lookups ──────────────────────────────────────────────────────
    def concept(self, concept_id: str) -> dict | None:
        return self._concepts.get(concept_id)

    def resolve_alias(self, word: str) -> dict | None:
        """Map a surface word to its project concept (normalized match)."""
        return self._alias_index.get(normalize_term(word))

    @property
    def concept_count(self) -> int:
        return len(self._concepts)

    def is_rejected_term(self, word: str) -> bool:
        return word in self._rejected

    # ── Context injection ─────────────────────────────────────────────────────
    def enrich_context(self, user_message: str, max_terms: int = 5) -> str:
        """Build a context block for the system prompt from a user message.

        Scans the message for known dialect terms AND project-concept
        aliases. Returns an Arabic block describing what was found —
        lexical info only (never speaker intent, which stays
        context-dependent).
        """
        found: list[str] = []
        seen: set[str] = set()

        # dialect terms
        for term, entry in self._entries.items():
            if len(found) >= max_terms:
                break
            if term in user_message and term not in seen:
                u = entry.get("usage", {})
                found.append(
                    f"- [{term}] {entry.get('meaning','')} "
                    f"(نبرة الكلمة: {u.get('lexical_tone','?')}، "
                    f"نوعها: {u.get('lexical_class','?')})"
                )
                seen.add(term)

        # project concept aliases
        for alias_norm, concept in self._alias_index.items():
            if len(found) >= max_terms:
                break
            label = concept.get("preferred_label", "")
            if label in user_message and label not in seen:
                found.append(
                    f"- [{concept.get('concept_id','')}] "
                    f"{label}: {concept.get('definition','')[:80]}"
                )
                seen.add(label)

        if not found:
            return ""
        return "مصطلحات مألوفة في هذه الرسالة (معانيها كما هي في المشروع):\n" + "\n".join(found)

    # ── Introspection (for tests / CLI) ───────────────────────────────────────
    def stats(self) -> dict:
        from collections import Counter

        tones = Counter(e["usage"].get("lexical_tone") for e in self._entries.values())
        classes = Counter(e["usage"].get("lexical_class") for e in self._entries.values())
        origins = Counter(
            e["usage"].get("origin_type") for e in self._entries.values() if e["usage"].get("origin_type")
        )
        return {
            "entries": len(self._entries),
            "synonyms_indexed": len(self._synonym_index),
            "concepts": len(self._concepts),
            "rejected_terms": len(self._rejected),
            "lexical_tone": dict(tones),
            "lexical_class": dict(classes),
            "origin_type": dict(origins),
        }


# ── CLI smoke test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    engine = DialectEngine()
    s = engine.stats()
    print(f"DialectEngine loaded: {s['entries']} entries · {s['concepts']} concepts · {s['rejected_terms']} rejected terms")
    print(f"  lexical_tone:  {s['lexical_tone']}")
    print(f"  lexical_class: {s['lexical_class']}")
    print(f"  origin_type:   {s['origin_type']}")

    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
        print(f"\n── message: {msg}")
        ctx = engine.enrich_context(msg)
        print(f"── context block:\n{ctx if ctx else '  (no known terms)'}")

        # per-word lookups
        for word in msg.split():
            hit = engine.lookup(word) or engine.lookup_synonym(word)
            if hit:
                u = hit["usage"]
                print(f"  └ {word} → {hit['meaning']} [{u.get('lexical_tone')}/{u.get('lexical_class')}]")
            concept = engine.resolve_alias(word)
            if concept:
                print(f"  └ {word} → concept {concept['concept_id']}: {concept.get('definition','')[:60]}")
