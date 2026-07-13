"""
aggregate_entities.py

Reads all documents/<dir>/entities.csv files (or a combined all_entities.csv),
then for each entity type (artist, school, object_type):
  - Counts occurrences
  - Detects language (it/en/de/fr)
  - Clusters similar/translated values using Claude
  - Writes documents/artists.csv, documents/schools.csv, documents/object_types.csv
    with columns: canonical, variants, language, count

Usage:
    python3 aggregate_entities.py [--docs-dir documents] [--batch-size 200]
"""

from __future__ import annotations

import re
import csv
import json
import time
import argparse
import textwrap
from pathlib import Path
from collections import Counter

import anthropic

MODEL = "claude-sonnet-5"
MAX_TOKENS = 16000

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

LANG_AND_CLUSTER_PROMPT = textwrap.dedent("""\
You are an expert in art history and auction catalogues (Italian, English, French, German).

Below is a list of "{entity_type}" values extracted from auction catalogues, with their occurrence counts.
Each line is: COUNT | VALUE

{items}

Your tasks:
1. Detect the language of each value: "it", "en", "fr", "de", or "other".
2. Group values that refer to the same concept/person/school despite different spellings,
   languages, abbreviations or typos (e.g. "DIPINTI ANTICHI" / "OLD PAINTINGS" / "ANCIENS TABLEAUX"
   are the same object type; "REMBRANDT" / "REMBRANDT VAN RIJN" are the same artist).
3. For each group choose a canonical form (prefer the most complete/frequent one).

Return ONLY JSONL (one JSON object per line, no array, no markdown). Each line:
{{"canonical": "<canonical form>", "variants": ["<v1>", "<v2>", ...], "language": "<it|en|fr|de|other>", "count": <total count across all variants>}}

Rules:
- Every input value must appear in exactly one group's variants list (include canonical in variants too).
- If a value has no close match, it forms a group of one.
- language = language of the canonical form.
- count = sum of counts of all variants in the group.
""")


# ---------------------------------------------------------------------------
# Claude call (streaming, JSONL response)
# ---------------------------------------------------------------------------

def call_claude(client: anthropic.Anthropic, prompt: str) -> list[dict]:
    for attempt in range(3):
        max_tokens = MAX_TOKENS * (2 ** attempt)
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                extra_body={"output_config": {"effort": "low"}},
            ) as stream:
                response = stream.get_final_message()

            print(f"  [debug] stop_reason={response.stop_reason}, "
                  f"block_types={[b.type for b in response.content]}, "
                  f"max_tokens={max_tokens}")

            text_blocks = [b.text for b in response.content if b.type == "text"]
            if not text_blocks:
                print(f"  [warn] no text block (attempt {attempt+1}), retrying with larger budget...")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                continue

            raw = "".join(text_blocks).strip()

            if response.stop_reason == "max_tokens":
                print(f"  [warn] truncated at {max_tokens} tokens (attempt {attempt+1}), retrying...")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                continue

            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

            results = []
            bad = 0
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    bad += 1
            if bad:
                print(f"  [warn] skipped {bad} unparseable JSONL line(s)")
            return results

        except (anthropic.APIError, anthropic.RateLimitError) as e:
            print(f"  [warn] API error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return []

# def call_claude(client: anthropic.Anthropic, prompt: str) -> list[dict]:
#     for attempt in range(3):
#         max_tokens = MAX_TOKENS * (2 ** attempt)
#         try:
#             with client.messages.stream(
#                 model=MODEL,
#                 max_tokens=max_tokens,
#                 messages=[{"role": "user", "content": prompt}],
#             ) as stream:
#                 response = stream.get_final_message()
#
#             text_blocks = [b.text for b in response.content if b.type == "text"]
#             if not text_blocks:
#                 print(f"  [warn] no text block in response (attempt {attempt+1}), retrying...")
#                 if attempt < 2:
#                     time.sleep(2 ** attempt)
#                 continue
#             raw = "".join(text_blocks).strip()
#
#             if response.stop_reason == "max_tokens":
#                 print(f"  [warn] truncated at {max_tokens} tokens (attempt {attempt+1}), retrying...")
#                 if attempt < 2:
#                     time.sleep(2 ** attempt)
#                 continue
#
#             raw = re.sub(r"^```[a-z]*\n?", "", raw)
#             raw = re.sub(r"\n?```$", "", raw)
#
#             results = []
#             bad = 0
#             for line in raw.splitlines():
#                 line = line.strip()
#                 if not line:
#                     continue
#                 try:
#                     results.append(json.loads(line))
#                 except json.JSONDecodeError:
#                     bad += 1
#             if bad:
#                 print(f"  [warn] skipped {bad} unparseable JSONL line(s)")
#             return results
#
#         except (anthropic.APIError, anthropic.RateLimitError) as e:
#             print(f"  [warn] API error (attempt {attempt+1}): {e}")
#             if attempt < 2:
#                 time.sleep(2 ** attempt)
#     return []


# ---------------------------------------------------------------------------
# Load all entity CSVs
# ---------------------------------------------------------------------------

def load_all_entities(docs_dir: Path) -> list[dict]:
    """Load from all_entities.csv if present, else glob all entities.csv files."""
    combined = docs_dir / "all_entities.csv"
    if combined.exists():
        sources = [combined]
    else:
        sources = sorted(docs_dir.glob("*/entities.csv"))

    rows = []
    for path in sources:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows.extend(reader)
    print(f"Loaded {len(rows)} rows from {len(sources)} file(s)")
    return rows

# ---------------------------------------------------------------------------
# Recursive/hierarchical clustering (avoids giant single-shot merge prompts)
# ---------------------------------------------------------------------------
#
# def cluster_batch(client, entity_type, items, batch_size):
#     """items: list of (value, count) tuples. Returns list of group dicts."""
#     if len(items) <= batch_size:
#         items_block = "\n".join(f"{cnt} | {val}" for val, cnt in items)
#         prompt = LANG_AND_CLUSTER_PROMPT.format(entity_type=entity_type, items=items_block)
#         return call_claude(client, prompt)
#
#     chunks = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
#     all_groups = []
#     for i, chunk in enumerate(chunks):
#         print(f"    Sub-batch {i+1}/{len(chunks)} ({len(chunk)} values)...")
#         items_block = "\n".join(f"{cnt} | {val}" for val, cnt in chunk)
#         prompt = LANG_AND_CLUSTER_PROMPT.format(entity_type=entity_type, items=items_block)
#         all_groups.extend(call_claude(client, prompt))
#
#     canonical_to_variants: dict[str, list[str]] = {}
#     canonical_to_lang: dict[str, str] = {}
#     canonical_to_count: dict[str, int] = {}
#     for g in all_groups:
#         c = g.get("canonical")
#         if not c:
#             continue
#         canonical_to_variants.setdefault(c, []).extend(g.get("variants", [c]))
#         canonical_to_lang[c] = g.get("language", "other")
#         canonical_to_count[c] = canonical_to_count.get(c, 0) + g.get("count", 0)
#
#     next_level_items = [(c, canonical_to_count[c]) for c in canonical_to_variants]
#     merged = cluster_batch(client, entity_type, next_level_items, batch_size)
#
#     final_groups = []
#     for mg in merged:
#         all_variants = []
#         for c in mg.get("variants", [mg["canonical"]]):
#             all_variants.extend(canonical_to_variants.get(c, [c]))
#         final_groups.append({
#             "canonical": mg["canonical"],
#             "variants": sorted(set(all_variants)),
#             "language": mg.get("language", canonical_to_lang.get(mg["canonical"], "other")),
#             "count": mg.get("count", canonical_to_count.get(mg["canonical"], 0)),
#         })
#     return final_groups

def cluster_batch(client, entity_type, items, batch_size):
    """items: list of (value, count) tuples. One clustering pass per chunk,
    then merge exact-duplicate canonicals across chunks in Python (no recursion)."""
    chunks = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    all_groups = []
    for i, chunk in enumerate(chunks):
        print(f"    Batch {i+1}/{len(chunks)} ({len(chunk)} values)...")
        items_block = "\n".join(f"{cnt} | {val}" for val, cnt in chunk)
        prompt = LANG_AND_CLUSTER_PROMPT.format(entity_type=entity_type, items=items_block)
        all_groups.extend(call_claude(client, prompt))

    if len(chunks) <= 1:
        return all_groups

    # Merge duplicate canonicals produced across sibling chunks (Python-side, no extra API calls)
    canonical_to_variants: dict[str, list[str]] = {}
    canonical_to_lang: dict[str, str] = {}
    canonical_to_count: dict[str, int] = {}
    for g in all_groups:
        c = g.get("canonical")
        if not c:
            continue
        canonical_to_variants.setdefault(c, []).extend(g.get("variants", [c]))
        canonical_to_lang[c] = g.get("language", "other")
        canonical_to_count[c] = canonical_to_count.get(c, 0) + g.get("count", 0)

    return [
        {
            "canonical": c,
            "variants": sorted(set(canonical_to_variants[c])),
            "language": canonical_to_lang[c],
            "count": canonical_to_count[c],
        }
        for c in canonical_to_variants
    ]

# ---------------------------------------------------------------------------
# Process one entity type
# ---------------------------------------------------------------------------

def process_type(
    client: anthropic.Anthropic,
    entity_type: str,
    rows: list[dict],
    batch_size: int,
    out_path: Path,
) -> None:
    # Count occurrences
    values = [r["value"].strip().upper() for r in rows if r["type"] == entity_type and r["value"].strip()]
    counts: Counter = Counter(values)

    if not counts:
        print(f"  No values found for type '{entity_type}'")
        return

    print(f"  {entity_type}: {len(counts)} unique values, {sum(counts.values())} total occurrences")

    sorted_items = counts.most_common()
    all_groups = cluster_batch(client, entity_type, sorted_items, batch_size)

    # Write CSV
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["canonical", "variants", "language", "count"])
        writer.writeheader()
        for g in sorted(all_groups, key=lambda x: -x.get("count", 0)):
            writer.writerow({
                "canonical": g.get("canonical", ""),
                "variants": " | ".join(g.get("variants", [])),
                "language": g.get("language", "other"),
                "count": g.get("count", 0),
            })

    print(f"    → {len(all_groups)} canonical groups → {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Aggregate and cluster entities from catalogue CSVs.")
    parser.add_argument("--docs-dir", default="documents")
    parser.add_argument("--batch-size", type=int, default=200,
                        help="Max values per Claude call (default: 200)")
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    if not docs_dir.is_dir():
        raise SystemExit(f"Directory not found: {docs_dir}")

    client = anthropic.Anthropic()
    rows = load_all_entities(docs_dir)

    for entity_type, filename in [
        # ("school",      "schools.csv"),
        # ("object_type", "object_types.csv"),
        ("artist",      "artists.csv"),
    ]:
        print(f"\nProcessing {entity_type}...")
        process_type(client, entity_type, rows, args.batch_size, docs_dir / filename)

    print("\nDone.")


if __name__ == "__main__":
    main()
