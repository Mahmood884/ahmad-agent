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

## Statistics (verified run, 2026-10-13)

- **948 unique entries** extracted from 1,896 occurrences (the raw file contains 2 identical copies)
- Field coverage: term 948, meaning 948, examples 948, synonyms 948, dialect_region 11, origin 55, notes 5
- Usage distribution after fixes:
  - tone: neutral 916 / negative 18 / aggressive 7 / positive 7
  - intent: describe 902 / insult 18 / dismiss 7 / threat 5 / curse 5 / praise 5 / question 5 / greeting 1
  - origin_type (detected): 30 loanwords — english 21, persian 3, hindi 3, italian 2, turkish 1

## Known fixes applied (2026-10-13)

The staged `scripts/build_enriched_yaml.py` in `ahmad-agent/scripts/` used
plain substring matching (`k in text`), which produced mechanical false
positives on Arabic words that *contain* a keyword:

| Entry | Meaning | Was (staged) | Now (fixed) |
|---|---|---|---|
| بلبله | حنفية الماء (faucet) | insult ("بله" inside "بلبله") | describe |
| جابله | بكره/غداً (tomorrow) | insult ("بله" inside "جابله") | describe |
| أيسي | مكيف الهواء (aircon) | question ("كيف" inside "مكيف") | describe |
| مهلهل / منهل / هليلج | various | question ("هل" substring) | describe |
| أدنات | يوم للوعيد والتهديد | greeting ("عيد" inside "للوعيد") | describe |
| صيري | سلم خشب (ladder) | greeting ("سلم") | describe |
| ونقه | أوصله بعيداً | greeting ("عيد" inside "بعيداً") | describe |

Fix: all keyword matching now goes through `kw_in()` — Arabic word-boundary
regex `(?<![\u0621-\u064A])kw(?![\u0621-\u064A])`. Ambiguous keywords
("أهل", "سلم", "عيد", "وعيد", "هل", "كيف") were removed from lists where
they collide with common words; "شيطان" added to curse markers.

## Known limitations (honest)

1. **Keyword rules ≠ semantics.** `describe` covers 902/948 entries because
   most dictionary entries are nouns/objects with no emotive markers. This is
   correct behavior — not every word carries tone. But the *boundaries* are
   keyword-derived, not model-derived. A 1B local model or the 180 DPO pairs
   should review edge cases before this feeds training.
2. **`strength` only fires for threat/curse/insult.** Descriptive weakness
   ("ضعيف البنية بسبب مرض") stays `describe`, not `insult` — by design.
3. **`dialect_region` (11) and `origin` (55) fields are sparse** in the source
   itself, not lost in extraction.
4. **The 2 duplicate copies in the raw file are identical** (948 unique terms
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
