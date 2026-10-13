#!/usr/bin/env python3
"""
Build enriched Bahraini dialect dictionary from raw YAML.
Fills the empty `usage` field with tone, intent, strength, and origin_type
analysis for every entry.

Usage:
    python scripts/build_enriched_yaml.py [input.yml] [output.yml]
"""

import sys
import re
from pathlib import Path

import yaml

# ── Keyword-based analysis rules ──────────────────────────────────────────────

# Words whose meaning contains violence, hitting, or physical threat → aggressive
AGGRESSIVE_MEANING_KEYWORDS = [
    "ضرب", "ضري", "اطلق", "رمي", "طرد", "قتل", "سحق", "كسر", "باكسر",
    "ضربه", "ضربوا", "ضربت", "ضربنا", "ضربتم", "ضربوا", "طعن", "غضب",
    "زعلان", "زعل", "نادى", "صرخ", "صاخ", "صفارة", "هور", "عصيان",
]

# Words expressing dismissal, shooing, telling to go away → dismiss
DISMISS_INTENT_KEYWORDS = [
    "اذهب", "انه", "اسكت", "كف", "ط", "روحي", "اخرج", "جه", "نهي",
    "ارحل", "اطرد", "رفض", "لا", "ما", "امتنع",
]

# Words that are insults or offensive → insult
INSULT_INTENT_KEYWORDS = [
    "غبي", "أغبي", "أحمق", "جاهل", "نمام", "كذاب", "كاذب", "خاين",
    "وثني", "سخيف", "مجنون", "غف", "هبلة", "بطيء", "أعمى", "أصم",
    "ضعيف", "جبان", "حقير", "وسخ", "مقرف", "بله", "تافه",
]

# Words expressing threat → threat
THREAT_INTENT_KEYWORDS = [
    "ضرب", "كسر", "سحق", "أبلك", "خرّب", "احترق", "طيح", "سقط",
    "خيف", "يخوف", "يرعب", "رعب", "أرعب", "تهديد",
]

# Positive / praise words → positive tone
POSITIVE_TONE_KEYWORDS = [
    "ذكي", "ذكى", "جميل", "حلو", "طيب", "حسن", "أحسن", "شكر", "حمد",
    "ممتاز", "رائع", "جم", "أحباب", "حبي", "سلام", "أهل", "كريم",
    "وفي", "صادق", "أمين",
]

# Negative tone keywords → negative
NEGATIVE_TONE_KEYWORDS = [
    "خاين", "كذاب", "غبي", "مجنون", "ضعيف", "جبان", "حقير", "وسخ",
    "مقرف", "بله", "سخيف", "طيب", "حلو",  # some overlap, handled by intent
    "حزين", "غاضب", "زعلان", "تعبان", "مريض", "بائس",
]

# Loanwords from other languages → origin_type = "loanword"
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
    (r"^كوب$", "English"),     # Cup
    (r"^موتر$", "English"),    # Motor
    (r"^مانج$|^مانج$", "English"),
    (r"^روتي$", "Hindi"),
    (r"^شربت$", "Hindi"),
    (r"^سيده$", "Hindi"),
    (r"^عسكريم$", "English"),  # Ice cream
    (r"^فوت$", "English"),
    (r"^كيري ميري$", "English"),
    (r"^ماي$", "English"),
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
    (r"^كوب$", "English"),
    (r"^كوت$", "English"),
    (r"^كول$", "English"),
    (r"^لاف$", "English"),
    (r"^لوم$", "English"),
    (r"^ميكرو$", "English"),
    (r"^يوتي$", "English"),
    (r"^بيز$", "English"),
    (r"^فن$", "English"),
    (r"^فنيلة$", "English"),
    (r"^فن$", "English"),
]


def detect_tone(term: str, meaning: str, intent: str) -> str:
    """Detect tone: positive / negative / neutral / aggressive."""
    text = f"{term} {meaning}".lower()

    if any(re.search(k.lower(), text) for k in POSITIVE_TONE_KEYWORDS):
        return "positive"
    if intent in ("insult", "threat", "dismiss") and any(
        re.search(k.lower(), text) for k in NEGATIVE_TONE_KEYWORDS + INSULT_INTENT_KEYWORDS
    ):
        return "negative"
    if any(re.search(k.lower(), text) for k in AGGRESSIVE_MEANING_KEYWORDS):
        return "aggressive"
    return "neutral"


def detect_intent(term: str, meaning: str) -> str:
    """Detect intent: describe / question / dismiss / insult / threat / curse / praise / greeting."""
    text = f"{term} {meaning}".lower()

    # Question
    if any(w in text for w in ["لماذا", "ماذا", "شنو", "شنوها", "كيف", "هل", "أيش"]):
        return "question"

    # Greeting / friendly
    if any(w in text for w in ["سلم", "سلام", "أهل", "حباب", "هلا", "وعيد", "عيد"]):
        return "greeting"

    # Praise
    if any(w in text for w in ["ذكي", "جميل", "حلو", "طيب", "حسن", "أحسن", "ممتاز", "رائع"]):
        return "praise"

    # Curse / prayer against
    if any(w in text for w in ["دعاء", "اللعنة", "خراب", "هلك", "يلعن"]):
        return "curse"

    # Threat
    if any(w in text for w in ["ضرب", "كسر", "سحق", "أبلك", "خرّب", "طيح", "سقط", "خيف", "يخوف"]):
        return "threat"

    # Dismiss
    if any(w in text for w in ["اسكت", "اذهب", "انه", "كف", "روحي", "اخرج", "اطرد", "نهي", "ارحل"]):
        return "dismiss"

    # Insult
    if any(w in text for w in ["غبي", "أغبي", "أحمق", "جاهل", "نمام", "كذاب", "خاين", "حقير",
                                "وسخ", "مقرف", "بله", "سخيف", "مجنون", "جبان", "ضعيف"]):
        return "insult"

    # Default
    return "describe"


def detect_strength(term: str, meaning: str, intent: str) -> str | None:
    """Return 'high' / 'medium' / None based on severity."""
    text = f"{term} {meaning}".lower()

    if intent in ("threat", "curse", "insult"):
        if any(w in text for w in ["قوي", "شديد", "مبرح", "لصيق", "ما"]):
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
    """Add usage analysis to a single dictionary entry."""
    term = entry.get("term", "")
    meaning = entry.get("meaning", "")

    intent = detect_intent(term, meaning)
    tone = detect_tone(term, meaning, intent)
    strength = detect_strength(term, meaning, intent)
    origin_type = detect_origin_type(term)

    usage = {"tone": tone, "intent": intent}
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
    return yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


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
