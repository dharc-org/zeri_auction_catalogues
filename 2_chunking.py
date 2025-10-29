import re
import csv
import sys
from collections import Counter
from pathlib import Path

def analyze_and_chunk_markdown(text):
    # Candidate regex patterns to test for recurrence
    regex_patterns = {
        # Generic pattern: headings or plain paragraphs
        "generic": re.compile(
            r'^(?:\|?\s*)?(?:#{1,6}\s*)?(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
        # Markdown header style
        "header": re.compile(
            r'^(?:\|?\s*)?#{1,6}\s*(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
        # Bullet lists like "- 2 - Title" or "* 3. Title"
        "bullet": re.compile(
            r'^(?:\|?\s*)?(?:[-*]\s*)?(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
        # Table-style lines that explicitly begin with "| "
        "pipe_prefix": re.compile(
            r'^\|\s*(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
    }

    # Find matches for all regexes
    all_matches = []
    for name, pattern in regex_patterns.items():
        matches = list(pattern.finditer(text))
        all_matches.append((name, matches))

    # Identify which pattern captures the most matches
    most_common = max(all_matches, key=lambda x: len(x[1]))
    pattern_name, matches = most_common

    print(f"🧩 Most recurring pattern: {pattern_name} ({len(matches)} occurrences)")

    # Extract chunk boundaries
    positions = [(m.start(), m.group("num"), m.group("title")) for m in matches]
    positions.sort(key=lambda x: x[0])

    # Build chunks
    chunks = []
    for i, (pos, num, title) in enumerate(positions):
        start = pos
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chunk_text = text[start:end].strip()
        chunks.append({
            "num": num.strip(),
            "title": title.strip(),
            "text": chunk_text,
            "index": i + 1
        })

    # --- Check numeric consistency ---
    inconsistencies = []
    last_num = None
    for ch in chunks:
        try:
            num_val = int(re.sub(r'\D', '', ch["num"]))  # handles I6 → 6, ignores letters
        except ValueError:
            num_val = None

        if last_num and num_val:
            if num_val != last_num + 1:
                inconsistencies.append({
                    "prev_num": last_num,
                    "current_num": num_val,
                    "title": ch["title"]
                })
        if num_val:
            last_num = num_val

    return {
        "pattern": pattern_name,
        "chunks": chunks,
        "inconsistencies": inconsistencies
    }


def save_chunks_to_csv(chunks, output_csv):
    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["index", "num", "title", "text"])
        writer.writeheader()
        for ch in chunks:
            writer.writerow(ch)
    print(f"💾 Saved {len(chunks)} chunks to {output_csv}")


def main():
    parent_folder = Path("./imgs_benchmark")

    if not parent_folder.exists():
        print(f"❌ Parent folder not found: {parent_folder}")
        sys.exit(1)

    all_chunks = []
    all_inconsistencies = []

    # Iterate over all catalogue subfolders
    for catalogue_dir in sorted(parent_folder.iterdir()):
        if not catalogue_dir.is_dir():
            continue

        catalogue_id = catalogue_dir.name
        input_file = catalogue_dir / "md" / "all.md"
        output_file = catalogue_dir / "md" / "chunks.csv"

        if not input_file.exists():
            print(f"⚠️ Skipping {catalogue_id} — missing {input_file}")
            continue

        print(f"\n📘 Processing catalogue: {catalogue_id}")
        text = input_file.read_text(encoding="utf-8")

        result = analyze_and_chunk_markdown(text)
        chunks = result["chunks"]
        inconsistencies = result["inconsistencies"]

        # Add catalogue_id + context metadata
        for ch in chunks:
            ch["catalogue_id"] = catalogue_id
            ch["line_start"] = text[:ch["text"] and text.index(ch["text"])].count("\n") + 1 \
                if ch["text"] in text else None

        for inc in inconsistencies:
            inc["catalogue_id"] = catalogue_id
            # Find the related chunk
            match = next((c for c in chunks if c["num"].isdigit() and int(re.sub(r'\D', '', c["num"])) == inc["current_num"]), None)
            if match:
                inc["excerpt"] = match["text"][:200].replace("\n", " ") + "..."
                inc["line_start"] = match.get("line_start")
            else:
                inc["excerpt"] = "(not found)"
                inc["line_start"] = None

        # --- Save individual chunks CSV ---
        with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["catalogue_id", "index", "num", "title", "text", "line_start"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for ch in chunks:
                writer.writerow(ch)

        print(f"💾 Saved {len(chunks)} chunks to {output_file}")

        # Append to global collections
        all_chunks.extend(chunks)
        all_inconsistencies.extend(inconsistencies)

        # Log inconsistencies
        if inconsistencies:
            print(f"⚠️ {len(inconsistencies)} inconsistencies in {catalogue_id}:")
            for inc in inconsistencies:
                print(f"  Between {inc['prev_num']} and {inc['current_num']} → {inc['title']}")
        else:
            print("✅ All numbers seem sequential.")

    # --- Save combined CSVs ---
    all_chunks_csv = parent_folder / "all_chunks.csv"
    all_inconsistencies_csv = parent_folder / "inconsistencies.csv"

    # Combined chunks
    with open(all_chunks_csv, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["catalogue_id", "index", "num", "title", "text", "line_start"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for ch in all_chunks:
            writer.writerow(ch)

    # Combined inconsistencies with context
    with open(all_inconsistencies_csv, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["catalogue_id", "prev_num", "current_num", "title", "excerpt", "line_start"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for inc in all_inconsistencies:
            writer.writerow(inc)

    print(f"\n📊 Summary files written to {parent_folder}:")
    print(f"  • {all_chunks_csv.name} — {len(all_chunks)} total chunks")
    print(f"  • {all_inconsistencies_csv.name} — {len(all_inconsistencies)} inconsistencies with context")




if __name__ == "__main__":
    main()
