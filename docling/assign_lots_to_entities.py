"""
assign_lots_to_entities.py

Per ogni catalogo:
  - esegue analyze_and_chunk_markdown UNA VOLTA su tutto all.md (stesso
    regex-chunking di ocr_chunking.py, importato senza modificarlo), cosi'
    il pattern viene rilevato sull'intero documento e non su segmenti corti
  - calcola la start_line di ciascun lotto trovato (posizione carattere -> riga)
  - per ogni entità di titolo in entities.csv, individua l'intervallo
    [line_number entità, line_number entità successiva) e le assegna tutti
    i lotti (globali) la cui start_line cade in quell'intervallo

Output: documents/all_entities_with_lots.csv
  dir_name, line_number, entity_value, entity_type, page_image, lot_nums, lot_count
"""
from __future__ import annotations
import re
import argparse
from pathlib import Path
import pandas as pd

#from ocr_chunking import analyze_and_chunk_markdown

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


# stessa regex usata in extract_catalogue_entities.py per individuare i titoli
TITLE_RE = re.compile(r"^#{1,2}\s+(.+)")


def is_title_line(lines: list[str], line_number: int) -> bool:
    """entities.csv non distingue entità da titolo vs da body: lo ricaviamo
    controllando se la riga a cui punta line_number e' effettivamente una
    riga di titolo (# / ##) in all.md."""
    idx = line_number - 1
    if idx < 0 or idx >= len(lines):
        return False
    return bool(TITLE_RE.match(lines[idx]))


def process_catalogue(dir_path: Path) -> pd.DataFrame:
    md_path = dir_path / "all.md"
    entities_path = dir_path / "entities.csv"
    if not md_path.exists() or not entities_path.exists():
        return pd.DataFrame()

    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    entities_df = pd.read_csv(entities_path)
    if entities_df.empty:
        return pd.DataFrame()

    # tieni solo le entità estratte da riga di titolo (# / ##)
    # entities_df = entities_df[
    #     entities_df["line_number"].apply(lambda ln: is_title_line(lines, int(ln)))
    # ]
    if entities_df.empty:
        return pd.DataFrame()

    entities_df = entities_df.sort_values("line_number").reset_index(drop=True)
    breakpoints = sorted(entities_df["line_number"].unique())

    # chunking una sola volta su tutto il documento
    try:
        result = analyze_and_chunk_markdown(text)
    except Exception as e:
        print(f"    [warn] {dir_path.name}: chunking fallito: {e}")
        return pd.DataFrame()

    # start_line di ogni lotto: posizione carattere del chunk nel testo -> riga.
    # Cerca in sequenza a partire dalla posizione del chunk precedente, cosi'
    # i chunk sono gia' in ordine di apparizione e si evitano match sbagliati
    # su prefissi duplicati altrove nel documento.
    lot_starts = []
    cursor = 0
    for ch in result["chunks"]:
        pos = text.find(ch["text"][:50], cursor)
        if pos == -1:
            pos = text.find(ch["text"][:50])  # fallback: cerca da capo
        if pos == -1:
            continue
        start_line = text.count("\n", 0, pos) + 1
        lot_starts.append((start_line, ch["num"]))
        cursor = pos + 1

    rows = []
    for i, start_line in enumerate(breakpoints):
        end_line = breakpoints[i + 1] if i + 1 < len(breakpoints) else len(lines) + 1

        lot_nums = [num for sl, num in lot_starts if start_line <= sl < end_line]

        ents_here = entities_df[entities_df["line_number"] == start_line]
        for _, ent in ents_here.iterrows():
            rows.append({
                "dir_name": ent["dir_name"],
                "line_number": start_line,
                "entity_value": ent["value"],
                "entity_type": ent["type"],
                "page_image": ent["page_image"],
                "lot_nums": ";".join(str(n) for n in lot_nums),
                "lot_count": len(lot_nums),
            })

    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs-dir", default="documents")
    ap.add_argument("--out", default="documents/all_entities_with_lots.csv")
    args = ap.parse_args()

    docs_dir = Path(args.docs_dir)
    all_rows = []
    for sub in sorted(docs_dir.iterdir()):
        if not sub.is_dir():
            continue
        df = process_catalogue(sub)
        if not df.empty:
            all_rows.append(df)
            print(f"{sub.name}: {len(df)} entità processate")

    out_df = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    out_df.to_csv(args.out, index=False, encoding="utf-8")
    print(f"→ {len(out_df)} righe → {args.out}")


if __name__ == "__main__":
    main()
