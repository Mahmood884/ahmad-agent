# Dialect Pipeline — Bahraini Dictionary Enrichment

## What this is

Converts the raw Bahraini dialect dictionary (pasted from the Qwen session,
499KB text file) into an **enriched unified JSON dictionary** where every
entry carries a `usage` block:
`{lexical_tone, lexical_class, speaker_intent, strength?, origin_type?}`.

The enriched output is the vocabulary layer for AHMAD-OS's dialect engine —
it tells the agent how each word *sounds* (lexical_tone), what it *is*
(lexical_class), that the speaker's intent is NOT word-derivable
(speaker_intent), how *severe* it is (strength), and where it *came from*
(origin_type).

## Pipeline

```
raw/bahraini_dictionary_raw.txt   (499KB — FOUR sources, see below)
        │
        ├─ source 1: JSON-in-markdown (x2 identical copies, 1896 occurrences)
        │            ▼  scripts/extract_dictionary.py
        │     data/dictionary_raw.yaml          (948 unique entries, clean YAML)
        │            ▼  scripts/build_enriched_yaml.py
        │     data/dictionary_enriched.yaml     (948 entries + usage block on each)
        │
        ├─ source 2: antigravity python script in the file's TAIL
        │            (entries_raw = [...], 835 entries — 351 genuinely new)
        │            ▼  scripts/merge_and_export_json.py --secondary-from-python
        │         data/antigravity_entries.json    (835 entries, usage-filled)
        │
        ├─ source 3: curated greeting warmth scale (user, 2026-10-13)
        │            data/greeting_warmth_curated.yaml  (11 entries — HIGHEST precedence)
        │
        └─ source 4: WhatsApp-group corpus "قاموس أهل البحرين" (2026-10-13)
                     data/whatsapp_corpus_curated.yaml    (128 entries from 6 batches, +121 net-new, incl. 8 proverbs)
                                    ▼
        data/bahraini_dictionary_unified.json  (1429 = 948 + 351 + 11 + 121 net-new)
```

Run all steps:

```bash
cd ~/ahmad-agent/dialect
source ~/ahmad-agent/.venv/bin/activate
python3 scripts/extract_dictionary.py
python3 scripts/build_enriched_yaml.py data/dictionary_raw.yaml data/dictionary_enriched.yaml
python3 scripts/merge_and_export_json.py          # uses data/antigravity_entries.json if present
```

To re-extract the secondary source from the raw file's tail script:

```bash
# extract the script tail, then:
python3 scripts/merge_and_export_json.py --secondary-from-python <script.py>
```

## The two sources in the raw file (discovered 2026-10-13)

The raw paste is NOT just duplicated JSON. It contains:

| Block | What | Count |
|---|---|---|
| fences 1–2 | dictionary JSON (identical copies) | 948 unique each |
| fence 3 | metadata-only stub | 0 entries |
| file tail | complete antigravity enrichment script with `entries_raw` | **835 entries — 351 new** |

The 351 new terms include common ones the primary source lacks: `وايد`,
`حلطمة`, `لاويش`, `صه`, `عيار`, `بقعة`, `حنفروش`, `مطعطع`…
(`كشتة`/`كشخة` exist as `كشته`/`كشخه` — orthographic variants, not gaps.)
Extraction uses `ast.literal_eval` — never `eval`.

## Output format

```yaml
entries:
- term: أبسطه
  meaning: ضربه
  examples: []
  synonyms:
  - كوفنه
  usage:
    lexical_tone: aggressive     # how the WORD sounds (positive | negative | neutral | aggressive | friendly)
    lexical_class: threat        # what the WORD is (describe | question | greeting | praise |
                                 # curse | threat | dismiss | insult)
    speaker_intent: context-dependent  # actual intent needs sentence context — NOT word-derivable
    strength: medium             # high | medium (only for threat/curse/insult/dismiss)
    origin_type: english         # english | hindi | italian | persian | russian | turkish | french
                                 # (only for loanwords)
```

**Semantic boundary:** `lexical_tone` and `lexical_class` describe the WORD,
not the speaker. "أبسطه = ضربه" classifies the word; it does NOT establish
that a speaker using it intends violence (could be quotation, joke, report,
or question). Never train on these labels as intent ground truth.

## Statistics (verified run, 2026-10-13, post-review v2)

- **Primary source:** 948 unique entries from 1,896 occurrences (2 identical copies)
- **Secondary source (antigravity):** 835 entries → **+351 new**
- **Curated warmth scale (user):** 11 entries (1 overrides primary `هلا`)
- **WhatsApp corpus (6 batches):** ~1,150 pairs parsed → ~1,029 already covered → **+121 net-new** (128 written, incl. 8 proverbs)
- Batch 1: 263 pairs → 87% coverage → +26 net-new
- Batch 2 (مصطلحات بحرانية): +25 net-new (طمبل، تنكه، ثقيل طينه، صمايل، لوفري...)
- Batch 3 (forum comments): pure noise — 0 terms extracted (filtered)
- Batch 4 (Instagram + صحيفة الوسط): 9/9 terms already covered → +3 net-new (أمبهبل، رحت ملح، فقحة) + 8 proverbs
- Batch 5 (academic: شعبية/أعجمية/يومية): 41% coverage → +24 net-new (استيشن، اسويج، بَس، تُجورِي، جاكليت، برواز، واركوت...)
- Batch 6 (huge list): 223 pairs → 83% coverage → +37 net-new (البيالة، التجمبح، بوخفنة، تهردم، تحنقل...)
- **Unified total:** **1429 entries** · **0 null fields** (sparse fields omitted, not null)
- Field coverage: term 1335, meaning 1335, examples (source-carried), synonyms (source-carried),
  dialect_region 11, origin 55, notes 5
- Usage distribution:
  - lexical_tone: neutral 1284 / negative 19 / aggressive 14 / friendly 13 / positive 5
  - lexical_class: describe 1267 / insult 19 / greeting 13 / question 10 / dismiss 8 / curse 7 / praise 5 / threat 6
  - warmth (greetings only): high 7 / medium 3 / low 1 — the graded scale
  - origin_type: english 44, hindi 5, persian 4, french 2, italian 2, turkish 2, russian 1

## Runtime access — dialect/engine.py

The wiring gap (no loader connecting the artifacts to the inference path) is
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
by ID and by alias · rejected-terms guard (all spellings) · whole-word +
phrase + clitic matching · context-block injection with notes/examples/
synonyms/origin/region · bare-term-wins on paren-variant collisions.
Smoke test: `python3 engine.py "<message>"`.

`scripts/ollama_bridge.py` delegates ALL dialect logic to `DialectEngine` —
one matching implementation, one schema, zero drift.

## Known fixes applied (2026-10-13, post-review v2)

**Review round 1 (word-boundary):** plain substring matching (`k in text`)
produced mechanical false positives on Arabic words that *contain* a keyword:
`بلبله` (faucet) = insult, `جابله` (tomorrow) = insult, `أيسي` (aircon) =
question, `أدنات` (day of threat) = greeting. Fix: Arabic word-boundary regex
`(?<![\u0621-\u064A])kw(?![\u0621-\u064A])` + removal of ambiguous keywords.

**Review round 2 (2026-10-13):**

1. `origin_type` falls back to the source's own `origin` field (55 entries
   carry it; pattern-only recovered 29, fallback recovers 60 total).
2. Loanword patterns: dead madda-form patterns replaced by plain-alef twins.
3. Ontology dangling refs resolved (20 concepts, all defined).
4. `semantic_fidelity.md` §9 marks each planned file as موجود / غير موجود.
5. 8 keyword errors fixed (شكر/كريم/حلو/كف/سقط/طيح + 3 more) — all clean.

**Review round 3 (2026-10-13, v2 engine):**

1. **Secondary source merged (was absent at build time):** the antigravity
   script in the raw file's tail was extracted (`ast.literal_eval`) and
   merged: 948 → **1299** entries.
2. **Schema unification:** both sources now emit the same `usage` schema
   (lexical_tone/lexical_class/speaker_intent). The old generic analyzer
   emitted `{tone, intent}` — dead keys. `ollama_bridge.py` no longer reads
   them; it delegates to `DialectEngine`.
3. **Per-word normalization:** `normalize_term` normalizes each word
   independently — `طايح النصبة` now matches itself (the ة→ه rule was
   anchored at the end of the whole string).
4. **Null fields dropped:** 2,773 nulls removed — absent means absent.
5. **Source order preserved:** no codepoint sort; entries keep source order.
6. **Bare-term-wins on collision:** `مطعم (بضم الميم)` no longer steals the
   `مطعم` phrase key.
7. **Full context payload:** `enrich_context` injects notes / examples /
   synonyms / origin / region, and alerts on rejected terms in all their
   spellings (عزوز / زيزو / غزيزو).
8. **Reproducible build:** `build_engine_v2.py` regenerates the engine from
   `engine_v1_substring.py.bak` — verified byte-identical output.
9. **Tests:** 16/16 dialect regression tests (dialect/test_dialect_engine.py)
   + full repo suite **270 passed / 3 skipped**.

**Known limitations (still honest):**

1. **Keyword rules ≠ semantics.** `describe` covers ~908/948 entries because
   most dictionary entries are nouns/objects with no emotive markers. The
   *boundaries* are keyword-derived, not model-derived. A local model or the
   DPO pairs should review edge cases before training.
2. **`strength` only fires for threat/curse/insult/dismiss** — by design.
3. **`speaker_intent` is always "context-dependent"** — the dictionary
   deliberately does not claim to know what a speaker means.
4. **`dialect_region` (11) and `origin` (55) are sparse in the source
   itself**, not lost in extraction.
5. **The 2 dictionary copies in the raw file are identical** (948 unique
   terms both times) — extraction dedupes by first occurrence.
6. **The engine is NOT wired into `src/ahmad/`** — `enrich_context()` must be
   called from the conversation/provider path, and `semantic_fidelity.md`
   loaded as a system prompt. The loader exists; the runtime call site does
   not (yet). This is the next wiring step, not a data problem.

## Files

```
dialect/
├── README.md                          # this file
├── TASK_PROMPT.md                     # self-contained task spec (v3 schema) for model comparison
├── ontology.yaml                      # semantic concept registry (L2) — stable IDs, definitions, aliases
├── engine.py                          # runtime loader (canonical) — whole-word matching + full payload
├── engine_v2.py                       # compatibility re-export of engine.py
├── engine_v1_substring.py.bak         # pre-review engine (substring matching) — build source of truth
├── build_engine_v2.py                 # regenerates engine.py from the .bak (verified byte-identical)
├── test_dialect_engine.py             # 16 regression tests (engine + dictionary + ontology)
├── raw/
│   └── bahraini_dictionary_raw.txt    # 499KB source paste (do not edit)
├── scripts/
│   ├── extract_dictionary.py          # raw text → clean YAML (brace-matched JSON extraction)
│   ├── build_enriched_yaml.py         # clean YAML → enriched YAML (lexical usage blocks)
│   ├── merge_and_export_json.py       # sources → unified JSON (secondary extractable via --secondary-from-python)
│   └── ollama_bridge.py               # Ollama client — delegates all dialect logic to DialectEngine
├── data/
    ├── dictionary_raw.yaml            # 948 entries, 4254 lines
    ├── dictionary_enriched.yaml       # 948 entries + usage, 7155 lines
    ├── antigravity_entries.json       # 835 secondary-source entries (351 new merged in)
    ├── greeting_warmth_curated.yaml   # 11 curated warmth-scale entries (user — HIGHEST precedence)
    ├── whatsapp_corpus_curated.yaml   # 128 entries from 6 batches (+121 net-new, incl. 8 proverbs)
    └── bahraini_dictionary_unified.json  # 1429 entries, unified product
```

Related: `../prompts/semantic_fidelity.md` — the agent system prompt built
from this registry (interpretation protocol, priority order, clarification
policy, evidence discipline).
