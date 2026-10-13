#!/usr/bin/env python3
"""
Build enriched Bahraini dialect dictionary from raw YAML.
Fills the `usage` field with tone, intent, strength, and origin_type
analysis for every entry.

FIXES vs. the staged version (word-boundary + keyword curation):
  1. All keyword matching now uses Arabic word boundaries:
     a keyword matches only when NOT preceded AND NOT followed by an
     Arabic letter. This kills substring false positives such as:
       - "كيف" inside "مكيف" (aircon)  -> was: question
       - "هل" inside "مهلهل"/"منهل"/"هليلج" -> was: question
       - "بله" inside "بلبله" (faucet) / "جابله" (tomorrow) -> was: insult
       - "سلام" inside "سلامة", "عيد" inside "بعيداً" -> was: greeting
       - "غبي" inside "المشاغبين" (naughty) -> was: insult
  2. Removed ambiguous common words from keyword lists:
     - greeting: dropped "أهل" (family/people, e.g. "عند أهل البلاد"),
       "سلم" (also "ladder": "سلم خشب"), "عيد" (proverb refs), "وعيد"
       (means threat, not greeting).
     - question: kept distinctive markers only.
  3. Added "شيطان" to curse keywords (e.g. يالمبغول).

Usage:
    python scripts/build_enriched_yaml.py [input.yml] [output.yml]
"""

import sys
import re
from pathlib import Path

import yaml

# Arabic letters range (hamza through ya) — used for word boundaries.
# Arabic diacritics/tatweel are included so "غبيّ" still matches.
_AR = r"[\u0621-\u064A\u0640\u064B-\u0652]"


def kw_in(keyword: str, text: str) -> bool:
    """Word-boundary-aware substring match for Arabic text.

    Matches only when the keyword is not immediately preceded or followed
    by an Arabic letter. Clitics (ل/ب/ك/و prefixes) therefore do NOT match:
    "للوعيد" does not match "وعيد". This is intentional — the curated
    keyword lists carry standalone forms only.
    """
    pattern = rf"(?<!{_AR}){re.escape(keyword)}(?!{_AR})"
    return re.search(pattern, text) is not None


# ── Keyword-based analysis rules ──────────────────────────────────────────────

AGGRESSIVE_MEANING_KEYWORDS = [
    "ضرب", "ضري", "اطلق", "رمي", "طرد", "قتل", "سحق", "كسر", "باكسر",
    "ضربه", "ضربوا", "ضربت", "ضربنا", "طعن", "غضب",
    "نادى", "صرخ", "صاخ", "صفارة", "هور", "عصيان",
]

DISMISS_INTENT_KEYWORDS = [
    "اذهب", "انه", "اسكت", "كف", "روحي", "اخرج", "جه", "نهي",
    "ارحل", "اطرد", "رفض", "امتنع",
]

INSULT_INTENT_KEYWORDS = [
    "غبي", "أغبي", "أحمق", "جاهل", "نامام", "كذاب", "كاذب", "خاين",
    "وثني", "سخيف", "مجنون", "هبلة", "أعمى", "أصم",
    "جبان", "حقير", "وسخ", "مقرف", "بله", "تافه",
]

THREAT_INTENT_KEYWORDS = [
    "ضرب", "كسر", "سحق", "أبلك", "خرّب", "احترق", "طيح", "سقط",
    "خيف", "يخوف", "يرعب", "رعب", "أرعب", "تهديد",
]

POSITIVE_TONE_KEYWORDS = [
    "ذكي", "ذكى", "جميل", "حلو", "طيب", "حسن", "أحسن", "شكر", "حمد",
    "ممتاز", "رائع", "كريم", "وفي", "صادق", "أمين",
]

NEGATIVE_TONE_KEYWORDS = [
    "خاين", "كذاب", "غبي", "مجنون", "جبان", "حقير", "وسخ",
    "مقرف", "سخيف", "حزين", "غاضب", "زعلان", "تعبان", "مريض", "بائس",
]

# Curated greeting markers — only words that are greetings in context.
# Dropped: "أهل" (family/people), "سلم" (also ladder), "عيد" (proverb refs),
# "وعيد" (means threat).
GREETING_INTENT_KEYWORDS = [
    "مرحبا", "أهلا", "هلا", "حباب", "مساء", "صباح", "السلام",
]

# Distinctive question markers only ("هل"/"كيف" removed — too short,
# they collide with common words; boundary matching keeps standalone forms).
QUESTION_INTENT_KEYWORDS = [
    "لماذا", "ماذا", "شنو", "شنوها", "أيش", "ليش", "وش",
]

CURSE_INTENT_KEYWORDS = [
    "دعاء", "اللعنة", "خراب", "هلك", "يلعن", "شيطان",
]

LOANWORD_PATTERNS = [
    (r"^أجست$", "English"),    # Adjust
    (r"^آيدين$", "English"),   # Iodine
    (r"^آيسي$", "English"),    # Aircon
    (r"^بست$", "English"),     # Bus
    (r"^بستوك$", "English"),   # Biscuit
    (r"^بوم$", "English"),     # Boom
    (r"^ديكور$", "English"),   # Decoration
    (r"^راندبوت$", "English"), # Roundabout
    (r"^سبانة$", "English"),   # Spanner
    (r"^سبيتار$", "English"),  # Hospital
    (r"^سكروب$", "English"),   # Screwdriver
    (r"^سيت$", "English"),     # Seat
    (r"^شاصي$", "English"),    # Chassis
    (r"^كاب شلقلقي$", "English"), # Shaker
    (r"^كاتشب$", "English"),   # Ketchup
    (r"^كيبل$", "English"),    # Cable
    (r"^كونديشن$", "English"), # Conditioner
    (r"^كنديشن$", "English"),  # Conditioner (variant)
    (r"^موتر$", "English"),    # Motor
    (r"^مانج$", "English"),
    (r"^روتي$", "Hindi"),
    (r"^شربت$", "Hindi"),
    (r"^سيده$", "Hindi"),
    (r"^عسكريم$", "English"),  # Ice cream
    (r"^فوت$", "English"),
    (r"^كيري ميري$", "English"),
    (r"^ماي بيلر$", "English"),
    (r"^كوجر$", "English"),
    (r"^طاولة$", "Italian"),   # Tavola
    (r"^معكرونة$", "Italian"),# Macaroni
    (r"^أوتو$", "Persian"),
    (r"^أوز$", "Persian"),
    (r"^حنفروش$", "Persian"),
    (r"^خنفروش$", "Persian"),
    (r"^بار$", "Persian"),
    (r"^بوز$", "Persian"),
    (r"^استكانه$", "Russian"), # Ctakanh
    (r"^تتن$", "Turkish"),
    (r"^برغي$", "Turkish"),
    (r"^بقصم$", "Turkish"),
    (r"^بقعة$", "Turkish"),
    (r"^كوت$", "English"),
    (r"^كول$", "English"),
    (r"^لاف$", "English"),
    (r"^لوم$", "English"),
    (r"^ميكرو$", "English"),
    (r"^يوتي$", "English"),
    (r"^بيز$", "English"),
    (r"^فن$", "English"),
    (r"^فنيلة$", "English"),
]


def detect_tone(term: str, meaning: str, intent: str) -> str:
    """Detect tone: positive / negative / neutral / aggressive."""
    text = f"{term} {meaning}"

    if any(kw_in(k, text) for k in POSITIVE_TONE_KEYWORDS):
        return "positive"
    if intent in ("insult", "threat", "dismiss") and any(
        kw_in(k, text) for k in NEGATIVE_TONE_KEYWORDS + INSULT_INTENT_KEYWORDS
    ):
        return "negative"
    if any(kw_in(k, text) for k in AGGRESSIVE_MEANING_KEYWORDS):
        return "aggressive"
    return "neutral"


def detect_intent(term: str, meaning: str) -> str:
    """Detect intent: describe / question / dismiss / insult / threat / curse / praise / greeting."""
    text = f"{term} {meaning}"

    if any(kw_in(k, text) for k in QUESTION_INTENT_KEYWORDS):
        return "question"

    if any(kw_in(k, text) for k in GREETING_INTENT_KEYWORDS):
        return "greeting"

    if any(kw_in(k, text) for k in ["ذكي", "جميل", "حلو", "طيب", "حسن", "أحسن", "ممتاز", "رائع"]):
        return "praise"

    if any(kw_in(k, text) for k in CURSE_INTENT_KEYWORDS):
        return "curse"

    if any(kw_in(k, text) for k in THREAT_INTENT_KEYWORDS):
        return "threat"

    if any(kw_in(k, text) for k in DISMISS_INTENT_KEYWORDS):
        return "dismiss"

    if any(kw_in(k, text) for k in INSULT_INTENT_KEYWORDS):
        return "insult"

    return "describe"


def detect_strength(term: str, meaning: str, intent: str) -> str | None:
    """Return 'high' / 'medium' / None based on severity."""
    text = f"{term} {meaning}"

    if intent in ("threat", "curse", "insult"):
        if any(kw_in(w, text) for w in ["قوي", "شديد", "مبرح", "لصيق"]):
            return "high"
        return "medium"
    return None


def detect_origin_type(term: str) -> str | None:
    """Detect if word is a loanword and return language or None."""
    for pattern, lang in LOANWORD_PATTERNS:
        if re.search(pattern, term, re.IGNORECASE):
            return lang.lower()
    return None


def enrich_entry(entry: dict) -> dict:
    """Add lexical analysis to a single dictionary entry.

    IMPORTANT SEMANTIC BOUNDARY (added 2026-10-13 after review):
    The fields produced here describe the WORD (lexical class), not the
    SPEAKER'S INTENT in a sentence. `أبسطه` = "ضربه" describes what the word
    means — it does NOT establish that a speaker using it intends to hit
    anyone (it may be quotation, joke, report, or question). Do not train a
    model to treat these labels as intent ground truth.
    """
    term = entry.get("term", "")
    meaning = entry.get("meaning", "")

    intent = detect_intent(term, meaning)
    tone = detect_tone(term, meaning, intent)
    strength = detect_strength(term, meaning, intent)
    origin_type = detect_origin_type(term)

    usage = {
        "lexical_tone": tone,          # how the WORD sounds (positive/negative/neutral/aggressive)
        "lexical_class": intent,       # what the WORD is (describe/question/greeting/praise/curse/threat/dismiss/insult)
        "speaker_intent": "context-dependent",  # actual intent requires sentence context — NOT derivable from the word alone
    }
    if strength:
        usage["strength"] = strength
    if origin_type:
        usage["origin_type"] = origin_type

    entry["usage"] = usage
    return entry


def enrich_yaml(raw_text: str) -> str:
    """Parse raw YAML, enrich every entry, return formatted YAML."""
    data = yaml.safe_load(raw_text)

    if "entries" not in data:
        raise ValueError("YAML must have top-level 'entries' key")

    enriched = []
    for entry in data["entries"]:
        enriched.append(enrich_entry(entry))

    data["entries"] = enriched
    return yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False, width=10_000)


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    if input_path and input_path.exists():
        raw = input_path.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    result = enrich_yaml(raw)

    if output_path:
        output_path.write_text(result, encoding="utf-8")
        print(f"✅ Enriched dictionary written to {output_path}")
        print(f"   Entries processed: {len(yaml.safe_load(result)['entries'])}")
    else:
        print(result)


if __name__ == "__main__":
    main()
