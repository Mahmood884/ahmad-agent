#!/usr/bin/env python3
"""
Extract the unique Bahraini dialect dictionary from the raw pasted text.

The raw file (raw/bahraini_dictionary_raw.txt) is a paste of a JSON dictionary
wrapped in markdown fences. It contains 2 identical copies of the same
948-entry dictionary (verified: 1896 total term occurrences, 948 unique).

This script:
  1. Locates every ```json fenced block in the raw text.
  2. Extracts the `"entries": [...]` array from each block using brace
     matching (the JSON is pretty-printed with blank lines between keys,
     which is still valid JSON, but the file also contains stray prose
     outside the fences — so we cut precisely at the array).
  3. Deduplicates by `term` (first occurrence wins).
  4. Writes a clean YAML dictionary to data/dictionary_raw.yaml in the
     schema expected by scripts/build_enriched_yaml.py:

         entries:
           - term: "..."
             meaning: "..."
             examples: []
             synonyms: []
             notes: "..."        # optional
             dialect_region: "..."  # optional
             origin: "..."       # optional

Usage:
    python scripts/extract_dictionary.py [raw_path] [output_yaml]
"""

import json
import re
import sys
from pathlib import Path

import yaml


def find_fenced_blocks(text: str) -> list[str]:
    """Return the content of every ```json ... ``` block."""
    blocks = []
    for m in re.finditer(r"```json", text):
        start = m.end()
        end = text.find("```", start)
        if end == -1:
            end = len(text)
        blocks.append(text[start:end])
    return blocks


def extract_entries_array(block: str) -> list[dict] | None:
    """Pull the JSON array that follows "entries": using brace matching."""
    idx = block.find('"entries"')
    if idx == -1:
        return None
    br = block.find("[", idx)
    if br == -1:
        return None
    depth = 0
    for j in range(br, len(block)):
        if block[j] == "[":
            depth += 1
        elif block[j] == "]":
            depth -= 1
            if depth == 0:
                candidate = block[br : j + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # tolerate trailing commas
                    fixed = re.sub(r",\s*([\]}])", r"\1", candidate)
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        return None
    return None


def main() -> None:
    here = Path(__file__).resolve().parent.parent
    raw_path = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "raw" / "bahraini_dictionary_raw.txt"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else here / "data" / "dictionary_raw.yaml"

    raw = raw_path.read_text(encoding="utf-8")

    blocks = find_fenced_blocks(raw)
    print(f"[extract] fenced json blocks found: {len(blocks)}")

    seen: dict[str, dict] = {}
    order: list[str] = []
    total_occurrences = 0

    for i, block in enumerate(blocks):
        entries = extract_entries_array(block)
        if entries is None:
            print(f"[extract] block {i}: no entries array parsed — skipped")
            continue
        print(f"[extract] block {i}: {len(entries)} entries")
        for e in entries:
            total_occurrences += 1
            term = (e.get("term") or "").strip()
            if not term:
                continue
            if term not in seen:
                seen[term] = e
                order.append(term)

    unique = [seen[t] for t in order]
    print(f"[extract] total occurrences: {total_occurrences}")
    print(f"[extract] unique terms: {len(unique)}")

    # Field census
    fields: dict[str, int] = {}
    for e in unique:
        for k in e:
            fields[k] = fields.get(k, 0) + 1
    print(f"[extract] field coverage: {fields}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.dump(
            {"entries": unique},
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=10_000,
        )
    print(f"[extract] wrote {out_path} ({len(unique)} entries)")


if __name__ == "__main__":
    main()
