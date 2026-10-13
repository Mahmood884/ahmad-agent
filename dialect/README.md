# Dialect Pipeline — Bahraini Dictionary Enrichment

## What this is

Converts the raw Bahraini dialect dictionary (pasted from the Qwen session,
499KB text file) into an **enriched YAML dictionary** where every entry carries
a `usage` block: `{tone, intent, strength?, origin_type?}`.

The enriched output is the vocabulary layer for AHMAD-OS's dialect engine —
it tells the agent how each word *sounds* (tone), what it *wants* (intent),
how *severe* it is (strength), and where it *came from* (origin_type).

## Pipeline

```
raw/bahraini_dictionary_raw.txt   (499KB, pasted JSON-in-markdown, 2 duplicate copies)
        │
        ▼  scripts/extract_dictionary.py
data/dictionary_raw.yaml          (948 unique entries, clean YAML)
        │
        ▼  scripts/build_enriched_yaml.py
data/dictionary_enriched.yaml     (948 entries + usage block on each)
```

Run both steps:

```bash
cd ~/ahmad-agent/dialect
source ~/ahmad-agent/.venv/bin/activate
python3 scripts/extract_dictionary.py
python3 scripts/build_enriched_yaml.py data/dictionary_raw.yaml data/dictionary_enriched.yaml
```

## Output format

```yaml
entries:
- term: أبسطه
  meaning: ضربه
  examples: []
  synonyms:
  - كوفنه
  usage:
    lexical_tone: aggressive     # how the WORD sounds (positive | negative | neutral | aggressive)
    lexical_class: threat        # what the WORD is (describe | question | greeting | praise |
                                 # curse | threat | dismiss | insult)
    speaker_intent: context-dependent  # actual intent needs sentence context — NOT word-derivable
    strength: medium             # high | medium  (only for threat/curse/insult)
    origin_type: english         # english | hindi | italian | persian | russian | turkish
                                 # (only for loanwords)
```

**Semantic boundary (added 2026-10-13):** `lexical_tone` and `lexical_class`
describe the WORD, not the speaker. "أبسطه = ضربه" classifies the word; it does
NOT establish that a speaker using it intends violence (could be quotation,
joke, report, or question). Never train on these labels as intent ground truth.

## Statistics (verified run, 2026-10-13, post-review fixes)

- **948 unique entries** extracted from 1,896 occurrences (the raw file contains 2 identical copies)
- Field coverage: term 948, meaning 948, examples 948, synonyms 948, dialect_region 11, origin 55, notes 5
- Usage distribution after all fixes:
  - lexical_tone: neutral 919 / negative 18 / aggressive 7 / positive 4
  - lexical_class: describe 908 / insult 18 / dismiss 5 / curse 5 / praise 4 / question 5 / threat 2 / greeting 1
  - origin_type (with source-field fallback): english 44, hindi 5, persian 4, french 2, italian 2, turkish 2, russian 1 = **60 total** (was 29 pattern-only)

## Runtime access — dialect/engine.py

The review gap (no loader connecting the artifacts to the inference path) is
closed by `engine.py`:

```python
from dialect.engine import DialectEngine
engine = DialectEngine()                      # loads unified JSON + ontology
engine.lookup("أبشار")                        # → entry (normalized fallback)
engine.concept("AHMAD.CONCEPT.GOVERNANCE_LAYER")  # → concept record
engine.enrich_context("عطني أبشار شخبارك")     # → Arabic context block for the prompt
engine.stats()                                # → counts + distributions
```

Engine capabilities: exact + normalized + synonym lookup · concept resolution
by ID and by alias · rejected-terms guard · context-block injection ·
per-word lexical annotation. Smoke test: `python3 engine.py "<message>"`.

## Known fixes applied (2026-10-13, post-review)

**Review round 1 (word-boundary):** plain substring matching (`k in text`)
produced mechanical false positives on Arabic words that *contain* a keyword:
`بلبله` (faucet) = insult, `جابله` (tomorrow) = insult, `أيسي` (aircon) =
question, `أدنات` (day of threat) = greeting. Fix: Arabic word-boundary regex
`(?<![\u0621-\u064A])kw(?![\u0621-\u064A])` + removal of ambiguous keywords
("أهل", "سلم", "عيد", "وعيد", "هل", "كيف").

**Review round 2 (2026-10-13):**

1. `origin_type` now falls back to the source's own `origin` field (e.g.
   "الروسية - Ctakanh" → russian) when no pattern matches — 55 entries carry
   the field; pattern-only recovered 29, fallback recovers 60 total.
2. Loanword patterns fixed: dead madda-form patterns (آيسي/آيدين) now have
   plain-alef twins (أيسي/أيدين — the live forms); dead duplicates removed.
3. Ontology dangling refs resolved: AGENT_RUNTIME, SECURE_PROTOCOL,
   INTENT_ANNOTATION, USER_ASSISTANT are now defined concepts (20 total).
4. `semantic_fidelity.md` §9 now marks each planned file explicitly as
   موجود / غير موجود بعد (مخطط) — no hallucination bait.
5. Remaining keyword errors fixed: "شكر" (matched sugar سكر), "كريم" (matched
   ice cream عسكريم), "حلو" (matched sweet water ماي بيلر), "كف" (matched
   palm كف اليد / slap كف راشدي), "سقط"/"طيح" (matched literal falling
   أنشدخ/صفرة). All 8 verified clean.

**Known limitations (still honest):**

1. **Keyword rules ≠ semantics.** `describe` covers 908/948 entries because
   most dictionary entries are nouns/objects with no emotive markers. This is
   correct behavior — not every word carries tone. But the *boundaries* are
   keyword-derived, not model-derived. A 1B local model or the 188 DPO pairs
   should review edge cases before this feeds training.
2. **`strength` only fires for threat/curse/insult.** Descriptive weakness
   ("ضعيف البنية بسبب مرض") stays `describe`, not `insult` — by design.
3. **`speaker_intent` is always "context-dependent"** — the dictionary
   deliberately does not claim to know what a speaker means.
4. **`dialect_region` (11) and `origin` (55) fields are sparse** in the source
   itself, not lost in extraction.
5. **The 2 duplicate copies in the raw file are identical** (948 unique terms
   both times) — extraction dedupes by first occurrence.

## Files

```
dialect/
├── README.md                          # this file
├── TASK_PROMPT.md                     # self-contained task spec for model comparison
├── ontology.yaml                      # semantic concept registry (L2) — stable IDs, definitions, aliases
├── raw/
│   └── bahraini_dictionary_raw.txt    # 499KB source paste (do not edit)
├── scripts/
│   ├── extract_dictionary.py          # raw text → clean YAML (brace-matched JSON extraction)
│   ├── build_enriched_yaml.py         # clean YAML → enriched YAML (lexical usage blocks)
│   └── merge_and_export_json.py       # sources → unified JSON (antigravity loader ready, source absent)
└── data/
    ├── dictionary_raw.yaml            # 948 entries, 4254 lines
    ├── dictionary_enriched.yaml       # 948 entries + usage, 7155 lines
    └── bahraini_dictionary_unified.json  # 948 entries, unified product (~325KB)
```

Related: `../prompts/semantic_fidelity.md` — the agent system prompt built
from this registry (interpretation protocol, priority order, clarification
policy, evidence discipline).
