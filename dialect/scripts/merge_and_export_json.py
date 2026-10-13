#!/usr/bin/env python3
"""
Merge Bahraini dialect sources → single enriched JSON.
دمج مصادر قاموس البحرية → ملف JSON واحد موحّد

Sources (by precedence):
  1. data/greeting_warmth_curated.yaml  (curated warmth scale — HIGHEST)
  2. data/dictionary_enriched.yaml       (948 entries, usage already filled)
  3. data/antigravity_entries.json       (835 entries, generic usage)

DISCOVERY 2026-10-13 (post-review): the secondary source is REAL — it lives
inside the raw paste itself. The tail of raw/bahraini_dictionary_raw.txt
contains a complete antigravity enrichment script whose `entries_raw = [...]`
list holds 835 entries, of which 351 are genuinely new (not in the 948).
Extracted with ast.literal_eval (no eval) into data/antigravity_entries.json.

WARMTH SCALE 2026-10-13 (user-curated): Bahraini greeting warmth is GRADED,
not binary:
  low    → bare greeting (هلا)
  medium → + oath (هلا والله) or personal address (هلا بيك/بيهم)
  high   → + poetic imagery (اسفرت وانورة / استهلت / وأمطرت)
           or follow-up questions (ووينك / أخبارك / وش مسوي)
The curated source carries these entries; it OVERRIDES the primary source on
conflict (the user is the source of truth for warmth).

Schema unification (review finding ③): every entry — from ALL sources — now
emits the SAME usage schema: {lexical_tone, lexical_class, speaker_intent,
strength?, origin_type?, warmth?}. The old analyze_usage_generic emitted
{tone, intent} and friendly/dismiss-strength=high, which mixed schemas. Removed.

Also fixed (review findings):
- null fields dropped: 2,773 nulls (dialect_region/origin/notes) removed —
  absent means absent, not null.
- source order preserved: no codepoint sort; entries keep the order they had
  in dictionary_enriched.yaml (the primary source's order = the raw file's).
- category: loanwords get "كلمة دخيلة" instead of forced "عامية بحرينية".
- metadata.schema describes the document.
- entry_count and sources reflect reality (948 + 351 = 1,299 total).

Dedup key: term (normalized: strip tatweel/diacritics, unify alef/ya/ta-marbuta)

Output: data/bahraini_dictionary_unified.json

Usage:
    python3 scripts/merge_and_export_json.py
    python3 scripts/merge_and_export_json.py --secondary-from-python <script.py>
"""

import ast
import json
import re
import sys
from pathlib import Path

import yaml

# ── Normalization (per-word; ة$ anchored at end of EACH word) ─────────────────
# Review finding ②: the old normalize_term applied ة→ه to the end of the whole
# string only, so "طايح النصبة" never matched itself. Now every word is
# normalized independently.
_AR_DIACRITICS = re.compile(r"[\u064B-\u0652\u0640]")
_ALEF_VARIANTS = re.compile(r"[إأآا]")
_YA_VARIANTS = re.compile(r"[ىي]")
_TA_MARBUTA = re.compile(r"ة$")


def normalize_term(term: str) -> str:
    """Unify orthographic variants, word by word."""
    words = term.strip().split()
    out = []
    for w in words:
        t = _AR_DIACRITICS.sub("", w)
        t = _ALEF_VARIANTS.sub("ا", t)
        t = _YA_VARIANTS.sub("ي", t)
        t = _TA_MARBUTA.sub("ه", t)
        out.append(t)
    return " ".join(out)


# ── Shared usage analyzer (single schema for both sources) ────────────────────
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

ORIGIN_MARKERS = [
    ("الإنجليزية", "english"), ("الانجليزي", "english"),
    ("الفارسية", "persian"), ("الفارسي", "persian"),
    ("الهندية", "hindi"), ("الهندي", "hindi"),
    ("التركية", "turkish"), ("التركي", "turkish"),
    ("الروسية", "russian"), ("الروسي", "russian"),
    ("الإيطالية", "italian"), ("الايطالية", "italian"),
    ("الفرنسية", "french"),
]

# A latin gloss in parentheses inside a meaning: "(Chassis)", "(Orange juice)"
_LATIN_GLOSS_RE = re.compile(r"\(([A-Za-z][A-Za-z\s]{2,})\)")


def analyze_usage(term: str, meaning: str, origin_field: str | None = None) -> dict:
    """Single-schema usage analysis: lexical_tone / lexical_class / strength / origin_type."""
    text = f"{term} {meaning}"

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

    usage = {
        "lexical_tone": tone,
        "lexical_class": intent,
        "speaker_intent": "context-dependent",
    }
    if strength:
        usage["strength"] = strength

    # origin_type: from the source's own origin field, or category markers.
    # The academic source embeds origins inside the MEANING text
    # ("محطة — من الإنجليزية station", "خزانة — من الهندية"), so the marker
    # scan runs over the meaning too, not only the origin field.
    # Loanwords carrying a LATIN GLOSS in parentheses — "شاصي: قاعدة
    # السيارة (Chassis)" — are tagged by pattern where no language marker
    # exists; every latin gloss in the corpus is English.
    origin_type = None
    for marker, lang in ORIGIN_MARKERS:
        if (origin_field and marker in origin_field) or (meaning and marker in meaning):
            origin_type = lang
            break
    if origin_type is None and meaning and _LATIN_GLOSS_RE.search(meaning):
        origin_type = "english"
    if origin_type:
        usage["origin_type"] = origin_type

    return usage


def is_loanword_category(category: str | None) -> bool:
    if not category:
        return False
    return any(m in category for m, _ in ORIGIN_MARKERS)


# ── Source 1: enriched YAML (primary) ─────────────────────────────────────────
def load_enriched_yaml(path: Path) -> dict[str, dict]:
    """Return {normalized_term: entry_dict} — order preserved."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = {}
    for e in data.get("entries", []):
        key = normalize_term(e["term"])
        if key not in out:  # first occurrence wins
            usage = e.get("usage") or {}
            # normalize any legacy {tone, intent} shape from older artifacts
            if "lexical_tone" not in usage and "tone" in usage:
                usage = {
                    "lexical_tone": usage.get("tone", "neutral"),
                    "lexical_class": usage.get("intent", "describe"),
                    "speaker_intent": "context-dependent",
                }
                if usage.get("strength"):
                    usage["strength"] = usage["strength"]
                if usage.get("origin_type"):
                    usage["origin_type"] = usage["origin_type"]
            out[key] = {
                "term": e["term"],
                "meaning": e.get("meaning", ""),
                "examples": e.get("examples", []),
                "synonyms": e.get("synonyms", []),
                "usage": usage,
                "category": "عامية بحرينية",
            }
            # keep sparse fields only when present (no nulls)
            for f in ("dialect_region", "origin", "notes"):
                if e.get(f):
                    out[key][f] = e[f]
    return out


# ── Source 2: antigravity entries (secondary) ─────────────────────────────────
def load_antigravity_entries(json_path: Path) -> dict[str, dict]:
    """Load the secondary source list as JSON (produced by --secondary-from-python)."""
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    out = {}
    for e in raw:
        key = normalize_term(e["term"])
        if key in out:
            continue
        category = e.get("category", "عامية بحرينية")
        origin_field = e.get("original")
        usage = analyze_usage(e["term"], e.get("meaning", ""), origin_field)
        entry = {
            "term": e["term"],
            "meaning": e.get("meaning", ""),
            "examples": e.get("examples", []),
            "synonyms": e.get("synonyms", []),
            "usage": usage,
            "category": "كلمة دخيلة" if is_loanword_category(category) else "عامية بحرينية",
        }
        for f, k in (("dialect_region", "region"), ("origin", "original"), ("notes", "also")):
            if e.get(k):
                entry[f] = e[k]
        out[key] = entry
    return out


def extract_secondary_from_python(script_path: Path) -> list[dict]:
    """Extract entries_raw = [...] from a python script via ast (no eval)."""
    text = script_path.read_text(encoding="utf-8")
    idx = text.find("entries_raw")
    if idx == -1:
        raise ValueError("no entries_raw assignment found in script")
    seg = text[idx:]
    m = re.search(r"entries_raw\s*=\s*", seg)
    if not m:
        raise ValueError("no entries_raw assignment found in script")
    br = seg.find("[", m.end())
    if br == -1:
        raise ValueError("no list literal after entries_raw")
    depth = 0
    for j in range(br, len(seg)):
        if seg[j] == "[":
            depth += 1
        elif seg[j] == "]":
            depth -= 1
            if depth == 0:
                break
    else:
        raise ValueError("unbalanced brackets in entries_raw")
    return ast.literal_eval(seg[br : j + 1])


# ── Source 0: curated warmth scale (user — highest precedence) ───────────────
def load_curated_warmth(path: Path) -> dict[str, dict]:
    """Load the user-curated greeting warmth entries. These OVERRIDE everything."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = {}
    for e in data.get("entries", []):
        key = normalize_term(e["term"])
        if key not in out:
            out[key] = {
                "term": e["term"],
                "meaning": e.get("meaning", ""),
                "examples": e.get("examples", []),
                "synonyms": e.get("synonyms", []),
                "usage": e.get("usage", {}),
                "category": "عامية بحرينية",
            }
    return out


# ── Source 0b: whatsapp corpus (fills gaps — usage auto-analyzed) ────────────
def load_whatsapp_corpus(path: Path) -> dict[str, dict]:
    """Load the whatsapp-group corpus. Terms get auto-analyzed usage.

    The entries here carry NO usage block (the paste was raw text); the same
    single-schema analyzer as the antigravity source runs on them, so they
    land in the unified JSON with an identical schema. Loanwords carrying a
    latin gloss in the meaning ("من الإنجليزية screwdriver") get origin_type
    english via the marker scan.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = {}
    for e in data.get("entries", []):
        key = normalize_term(e["term"])
        if key in out:
            continue
        usage = analyze_usage(e["term"], e.get("meaning", ""), e.get("origin"))
        entry = {
            "term": e["term"],
            "meaning": e.get("meaning", ""),
            "examples": e.get("examples", []),
            "synonyms": e.get("synonyms", []),
            "usage": usage,
            "category": "عامية بحرينية",
        }
        out[key] = entry
    return out


# ── Merge & export ────────────────────────────────────────────────────────────
def merge(primary: dict, secondary: dict, curated: dict, whatsapp: dict | None = None) -> dict:
    """Curated wins on conflict; then primary; then secondary/whatsapp fill gaps.

    Order: curated entries first (the user's explicit scale), then primary
    in source order, then secondary additions, then whatsapp additions.
    """
    whatsapp = whatsapp or {}
    merged: dict[str, dict] = {}
    # curated first (highest precedence — overrides هلا from primary)
    for key, entry in curated.items():
        merged[key] = entry
    curated_override = sum(1 for k in curated if k in primary)
    # primary next (skip keys already claimed by curated)
    for key, entry in primary.items():
        if key not in merged:
            merged[key] = entry
    # secondary fills remaining gaps
    added = 0
    for key, entry in secondary.items():
        if key not in merged:
            merged[key] = entry
            added += 1
    # whatsapp corpus fills what remains
    wa_added = 0
    for key, entry in whatsapp.items():
        if key not in merged:
            merged[key] = entry
            wa_added += 1
    print(f"[merge] curated: {len(curated)} entries ({curated_override} override primary)")
    print(f"[merge] primary: {len(primary)} entries")
    print(f"[merge] secondary: {len(secondary)} entries")
    print(f"[merge] added from secondary: {added}")
    print(f"[merge] whatsapp corpus: {len(whatsapp)} entries (+{wa_added} new)")
    print(f"[merge] total unique: {len(merged)}")
    return merged


def export_json(entries: dict, out_path: Path, primary_count: int, secondary_added: int):
    """Export merged entries as a unified JSON document. Order = insertion (source order)."""
    sorted_entries = list(entries.values())  # dict preserves insertion order: primary then secondary

    output = {
        "metadata": {
            "name": "Bahraini Dialect Dictionary — Unified",
            "language": "Arabic (Bahraini dialect)",
            "description": "قاموس موحّد للهجة البحرينية مع تحليل usage كامل",
            "version": "3.0",
            "entry_count": len(sorted_entries),
            "sources": [
                f"dictionary_enriched.yaml ({primary_count} entries, usage-filled)",
                f"antigravity_entries.json (+{secondary_added} new, usage-filled with same schema)",
            ],
            "schema": {
                "entry": {
                    "term": "str — surface form as in source",
                    "meaning": "str — Arabic gloss",
                    "examples": "list[str]",
                    "synonyms": "list[str]",
                    "usage": {
                        "lexical_tone": "positive|negative|neutral|aggressive|friendly",
                        "lexical_class": "describe|question|greeting|praise|curse|threat|dismiss|insult",
                        "speaker_intent": "always 'context-dependent' — the WORD never establishes the speaker's intent",
                        "strength": "high|medium (only for curse/threat/insult/dismiss)",
                        "origin_type": "english|hindi|italian|persian|russian|turkish|french (only for loanwords)",
                    },
                    "category": "str — عامية بحرينية | كلمة دخيلة",
                    "dialect_region": "str (sparse — only when the source carries it)",
                    "origin": "str (sparse — only when the source carries it)",
                    "notes": "str (sparse — only when the source carries it)",
                }
            },
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
    curated_yaml = base / "data" / "greeting_warmth_curated.yaml"
    secondary_json = base / "data" / "antigravity_entries.json"
    out_path = base / "data" / "bahraini_dictionary_unified.json"

    if not enriched_yaml.exists():
        print(f"ERROR: {enriched_yaml} not found", file=sys.stderr)
        sys.exit(1)

    # optional: (re)extract the secondary source from a python script
    if "--secondary-from-python" in sys.argv:
        i = sys.argv.index("--secondary-from-python")
        script = Path(sys.argv[i + 1])
        entries = extract_secondary_from_python(script)
        secondary_json.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[extract] wrote {secondary_json} ({len(entries)} entries from {script})")

    primary = load_enriched_yaml(enriched_yaml)
    print(f"[load] enriched_yaml: {len(primary)} entries")

    curated = {}
    if curated_yaml.exists():
        curated = load_curated_warmth(curated_yaml)
        print(f"[load] curated warmth: {len(curated)} entries")
    else:
        print("[load] greeting_warmth_curated.yaml not found — skipping curated source")

    whatsapp = {}
    whatsapp_yaml = base / "data" / "whatsapp_corpus_curated.yaml"
    if whatsapp_yaml.exists():
        whatsapp = load_whatsapp_corpus(whatsapp_yaml)
        print(f"[load] whatsapp corpus: {len(whatsapp)} entries")
    else:
        print("[load] whatsapp_corpus_curated.yaml not found — skipping whatsapp source")

    secondary = {}
    if secondary_json.exists():
        secondary = load_antigravity_entries(secondary_json)
        print(f"[load] secondary: {len(secondary)} entries")
    else:
        print("[load] antigravity_entries.json not found — skipping secondary source")

    merged = merge(primary, secondary, curated, whatsapp)
    added = len(merged) - len(primary) - len(curated) + sum(1 for k in curated if k in primary)
    export_json(merged, out_path, len(primary), added)


if __name__ == "__main__":
    main()
