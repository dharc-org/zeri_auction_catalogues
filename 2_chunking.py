import re
import csv
from pathlib import Path
import pandas as pd


# ---------------------------------------------------------
# 1️⃣ CHUNK DETECTION
# ---------------------------------------------------------
def analyze_and_chunk_markdown(text):
    """
    Splits the Markdown into chunks based on the most frequent numbering pattern.
    """
    regex_patterns = {
        "generic": re.compile(
            r'^(?:\|?\s*)?(?:#{1,6}\s*)?(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
        "header": re.compile(
            r'^(?:\|?\s*)?#{1,6}\s*(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
        "bullet": re.compile(
            r'^(?:\|?\s*)?(?:[-*]\s*)?(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
        "pipe_prefix": re.compile(
            r'^\|\s*(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
    }

    # Detect the most common numbering pattern
    all_matches = [(name, list(p.finditer(text))) for name, p in regex_patterns.items()]
    pattern_name, matches = max(all_matches, key=lambda x: len(x[1]))

    print(f"🧩 Most recurring pattern: {pattern_name} ({len(matches)} occurrences)")

    # Build chunks
    positions = [(m.start(), m.group("num"), m.group("title")) for m in matches]
    positions.sort(key=lambda x: x[0])

    chunks = []
    for i, (pos, num, title) in enumerate(positions):
        start = pos
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chunk_text = text[start:end].strip()
        chunks.append({
            "index": i + 1,
            "num": num.strip(),
            "title": title.strip(),
            "text": chunk_text,
        })

    return {"pattern": pattern_name, "chunks": chunks}


# ---------------------------------------------------------
# 2️⃣ POST-PROCESSING FUNCTIONS
# ---------------------------------------------------------
def split_based_on_gap(df):
    """
    Split rows when missing lot numbers are found embedded in text
    and they exactly fill the numeric gap.
    """
    lot_pattern = re.compile(r'(?:^|\n|\| |## |### |# |\s|•)(\d{1,3})(?:\s*[\.\-–—]\s*)(?=[A-ZÀ-ÖØ-öø-ÿ])')
    split_rows = []

    df = df.sort_values(['catalogue_id', 'index']).reset_index(drop=True)

    for i, row in df.iterrows():
        catalogue_id = row['catalogue_id']
        text = str(row['text'])
        index = row['index']

        try:
            current_num = int(re.sub(r'\D', '', str(row['num'])))
        except:
            split_rows.append(row.to_dict())
            continue

        # Determine next number
        next_num = None
        if i + 1 < len(df) and df.loc[i + 1, 'catalogue_id'] == catalogue_id:
            try:
                next_num = int(re.sub(r'\D', '', str(df.loc[i + 1, 'num'])))
            except:
                pass

        if not next_num:
            split_rows.append(row.to_dict())
            continue

        gap = next_num - current_num - 1
        if gap <= 0:
            split_rows.append(row.to_dict())
            continue

        embedded_nums = sorted(set(
            int(m.group(1)) for m in lot_pattern.finditer(text)
            if current_num < int(m.group(1)) < next_num
        ))

        if len(embedded_nums) == gap and embedded_nums == list(range(current_num + 1, next_num)):
            print(f"🔍 Splitting row {index} ({current_num}) → found embedded lots {embedded_nums}")
            matches = list(lot_pattern.finditer(text))
            segments = []
            for j, m in enumerate(matches):
                start = m.start()
                end = matches[j + 1].start() if j + 1 < len(matches) else len(text)
                seg_text = text[start:end].strip()
                num_match = re.match(lot_pattern, seg_text)
                if not num_match:
                    continue
                seg_num = int(num_match.group(1))
                if current_num <= seg_num < next_num:
                    segments.append((seg_num, seg_text))

            for seg_num, seg_text in segments:
                split_rows.append({
                    "catalogue_id": catalogue_id,
                    "index": f"{index}.{seg_num}",
                    "num": seg_num,
                    "title": seg_text.split('\n', 1)[0][:120],
                    "text": seg_text.strip(),
                })
        else:
            split_rows.append(row.to_dict())

    new_df = pd.DataFrame(split_rows)
    new_df['index'] = range(1, len(new_df) + 1)
    return new_df


def merge_sandwiched_errors(df):
    """
    Merge OCR errors where a wrong number is sandwiched between two sequential ones.
    """
    fixed_rows = []

    for catalogue_id, group in df.groupby('catalogue_id', sort=False):
        group = group.sort_values('index').reset_index(drop=True)
        rows = group.to_dict(orient='records')
        merged_rows = []
        i = 0
        while i < len(rows):
            current = rows[i]
            def parse_num(val):
                try:
                    return int(str(val).strip().strip('.-–—'))
                except:
                    return None

            curr_num = parse_num(current['num'])
            prev_num = parse_num(rows[i - 1]['num']) if i > 0 else None
            next_num = parse_num(rows[i + 1]['num']) if i + 1 < len(rows) else None

            if prev_num and next_num and prev_num + 1 == next_num and curr_num != prev_num + 1:
                merged = merged_rows.pop() if merged_rows else rows[i - 1].copy()
                merged['title'] += " " + str(current['title'])
                merged['text'] += " " + str(current['text'].strip())
                merged_rows.append(merged)
                i += 1
                continue

            merged_rows.append(current)
            i += 1

        for idx, row in enumerate(merged_rows):
            row['index'] = idx + 1
        fixed_rows.extend(merged_rows)

    return pd.DataFrame(fixed_rows)


def recalc_inconsistencies(df):
    """
    Recalculate inconsistencies *after* postprocessing.
    """
    inconsistencies = []

    for catalogue_id, group in df.groupby("catalogue_id"):
        group = group.sort_values("index")
        last_num = None

        for _, row in group.iterrows():
            try:
                num_val = int(re.sub(r'\D', '', str(row["num"])))
            except:
                num_val = None

            if last_num and num_val and num_val != last_num + 1:
                inconsistencies.append({
                    "catalogue_id": catalogue_id,
                    "prev_num": last_num,
                    "current_num": num_val,
                    "title": row["title"],
                    "excerpt": row["text"].strip()
                })
            if num_val:
                last_num = num_val

    return pd.DataFrame(inconsistencies)


# ---------------------------------------------------------
# 3️⃣ MAIN
# ---------------------------------------------------------
def main():
    parent_folder = Path("./imgs_benchmark")

    if not parent_folder.exists():
        print(f"❌ Parent folder not found: {parent_folder}")
        return

    all_chunks = []
    all_inconsistencies = []

    for catalogue_dir in sorted(parent_folder.iterdir()):
        if not catalogue_dir.is_dir():
            continue

        catalogue_id = catalogue_dir.name
        input_file = catalogue_dir / "md" / "all.md"
        output_file = catalogue_dir / "md" / f"{catalogue_id}_chunks.csv"

        if not input_file.exists():
            print(f"⚠️ Skipping {catalogue_id} — missing {input_file}")
            continue

        print(f"\n📘 Processing catalogue: {catalogue_id}")
        text = input_file.read_text(encoding="utf-8")

        # --- Step 1: Initial chunking ---
        result = analyze_and_chunk_markdown(text)
        chunks = result["chunks"]
        for ch in chunks:
            ch["catalogue_id"] = catalogue_id

        chunks_df = pd.DataFrame(chunks)

        # --- Step 2: Postprocessing ---
        chunks_df = split_based_on_gap(chunks_df)
        chunks_df = merge_sandwiched_errors(chunks_df)

        # --- Step 3: Recalculate inconsistencies ---
        inconsistencies_df = recalc_inconsistencies(chunks_df)

        # --- Step 4: Save outputs ---
        chunks_df.to_csv(output_file, index=False, encoding="utf-8")
        print(f"💾 Saved {len(chunks_df)} chunks to {output_file}")

        all_chunks.append(chunks_df)
        all_inconsistencies.append(inconsistencies_df)

    # --- Combine and export all results ---
    if all_chunks:
        all_chunks_df = pd.concat(all_chunks, ignore_index=True)
        all_chunks_df.to_csv(parent_folder / "all_chunks.csv", index=False, encoding="utf-8")

    if all_inconsistencies:
        all_inconsistencies_df = pd.concat(all_inconsistencies, ignore_index=True)
        all_inconsistencies_df.to_csv(parent_folder / "all_inconsistencies.csv", index=False, encoding="utf-8")

    print("\n📊 Finished processing all catalogues.")


if __name__ == "__main__":
    main()
