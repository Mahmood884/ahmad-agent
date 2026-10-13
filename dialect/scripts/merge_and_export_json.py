#!/usr/bin/env python3
"""
Merge Bahraini dialect sources → single enriched JSON.
دمج مصادر قاموس البحرية → ملف JSON واحد موحّد

Sources (by precedence):
  1. data/dictionary_enriched.yaml   (948 entries, usage already filled) — PRIMARY
  2. data/antigravity_entries.json   (secondary, fills gaps only) — OPTIONAL

ADAPTED FROM THE ORIGINAL PLAN (2026-10-13):
  The plan assumed a secondary "antigravity" source with ~600+ extra entries.
  That source does NOT exist on this machine (verified: no script, no JSON).
  This script keeps the loader ready for it — if the file ever appears, it
  merges automatically. Until then the merge is a clean single-source export.

Dedup key: term (normalized: strip tatweel/diacritics, unify alef/ya/ta-marbuta)

Output: data/bahraini_dictionary_unified.json
"""

import json
import re
import sys
from pathlib import Path

import yaml

# ── Normalization ──────────────────────────────────────────────────────────────
_AR_DIACRITICS = re.compile(r"[\u064B-\u0652\u0640]")
_ALEF_VARIANTS = re.compile(r"[إأآا]")
_YA_VARIANTS = re.compile(r"[ىي]")
_TA_MARBUTA = re.compile(r"ة$")


def normalize_term(term: str) -> str:
    """Unify orthographic variants for dedup purposes."""
    t = _AR_DIACRITICS.sub("", term.strip())
    t = _ALEF_VARIANTS.sub("ا", t)
    t = _YA_VARIANTS.sub("ي", t)
    t = _TA_MARBUTA.sub("ه", t)
    return t


# ── Source 1: enriched YAML (primary) ─────────────────────────────────────────
def load_enriched_yaml(path: Path) -> dict[str, dict]:
    """Return {normalized_term: entry_dict}."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = {}
    for e in data.get("entries", []):
        key = normalize_term(e["term"])
        if key not in out:  # first occurrence wins
            out[key] = {
                "term": e["term"],
                "meaning": e.get("meaning", ""),
                "examples": e.get("examples", []),
                "synonyms": e.get("synonyms", []),
                "dialect_region": e.get("dialect_region"),
                "origin": e.get("origin"),
                "notes": e.get("notes"),
                "usage": e.get("usage", {"tone": "neutral", "intent": "describe"}),
                "category": "عامية بحرينية",
                "source": "enriched_yaml",
            }
    return out


# ── Source 2: optional antigravity entries (secondary) ────────────────────────
def load_antigravity_entries(json_path: Path) -> dict[str, dict]:
    """Load an optional secondary source list as JSON."""
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    out = {}
    for e in raw:
        key = normalize_term(e["term"])
        if key in out:
            continue
        out[key] = {
            "term": e["term"],
            "meaning": e.get("meaning", ""),
            "examples": [],
            "synonyms": e.get("synonyms", []),
            "dialect_region": e.get("region"),
            "origin": e.get("original"),
            "notes": e.get("also"),
            "usage": analyze_usage_generic(e),
            "category": e.get("category", "عامية بحرينية"),
            "source": "secondary",
        }
    return out


# ── Usage analysis for secondary entries ──────────────────────────────────────
_AR = r"[\u0621-\u064A\u0640\u064B-\u0652]"


def kw_in(keyword: str, text: str) -> bool:
    """Arabic word-boundary matching (same rule as build_enriched_yaml.py)."""
    pattern = rf"(?<!{_AR}){re.escape(keyword)}(?!{_AR})"
    return re.search(pattern, text) is not None


GREETING = ["مرحبا", "هلا", "أهلا", "حباب", "السلام", "مساء", "صباح", "عساكم"]
QUESTION = ["لماذا", "ماذا", "شنو", "أيش", "ليش", "وش", "وين", "متى"]
INSULT = ["غبي", "مجنون", "كذاب", "بخيل", "وسخ", "حقير", "نمّام"]
CURSE = ["شيطان", "هلك", "دعاء", "نصبة"]
DISMISS = ["اسكت", "اذهب", "انطم", "ادلف", "انهب", "أخرس"]
AGGRESSIVE = ["ضرب", "طرد", "كسر", "ذبح", "طعن"]
PRAISE = ["ذكي", "وسيم", "كاشخ", "متزين", "جميل"]


def analyze_usage_generic(entry: dict) -> dict:
    """Minimal usage analysis for secondary-source entries."""
    text = f"{entry.get('term', '')} {entry.get('meaning', '')}"

    intent, tone, strength = "describe", "neutral", None

    if any(kw_in(k, text) for k in GREETING):
        intent, tone = "greeting", "friendly"
    elif any(kw_in(k, text) for k in QUESTION):
        intent = "question"
    elif any(kw_in(k, text) for k in CURSE):
        intent, strength = "curse", "medium"
    elif any(kw_in(k, text) for k in DISMISS):
        intent, tone, strength = "dismiss", "aggressive", "high"
    elif any(kw_in(k, text) for k in INSULT):
        intent, tone, strength = "insult", "negative", "medium"
    elif any(kw_in(k, text) for k in AGGRESSIVE):
        intent, tone, strength = "threat", "aggressive", "medium"
    elif any(kw_in(k, text) for k in PRAISE):
        intent, tone = "praise", "positive"

    usage = {"tone": tone, "intent": intent}
    if strength:
        usage["strength"] = strength
    return usage


# ── Merge & export ────────────────────────────────────────────────────────────
def merge(primary: dict, secondary: dict) -> dict:
    """Primary wins on term conflict; secondary fills gaps only."""
    merged = dict(primary)
    added = 0
    for key, entry in secondary.items():
        if key not in merged:
            merged[key] = entry
            added += 1
    print(f"[merge] primary: {len(primary)} entries")
    print(f"[merge] secondary: {len(secondary)} entries")
    print(f"[merge] added from secondary: {added}")
    print(f"[merge] total unique: {len(merged)}")
    return merged


def export_json(entries: dict, out_path: Path):
    """Export merged entries as a unified JSON document."""
    sorted_entries = sorted(entries.values(), key=lambda e: e["term"])

    for e in sorted_entries:
        e.pop("source", None)  # internal bookkeeping only

    output = {
        "metadata": {
            "name": "Bahraini Dialect Dictionary — Unified",
            "language": "Arabic (Bahraini dialect)",
            "description": "قاموس موحّد للهجة البحرينية مع تحليل usage كامل",
            "version": "2.0",
            "entry_count": len(sorted_entries),
            "sources": [
                "dictionary_enriched.yaml (948 entries, usage-filled)",
                "antigravity_entries.json (optional secondary — not present at build time)",
            ],
        },
        "entries": sorted_entries,
    }

    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[export] wrote {out_path} ({len(sorted_entries)} entries)")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    base = Path(__file__).resolve().parent.parent
    enriched_yaml = base / "data" / "dictionary_enriched.yaml"
    secondary_json = base / "data" / "antigravity_entries.json"
    out_path = base / "data" / "bahraini_dictionary_unified.json"

    if not enriched_yaml.exists():
        print(f"ERROR: {enriched_yaml} not found", file=sys.stderr)
        sys.exit(1)

    primary = load_enriched_yaml(enriched_yaml)
    print(f"[load] enriched_yaml: {len(primary)} entries")

    secondary = {}
    if secondary_json.exists():
        secondary = load_antigravity_entries(secondary_json)
        print(f"[load] secondary: {len(secondary)} entries")
    else:
        print("[load] antigravity_entries.json not found — skipping secondary source")

    merged = merge(primary, secondary)
    export_json(merged, out_path)


if __name__ == "__main__":
    main()
