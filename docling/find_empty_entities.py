"""
find_empty_entities.py

Scansiona documents/<dir_name>/entities.csv per ogni sottodirectory e
stampa/salva la lista di quelli vuoti (solo header, o file mancante).

Usage:
    python3 find_empty_entities.py [--docs-dir documents] [--out empty_entities.txt]
"""

import csv
import argparse
from pathlib import Path


def is_empty_csv(csv_path: Path) -> bool:
    """True se il file non esiste, o contiene solo l'header (nessuna riga dati)."""
    if not csv_path.exists():
        return True
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            next(reader)  # salta l'header
        except StopIteration:
            return True  # file completamente vuoto, nemmeno header
        for row in reader:
            if any(cell.strip() for cell in row):
                return False  # trovata almeno una riga con dati
    return True


def main():
    parser = argparse.ArgumentParser(description="Trova gli entities.csv vuoti.")
    parser.add_argument("--docs-dir", default="documents")
    parser.add_argument("--out", default="empty_entities.txt")
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    if not docs_dir.is_dir():
        raise SystemExit(f"Directory non trovata: {docs_dir}")

    subdirs = sorted([d for d in docs_dir.iterdir() if d.is_dir()])
    empty = []

    for d in subdirs:
        csv_path = d / "entities.csv"
        if is_empty_csv(csv_path):
            empty.append(d.name)

    print(f"Controllate {len(subdirs)} directory.")
    print(f"Trovate {len(empty)} entities.csv vuote o mancanti:\n")
    for name in empty:
        print(f"  {name}")

    out_path = docs_dir / args.out
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(empty) + ("\n" if empty else ""))
    print(f"\nLista salvata in: {out_path}")


if __name__ == "__main__":
    main()
