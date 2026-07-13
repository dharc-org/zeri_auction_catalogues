"""
rebuild_all_entities.py

Concatena tutti i documents/<dir_name>/entities.csv esistenti in
documents/all_entities.csv, senza richiamare Claude (puro I/O).
Utile dopo un crash che ha interrotto extract_catalogue_entities.py
prima della scrittura finale del CSV combinato.

Usage:
    python3 rebuild_all_entities.py [--docs-dir documents]
"""

import csv
import argparse
from pathlib import Path

CSV_COLUMNS = ["dir_name", "value", "type", "line_number", "page_image"]


def main():
    parser = argparse.ArgumentParser(description="Rigenera all_entities.csv da tutti gli entities.csv esistenti.")
    parser.add_argument("--docs-dir", default="documents")
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    if not docs_dir.is_dir():
        raise SystemExit(f"Directory non trovata: {docs_dir}")

    subdirs = sorted([d for d in docs_dir.iterdir() if d.is_dir()])

    all_rows = []
    n_dirs_with_data = 0
    n_dirs_missing = 0

    for d in subdirs:
        csv_path = d / "entities.csv"
        if not csv_path.exists():
            n_dirs_missing += 1
            continue
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if rows:
            all_rows.extend(rows)
            n_dirs_with_data += 1
        else:
            n_dirs_missing += 1

    out_path = docs_dir / "all_entities.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Directory totali: {len(subdirs)}")
    print(f"Directory con entities.csv non-vuoto: {n_dirs_with_data}")
    print(f"Directory vuote/mancanti: {n_dirs_missing}")
    print(f"Righe totali scritte: {len(all_rows)}")
    print(f"→ {out_path}")


if __name__ == "__main__":
    main()
