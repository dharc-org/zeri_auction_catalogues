"""
extract_catalogue_entities.py

For each documents/<dir_name>/all.md:
  - Extracts entities from section titles (# / ##): object types, artist names, schools
  - (optional) Extracts entities from body text in chunks: periods, object types, schools
  - Resolves line number → page image using all_index.json
  - Writes documents/<dir_name>/entities.csv
  - Logs catalogues missing all_index.json to documents/errors.txt
  - Concatenates all per-dir CSVs into documents/all_entities.csv

Usage:
    python extract_catalogue_entities.py [--docs-dir documents] [--chunk-chars 8000] [--mode titles|body|both]
"""

from __future__ import annotations

import re
import json
import csv
import time
import argparse
import textwrap
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL = "claude-sonnet-5"
MAX_TOKENS = 8096
CHUNK_CHARS = 8000          # max chars per body chunk sent to Claude
TITLE_RE = re.compile(r"^#{1,2}\s+(.+)")

CSV_COLUMNS = ["dir_name", "value", "type", "line_number", "page_image"]

TITLE_PROMPT = textwrap.dedent("""\
You are an expert in auction catalogues of art and antiques.
Given the following numbered list of section titles from an auction catalogue, extract named entities.

Titles:
{titles}

Return ONLY a JSONL response (one JSON object per line, no array brackets, no markdown).
Each line must be a self-contained JSON object:
  {{"line_number": <original line number>, "value": "<entity text>", "type": "<artist|school|object_type>"}}

Rules:
- "artist": a named individual artist or maker
- "school": a geographic, cultural, or period school/workshop (e.g. "Fiamminga", "Lombarda", "Dutch School")
- "object_type": a category of object (e.g. "dipinti", "sculture", "ceramiche", "mobili")
- Emit one line per entity; a single title may produce multiple lines.
- If a title yields nothing, skip it.
- If nothing fits at all, output nothing.
""")

BODY_PROMPT = textwrap.dedent("""\
You are an expert in auction catalogues of art and antiques.
Given the following body text from an auction catalogue section, extract named entities.

Text:
{text}

Return ONLY a JSONL response (one JSON object per line, no array brackets, no markdown).
Each line must be a self-contained JSON object:
  {{"value": "<entity text>", "type": "<period|school|object_type>"}}

Rules:
- "period": a historical period or century (e.g. "XVIII secolo", "Rinascimento", "1600 ca.")
- "school": a geographic, cultural, or period school/workshop
- "object_type": a category of object
- Extract only clearly stated entities; do NOT invent.
- If nothing fits, output nothing.
""")


# ---------------------------------------------------------------------------
# Page index helpers
# ---------------------------------------------------------------------------

def build_page_lookup(index: dict) -> list[tuple[int, str]]:
    """Sorted list of (start_line, filename) from all_index.json."""
    entries = sorted(index.items(), key=lambda x: x[1])
    return [(line, fname) for fname, line in entries]


def resolve_page(line_number: int, page_lookup: list[tuple[int, str]]) -> str:
    """Return the page image filename (.jpg) for a given 1-based line number."""
    result_fname = page_lookup[0][1]
    for start_line, fname in page_lookup:
        if line_number >= start_line:
            result_fname = fname
        else:
            break
    return result_fname.replace(".md", ".jpg")


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def call_claude(client: anthropic.Anthropic, prompt: str) -> list[dict]:
    """Call Claude, return parsed JSONL as list of dicts. Retries up to 3 times, doubling max_tokens on truncation."""
    for attempt in range(3):
        max_tokens = MAX_TOKENS * (2 ** attempt)
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                response = stream.get_final_message()
            text_blocks = [b.text for b in response.content if b.type == "text"]
            if not text_blocks:
                print(f"    [warn] no text block in response (attempt {attempt+1}), retrying...")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                continue
            raw = "".join(text_blocks).strip()
            if response.stop_reason == "max_tokens":
                print(f"    [warn] response truncated at {max_tokens} tokens (attempt {attempt+1}), retrying...")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                continue
            # Strip markdown fences if present
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            # Parse JSONL: one object per line, skip blank lines and bad lines
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
                print(f"    [warn] skipped {bad} unparseable line(s) in JSONL response")
            return results
        except (anthropic.APIError, anthropic.RateLimitError) as e:
            print(f"    [warn] API error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return []


# ---------------------------------------------------------------------------
# Chunked body call
# ---------------------------------------------------------------------------

def call_claude_body_chunked(
    client: anthropic.Anthropic,
    text: str,
    body_start_line: int,
    chunk_chars: int,
) -> list[tuple[int, str, str]]:
    """
    Split body text into chunks of ~chunk_chars, respecting line boundaries.
    Calls Claude once per chunk. Returns list of (line_number, value, type).
    line_number points to the first line of each chunk within the file.
    """
    results = []
    body_lines = text.split("\n")

    # Build chunks: accumulate lines until chunk_chars is exceeded
    chunks: list[tuple[int, list[str]]] = []   # (first_line_no, lines_in_chunk)
    current_lines: list[str] = []
    current_chars = 0
    chunk_start_line = body_start_line

    for idx, line in enumerate(body_lines):
        line_len = len(line) + 1  # +1 for newline
        if current_chars + line_len > chunk_chars and current_lines:
            chunks.append((chunk_start_line, current_lines))
            chunk_start_line = body_start_line + idx
            current_lines = [line]
            current_chars = line_len
        else:
            current_lines.append(line)
            current_chars += line_len

    if current_lines:
        chunks.append((chunk_start_line, current_lines))

    for c_start_line, c_lines in chunks:
        chunk_text = "\n".join(c_lines).strip()
        if len(chunk_text) < 30:
            continue
        prompt = BODY_PROMPT.format(text=chunk_text)
        entities = call_claude(client, prompt)
        for ent in entities:
            value = ent.get("value", "").strip()
            etype = ent.get("type", "").strip()
            if value and etype:
                results.append((c_start_line, value, etype))

    return results


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def parse_md(md_path: Path) -> list[tuple[int, str, str]]:
    """
    Returns list of (line_number_1based, text, kind) where kind = 'title'|'body'.
    Body segments collect all non-title non-empty lines between two titles.
    """
    lines = md_path.read_text(encoding="utf-8").splitlines()
    segments: list[tuple[int, str, str]] = []

    body_lines: list[str] = []
    body_start: int | None = None

    def flush_body():
        if body_lines and body_start is not None:
            segments.append((body_start, "\n".join(body_lines), "body"))
        body_lines.clear()

    for i, line in enumerate(lines, start=1):
        m = TITLE_RE.match(line)
        if m:
            flush_body()
            body_start = None
            segments.append((i, m.group(1).strip(), "title"))
        else:
            stripped = line.strip()
            if stripped:
                if body_start is None:
                    body_start = i
                body_lines.append(stripped)

    flush_body()
    return segments


# ---------------------------------------------------------------------------
# Per-directory processing
# ---------------------------------------------------------------------------

def process_directory(
    dir_path: Path,
    client: anthropic.Anthropic,
    chunk_chars: int,
    error_log: list[str],
    mode: str = "both",
) -> list[dict]:
    """Process one catalogue directory. Returns list of CSV row dicts."""
    dir_name = dir_path.name
    md_path = dir_path / "all.md"
    index_path = dir_path / "all_index.json"

    if not md_path.exists():
        print(f"  [skip] {dir_name}: no all.md")
        return []

    csv_path = dir_path / "entities.csv"
    if csv_path.exists():
        print(f"  [skip] {dir_name}: entities.csv already exists")
        return []

    print(f"  Processing {dir_name}...")

    # Load page index (or log error)
    page_lookup: list[tuple[int, str]] = []
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
        page_lookup = build_page_lookup(index)
    else:
        msg = f"{dir_name}: missing all_index.json"
        print(f"    [warn] {msg}")
        error_log.append(msg)

    segments = parse_md(md_path)
    rows: list[dict] = []

    title_segments = [(ln, txt) for ln, txt, k in segments if k == "title"]
    body_segments  = [(ln, txt) for ln, txt, k in segments if k == "body"]

    # --- Titles: one batch call for the whole catalogue ---
    if mode in ("titles", "both") and title_segments:
        titles_block = "\n".join(f"[line {ln}] {txt}" for ln, txt in title_segments)
        prompt = TITLE_PROMPT.format(titles=titles_block)
        entities = call_claude(client, prompt)
        for ent in entities:
            value = ent.get("value", "").strip()
            etype = ent.get("type", "").strip()
            line_no = ent.get("line_number")
            if not value or not etype or line_no is None:
                continue
            try:
                line_no = int(line_no)
            except (ValueError, TypeError):
                continue
            page_image = resolve_page(line_no, page_lookup) if page_lookup else ""
            rows.append({
                "dir_name": dir_name,
                "value": value,
                "type": etype,
                "line_number": line_no,
                "page_image": page_image,
            })

    # --- Body: chunked calls ---
    if mode in ("body", "both"):
        for line_no, text in body_segments:
            entity_tuples = call_claude_body_chunked(
                client, text, line_no, chunk_chars
            )
            for ent_line_no, value, etype in entity_tuples:
                page_image = resolve_page(ent_line_no, page_lookup) if page_lookup else ""
                rows.append({
                    "dir_name": dir_name,
                    "value": value,
                    "type": etype,
                    "line_number": ent_line_no,
                    "page_image": page_image,
                })

    # Write per-dir CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"    → {len(rows)} entities → {csv_path}")
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extract entities from auction catalogue markdown files.")
    parser.add_argument("--docs-dir", default="documents", help="Root documents directory (default: documents)")
    parser.add_argument("--chunk-chars", type=int, default=CHUNK_CHARS,
                        help=f"Max chars per body chunk sent to Claude (default: {CHUNK_CHARS})")
    parser.add_argument("--mode", choices=["titles", "body", "both"], default="both",
                        help="What to process: titles only, body only, or both (default: both)")
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    if not docs_dir.is_dir():
        raise SystemExit(f"Documents directory not found: {docs_dir}")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    subdirs = sorted([d for d in docs_dir.iterdir() if d.is_dir()])
    print(f"Found {len(subdirs)} directories under {docs_dir}\n")

    error_log: list[str] = []
    all_rows: list[dict] = []

    for subdir in subdirs:
        try:
            rows = process_directory(subdir, client, args.chunk_chars, error_log, args.mode)
            all_rows.extend(rows)
        except Exception as e:
            msg = f"{subdir.name}: unexpected error: {e}"
            print(f"  [error] {msg}")
            error_log.append(msg)

    # Write errors.txt
    error_path = docs_dir / "errors.txt"
    with open(error_path, "w", encoding="utf-8") as f:
        if error_log:
            f.write("\n".join(error_log) + "\n")
        else:
            f.write("No errors.\n")
    print(f"\nError log → {error_path} ({len(error_log)} entries)")

    # Write concatenated CSV
    all_csv_path = docs_dir / "all_entities.csv"
    with open(all_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Combined CSV → {all_csv_path} ({len(all_rows)} total rows)")

    print("\nDone.")


if __name__ == "__main__":
    main()
# """
# extract_catalogue_entities.py
#
# For each documents/<dir_name>/all.md:
#   - Extracts entities from section titles (# / ##): object types, artist names, schools
#   - Extracts entities from body text in chunks: periods, object types, schools
#   - Resolves line number → page image using all_index.json
#   - Writes documents/<dir_name>/entities.csv
#   - Logs catalogues missing all_index.json to documents/errors.txt
#   - Concatenates all per-dir CSVs into documents/all_entities.csv
#
# Usage:
#     python extract_catalogue_entities.py [--docs-dir documents] [--chunk-chars 8000] [--mode titles|body|both]
# """
#
# from __future__ import annotations
#
# import re
# import json
# import csv
# import time
# import argparse
# import textwrap
# from pathlib import Path
#
# import anthropic
#
# # ---------------------------------------------------------------------------
# # Config
# # ---------------------------------------------------------------------------
# MODEL = "claude-sonnet-4-20250514"
# MAX_TOKENS = 2048
# CHUNK_CHARS = 8000          # max chars per body chunk sent to Claude
# TITLE_RE = re.compile(r"^#{1,2}\s+(.+)")
#
# CSV_COLUMNS = ["dir_name", "value", "type", "line_number", "page_image"]
#
# TITLE_PROMPT = textwrap.dedent("""\
# You are an expert in auction catalogues of art and antiques.
# Given the following section title from an auction catalogue, extract named entities.
#
# Title: {title}
#
# Return ONLY a JSON array (no markdown, no explanation). Each element:
#   {{"value": "<entity text>", "type": "<artist|school|object_type>"}}
#
# Rules:
# - "artist": a named individual artist or maker
# - "school": a geographic, cultural, or period school/workshop (e.g. "Fiamminga", "Lombarda", "Dutch School")
# - "object_type": a category of object (e.g. "dipinti", "sculture", "ceramiche", "mobili")
# - If nothing fits, return []
# """)
#
# BODY_PROMPT = textwrap.dedent("""\
# You are an expert in auction catalogues of art and antiques.
# Given the following body text from an auction catalogue section, extract named entities.
#
# Text:
# {text}
#
# Return ONLY a JSON array (no markdown, no explanation). Each element:
#   {{"value": "<entity text>", "type": "<period|school|object_type>"}}
#
# Rules:
# - "period": a historical period or century (e.g. "XVIII secolo", "Rinascimento", "1600 ca.")
# - "school": a geographic, cultural, or period school/workshop
# - "object_type": a category of object
# - Extract only clearly stated entities; do NOT invent.
# - If nothing fits, return []
# """)
#
#
# # ---------------------------------------------------------------------------
# # Page index helpers
# # ---------------------------------------------------------------------------
#
# def build_page_lookup(index: dict) -> list[tuple[int, str]]:
#     """Sorted list of (start_line, filename) from all_index.json."""
#     entries = sorted(index.items(), key=lambda x: x[1])
#     return [(line, fname) for fname, line in entries]
#
#
# def resolve_page(line_number: int, page_lookup: list[tuple[int, str]]) -> str:
#     """Return the page image filename (.jpg) for a given 1-based line number."""
#     result_fname = page_lookup[0][1]
#     for start_line, fname in page_lookup:
#         if line_number >= start_line:
#             result_fname = fname
#         else:
#             break
#     return result_fname.replace(".md", ".jpg")
#
#
# # ---------------------------------------------------------------------------
# # Claude API call
# # ---------------------------------------------------------------------------
#
# def call_claude(client: anthropic.Anthropic, prompt: str) -> list[dict]:
#     """Call Claude, return parsed JSON array. Retries up to 3 times."""
#     for attempt in range(3):
#         try:
#             response = client.messages.create(
#                 model=MODEL,
#                 max_tokens=MAX_TOKENS,
#                 messages=[{"role": "user", "content": prompt}],
#             )
#             raw = response.content[0].text.strip()
#             raw = re.sub(r"^```[a-z]*\n?", "", raw)
#             raw = re.sub(r"\n?```$", "", raw)
#             return json.loads(raw)
#         except json.JSONDecodeError as e:
#             print(f"    [warn] JSON parse error (attempt {attempt+1}): {e}")
#             if attempt < 2:
#                 time.sleep(2 ** attempt)
#         except (anthropic.APIError, anthropic.RateLimitError) as e:
#             print(f"    [warn] API error (attempt {attempt+1}): {e}")
#             if attempt < 2:
#                 time.sleep(2 ** attempt)
#     return []
#
#
# # ---------------------------------------------------------------------------
# # Chunked body call
# # ---------------------------------------------------------------------------
#
# def call_claude_body_chunked(
#     client: anthropic.Anthropic,
#     text: str,
#     body_start_line: int,
#     chunk_chars: int,
# ) -> list[tuple[int, str, str]]:
#     """
#     Split body text into chunks of ~chunk_chars, respecting line boundaries.
#     Calls Claude once per chunk. Returns list of (line_number, value, type).
#     line_number points to the first line of each chunk within the file.
#     """
#     results = []
#     body_lines = text.split("\n")
#
#     # Build chunks: accumulate lines until chunk_chars is exceeded
#     chunks: list[tuple[int, list[str]]] = []   # (first_line_no, lines_in_chunk)
#     current_lines: list[str] = []
#     current_chars = 0
#     chunk_start_line = body_start_line
#
#     for idx, line in enumerate(body_lines):
#         line_len = len(line) + 1  # +1 for newline
#         if current_chars + line_len > chunk_chars and current_lines:
#             chunks.append((chunk_start_line, current_lines))
#             chunk_start_line = body_start_line + idx
#             current_lines = [line]
#             current_chars = line_len
#         else:
#             current_lines.append(line)
#             current_chars += line_len
#
#     if current_lines:
#         chunks.append((chunk_start_line, current_lines))
#
#     for c_start_line, c_lines in chunks:
#         chunk_text = "\n".join(c_lines).strip()
#         if len(chunk_text) < 30:
#             continue
#         prompt = BODY_PROMPT.format(text=chunk_text)
#         entities = call_claude(client, prompt)
#         for ent in entities:
#             value = ent.get("value", "").strip()
#             etype = ent.get("type", "").strip()
#             if value and etype:
#                 results.append((c_start_line, value, etype))
#
#     return results
#
#
# # ---------------------------------------------------------------------------
# # Markdown parser
# # ---------------------------------------------------------------------------
#
# def parse_md(md_path: Path) -> list[tuple[int, str, str]]:
#     """
#     Returns list of (line_number_1based, text, kind) where kind = 'title'|'body'.
#     Body segments collect all non-title non-empty lines between two titles.
#     """
#     lines = md_path.read_text(encoding="utf-8").splitlines()
#     segments: list[tuple[int, str, str]] = []
#
#     body_lines: list[str] = []
#     body_start: int | None = None
#
#     def flush_body():
#         if body_lines and body_start is not None:
#             segments.append((body_start, "\n".join(body_lines), "body"))
#         body_lines.clear()
#
#     for i, line in enumerate(lines, start=1):
#         m = TITLE_RE.match(line)
#         if m:
#             flush_body()
#             body_start = None
#             segments.append((i, m.group(1).strip(), "title"))
#         else:
#             stripped = line.strip()
#             if stripped:
#                 if body_start is None:
#                     body_start = i
#                 body_lines.append(stripped)
#
#     flush_body()
#     return segments
#
#
# # ---------------------------------------------------------------------------
# # Per-directory processing
# # ---------------------------------------------------------------------------
#
# def process_directory(
#     dir_path: Path,
#     client: anthropic.Anthropic,
#     chunk_chars: int,
#     error_log: list[str],
#     mode: str = "both",
# ) -> list[dict]:
#     """Process one catalogue directory. Returns list of CSV row dicts."""
#     dir_name = dir_path.name
#     md_path = dir_path / "all.md"
#     index_path = dir_path / "all_index.json"
#
#     if not md_path.exists():
#         print(f"  [skip] {dir_name}: no all.md")
#         return []
#
#     print(f"  Processing {dir_name}...")
#
#     # Load page index (or log error)
#     page_lookup: list[tuple[int, str]] = []
#     if index_path.exists():
#         with open(index_path, encoding="utf-8") as f:
#             index = json.load(f)
#         page_lookup = build_page_lookup(index)
#     else:
#         msg = f"{dir_name}: missing all_index.json"
#         print(f"    [warn] {msg}")
#         error_log.append(msg)
#
#     segments = parse_md(md_path)
#     rows: list[dict] = []
#
#     for line_no, text, kind in segments:
#         if kind == "title" and mode in ("titles", "both"):
#             prompt = TITLE_PROMPT.format(title=text)
#             entities = call_claude(client, prompt)
#             for ent in entities:
#                 value = ent.get("value", "").strip()
#                 etype = ent.get("type", "").strip()
#                 if not value or not etype:
#                     continue
#                 page_image = resolve_page(line_no, page_lookup) if page_lookup else ""
#                 rows.append({
#                     "dir_name": dir_name,
#                     "value": value,
#                     "type": etype,
#                     "line_number": line_no,
#                     "page_image": page_image,
#                 })
#         elif kind == "body" and mode in ("body", "both"):
#             # Body: chunk and call Claude multiple times as needed
#             entity_tuples = call_claude_body_chunked(
#                 client, text, line_no, chunk_chars
#             )
#             for ent_line_no, value, etype in entity_tuples:
#                 page_image = resolve_page(ent_line_no, page_lookup) if page_lookup else ""
#                 rows.append({
#                     "dir_name": dir_name,
#                     "value": value,
#                     "type": etype,
#                     "line_number": ent_line_no,
#                     "page_image": page_image,
#                 })
#
#     # Write per-dir CSV
#     csv_path = dir_path / "entities.csv"
#     with open(csv_path, "w", newline="", encoding="utf-8") as f:
#         writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
#         writer.writeheader()
#         writer.writerows(rows)
#
#     print(f"    → {len(rows)} entities → {csv_path}")
#     return rows
#
#
# # ---------------------------------------------------------------------------
# # Main
# # ---------------------------------------------------------------------------
#
# def main():
#     parser = argparse.ArgumentParser(description="Extract entities from auction catalogue markdown files.")
#     parser.add_argument("--docs-dir", default="documents", help="Root documents directory (default: documents)")
#     parser.add_argument("--chunk-chars", type=int, default=CHUNK_CHARS,
#                         help=f"Max chars per body chunk sent to Claude (default: {CHUNK_CHARS})")
#     parser.add_argument("--mode", choices=["titles", "body", "both"], default="both",
#                         help="What to process: titles only, body only, or both (default: both)")
#     args = parser.parse_args()
#
#     docs_dir = Path(args.docs_dir)
#     if not docs_dir.is_dir():
#         raise SystemExit(f"Documents directory not found: {docs_dir}")
#
#     client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
#
#     subdirs = sorted([d for d in docs_dir.iterdir() if d.is_dir()])
#     print(f"Found {len(subdirs)} directories under {docs_dir}\n")
#
#     error_log: list[str] = []
#     all_rows: list[dict] = []
#
#     for subdir in subdirs:
#         rows = process_directory(subdir, client, args.chunk_chars, error_log, args.mode)
#         all_rows.extend(rows)
#
#     # Write errors.txt
#     error_path = docs_dir / "errors.txt"
#     with open(error_path, "w", encoding="utf-8") as f:
#         if error_log:
#             f.write("\n".join(error_log) + "\n")
#         else:
#             f.write("No errors.\n")
#     print(f"\nError log → {error_path} ({len(error_log)} entries)")
#
#     # Write concatenated CSV
#     all_csv_path = docs_dir / "all_entities.csv"
#     with open(all_csv_path, "w", newline="", encoding="utf-8") as f:
#         writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
#         writer.writeheader()
#         writer.writerows(all_rows)
#     print(f"Combined CSV → {all_csv_path} ({len(all_rows)} total rows)")
#
#     print("\nDone.")
#
#
# if __name__ == "__main__":
#     main()
