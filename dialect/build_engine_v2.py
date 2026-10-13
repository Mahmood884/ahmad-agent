#!/usr/bin/env python3
"""
Build engine_v2.py from engine.py with two targeted transforms.

    python3 build_engine_v2.py

Transforms:
  1. enrich_context matching: whole-word + phrase + clitic-strip matching
     (already present in engine.py since the wordmatch patch — this script
     asserts it and fails loudly if engine.py drifted).
  2. enrich_context payload: inject notes / examples / synonyms / origin /
     region into the context block, and alert on rejected_terms (all their
     spellings: عزوز / زيزو / غزيزو).

The build is a REGENERATION, not an in-place edit: engine.py stays the
single source of truth; engine_v2.py is its enriched descendant. If
engine.py changes, re-run this script.
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Source of truth for the transform: the pre-wordmatch engine (v1, substring
# matching). Kept as engine_v1_substring.py.bak after the 2026-10-13 review
# round promoted the v2 output to engine.py. If the .bak is absent, fall back
# to engine.py (which must then still contain the pre-transform markers).
ENGINE = HERE / "engine_v1_substring.py.bak"
if not ENGINE.exists():
    ENGINE = HERE / "engine.py"
OUT = HERE / "engine_v2.py"

REQUIRED_MARKERS = [
    "def tokenize(",
    "def _phrase_key(",
    "def _clitic_stems(",
    "def _scan(",
]


def build() -> str:
    src = ENGINE.read_text(encoding="utf-8")

    for marker in REQUIRED_MARKERS:
        if marker not in src:
            raise SystemExit(
                f"engine.py is missing {marker!r} — the wordmatch patch is not applied. "
                f"Apply dialect-engine-wordmatch.patch first, then re-run this build."
            )

    # ── Transform: enrich_context payload ─────────────────────────────────────
    # Replace the dialect-terms loop body to include notes/examples/synonyms/
    # origin/region, and add a rejected-terms alert before the concept scan.

    old_block = '''        # dialect terms
        for entry in self._scan(tokens, self._term_phrases, self._term_lengths, True):
            if len(found) >= max_terms:
                break
            term = entry.get("term", "")
            if term in seen:
                continue
            u = entry.get("usage", {})
            found.append(
                f"- [{term}] {entry.get('meaning','')} "
                f"(نبرة الكلمة: {u.get('lexical_tone','?')}، "
                f"نوعها: {u.get('lexical_class','?')})"
            )
            seen.add(term)
'''

    new_block = '''        # rejected-terms alert (all spellings, incl. عزوز / زيزو / غزيزو)
        rejected_hit = False
        for form in self._rejected_forms:
            form_key = _phrase_key(form)
            if not form_key:
                continue
            if form_key in self._term_phrases:
                # single-word form: token/phrase match
                if self._scan(tokens, {form_key: {"term": form}}, [len(form_key)], True):
                    found.append(f"⚠️ مصطلحات مرفوضة في الرسالة: {form}")
                    rejected_hit = True
                    break
            else:
                # multi-word form: phrase scan
                if self._scan(tokens, {form_key: {"term": form}}, [len(form_key)], False):
                    found.append(f"⚠️ مصطلحات مرفوضة في الرسالة: {form}")
                    rejected_hit = True
                    break

        # dialect terms — with notes / examples / synonyms / origin / region
        for entry in self._scan(tokens, self._term_phrases, self._term_lengths, True):
            if len(found) >= max_terms:
                break
            term = entry.get("term", "")
            if term in seen:
                continue
            u = entry.get("usage", {})
            line = (
                f"- [{term}] {entry.get('meaning','')} "
                f"(نبرة الكلمة: {u.get('lexical_tone','?')}، "
                f"نوعها: {u.get('lexical_class','?')}"
            )
            extras = []
            if entry.get("notes"):
                extras.append(f"ملاحظة: {entry['notes']}")
            if entry.get("examples"):
                extras.append("مثال: " + " / ".join(entry["examples"][:2]))
            if entry.get("synonyms"):
                extras.append("مرادفات: " + "، ".join(entry["synonyms"][:4]))
            if entry.get("origin"):
                extras.append(f"الأصل: {entry['origin']}")
            if entry.get("dialect_region"):
                extras.append(f"المنطقة: {entry['dialect_region']}")
            if extras:
                line += " — " + " · ".join(extras)
            line += ")"
            found.append(line)
            seen.add(term)
'''

    if old_block not in src:
        raise SystemExit(
            "enrich_context block not found verbatim in engine.py — engine.py drifted "
            "from the expected shape. Refusing to build. Diff manually."
        )
    src = src.replace(old_block, new_block, 1)

    # ── Transform: rejected_forms index ───────────────────────────────────────
    # ontology rejected_terms carry forms like "عزوز / زيزو / غزيزو" in one
    # string; split them into individual forms for token matching.
    old_load = '''        for r in onto.get("rejected_terms", []):
            self._rejected.add(r.get("term", ""))
'''
    new_load = '''        for r in onto.get("rejected_terms", []):
            raw_term = r.get("term", "")
            self._rejected.add(raw_term)
            # split "عزوز / زيزو / غزيزو" into individual forms
            for form in re.split(r"\\s*/\\s*", raw_term):
                form = form.strip()
                if form:
                    self._rejected_forms.add(normalize_term(form))
'''
    if old_load not in src:
        raise SystemExit("rejected_terms loader not found verbatim — engine.py drifted.")
    src = src.replace(old_load, new_load, 1)

    # add the _rejected_forms attribute next to _rejected
    old_attr = '''        self._rejected: set[str] = set()
'''
    new_attr = '''        self._rejected: set[str] = set()
        self._rejected_forms: set[str] = set()
'''
    if old_attr not in src:
        raise SystemExit("_rejected attribute declaration not found — engine.py drifted.")
    src = src.replace(old_attr, new_attr, 1)

    # ── Transform: bare-term-wins on phrase-key collision ─────────────────────
    # "مطعم (بضم الميم)" and "مطعم" share the key ('مطعم',) after paren
    # stripping; whichever appears first would win under setdefault. The plain
    # form must win so lookup("مطعم") returns "مطعم".
    old_index = '''            key = _phrase_key(term)
            if key:
                self._term_phrases.setdefault(key, e)
'''
    new_index = '''            key = _phrase_key(term)
            if key:
                # prefer the bare term over a parenthesized variant:
                # "مطعم (بضم الميم)" and "مطعم" share the key ('مطعم',) —
                # the plain form wins so lookup("مطعم") returns "مطعم".
                existing = self._term_phrases.get(key)
                if existing is None or ("(" in existing.get("term", "") and "(" not in term):
                    self._term_phrases[key] = e
'''
    if old_index not in src:
        raise SystemExit("_term_phrases indexer not found verbatim — engine.py drifted.")
    src = src.replace(old_index, new_index, 1)

    # docstring update
    src = src.replace(
        '"""Runtime access layer for the dialect dictionary + ontology."""',
        '"""Runtime access layer v2 — whole-word matching + full context payload."""',
        1,
    )

    return src


def main():
    result = build()
    OUT.write_text(result, encoding="utf-8")
    print(f"✅ wrote {OUT} ({len(result.splitlines())} lines)")
    print("   transforms: whole-word/phrase/clitic matching (inherited) +")
    print("   notes/examples/synonyms/origin/region injection + rejected-terms alert")


if __name__ == "__main__":
    main()
