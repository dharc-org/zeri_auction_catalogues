"""
assign_entities_via_title_match.py

Per ogni lotto (chunk) di un catalogo con reviewed=1 in documents.db:
  - cerca in documents/<catalogue_id>/all.md la riga più simile (fuzzy match)
    al valore "title" del lotto (il testo può differire leggermente perché
    rivisto a mano)
  - trova la entità di titolo (artist/school/object_type, da entities.csv)
    con line_number più vicina PRECEDENTE a quella riga
  - assegna quell'entità al lotto

Output: <out-dir>/<catalogue_id>.csv, uno per catalogo, con colonne:
  chunk_id, num, title, matched_line, match_score, artist, school, object_type

Richiede: rapidfuzz (pip install rapidfuzz)
"""
from __future__ import annotations
import re
import sqlite3
import argparse
from pathlib import Path
import pandas as pd
from rapidfuzz import fuzz, process

TITLE_RE = re.compile(r"^#{1,2}\s+(.+)")
MIN_MATCH_SCORE = 60  # sotto questa soglia il match posizionale è considerato inaffidabile
WINDOW_SIZES = [30, 100, 500, None]  # None = tutte le righe rimanenti
FALLBACK_MIN_SCORE = 85  # soglia per il fallback: valore entità contenuto nel title


def is_title_line(lines: list[str], line_number: int) -> bool:
    idx = line_number - 1
    if idx < 0 or idx >= len(lines):
        return False
    return bool(TITLE_RE.match(lines[idx]))


def fetch_reviewed_catalogue_ids(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT id FROM catalogues WHERE reviewed = 1 ORDER BY id")
    return [r[0] for r in cur.fetchall()]


def fetch_chunks_for_catalogue(conn: sqlite3.Connection, catalogue_id: str) -> pd.DataFrame:
    return pd.read_sql_query("""
        SELECT id AS chunk_db_id, chunk_index, num, title
        FROM chunks
        WHERE catalogue_id = ?
        ORDER BY chunk_index
    """, conn, params=(catalogue_id,))


def load_title_entities(dir_path: Path, lines: list[str]) -> dict[int, list[tuple[str, str]]]:
    """line_number (di riga titolo) -> [(value, type), ...]"""
    entities_path = dir_path / "entities.csv"
    if not entities_path.exists():
        return {}

    entities_df = pd.read_csv(entities_path)
    if entities_df.empty:
        return {}

    entities_df = entities_df[
        entities_df["line_number"].apply(lambda ln: is_title_line(lines, int(ln)))
    ]

    by_line: dict[int, list[tuple[str, str]]] = {}
    for _, row in entities_df.iterrows():
        by_line.setdefault(int(row["line_number"]), []).append((row["value"], row["type"]))
    return by_line


def find_best_match_in_window(title: str, candidates: list[tuple[int, str]],
                               start_idx: int, window_size: int | None):
    """Cerca il miglior match SOLO tra i candidati da start_idx in poi,
    limitati a window_size elementi (None = fino in fondo)."""
    end_idx = len(candidates) if window_size is None else min(start_idx + window_size, len(candidates))
    window = candidates[start_idx:end_idx]
    if not window:
        return None, 0

    texts = [c[1] for c in window]
    match = process.extractOne(title, texts, scorer=fuzz.token_sort_ratio)
    if match is None:
        return None, 0

    _, score, local_idx = match
    return window[local_idx][0], score  # (line_number, score)


def advance_cursor(candidates: list[tuple[int, str]], cursor_idx: int, matched_line: int) -> int:
    """Trova l'indice del primo candidato con line_number > matched_line."""
    for i in range(cursor_idx, len(candidates)):
        if candidates[i][0] > matched_line:
            return i
    return len(candidates)


def build_entity_values_by_type(title_entities: dict[int, list[tuple[str, str]]]) -> dict[str, list[str]]:
    by_type: dict[str, set[str]] = {}
    for ents in title_entities.values():
        for value, etype in ents:
            by_type.setdefault(etype, set()).add(value)
    return {t: sorted(vals) for t, vals in by_type.items()}


def fallback_match_in_title(title: str, entity_values_by_type: dict[str, list[str]]) -> dict[str, list[str]]:
    """Se il match posizionale fallisce: cerca direttamente se il valore di
    un'entità nota nel catalogo compare (fuzzy, partial) dentro il title."""
    by_type: dict[str, list[str]] = {}
    for etype, values in entity_values_by_type.items():
        if not values:
            continue
        match = process.extractOne(title, values, scorer=fuzz.partial_ratio)
        if match is None:
            continue
        value, score, _ = match
        if score >= FALLBACK_MIN_SCORE:
            by_type.setdefault(etype, []).append(value)
    return by_type


def nearest_preceding_line(matched_line: int, title_lines: list[int]) -> int | None:
    candidates = [ln for ln in title_lines if ln <= matched_line]
    return max(candidates) if candidates else None


def process_catalogue(dir_path: Path, catalogue_id: str, chunks: pd.DataFrame) -> pd.DataFrame:
    md_path = dir_path / "all.md"
    if not md_path.exists():
        print(f"[skip] {dir_path.name}: all.md non trovato")
        return pd.DataFrame()

    lines = md_path.read_text(encoding="utf-8").splitlines()
    title_entities = load_title_entities(dir_path, lines)
    title_lines = sorted(title_entities.keys())
    entity_values_by_type = build_entity_values_by_type(title_entities)

    # righe candidate per il fuzzy match: tutte le non vuote, con indice 1-based
    candidates = [(i + 1, ln) for i, ln in enumerate(lines) if ln.strip()]

    rows = []
    cursor_idx = 0  # indice in `candidates`: non si torna mai indietro rispetto qui

    for _, chunk in chunks.iterrows():
        title = str(chunk["title"] or "").strip()
        matched_line, best_score = None, 0

        if title and candidates:
            for window_size in WINDOW_SIZES:
                ln, sc = find_best_match_in_window(title, candidates, cursor_idx, window_size)
                if sc > best_score:
                    best_score = sc
                if ln is not None and sc >= MIN_MATCH_SCORE:
                    matched_line = ln
                    break

        if matched_line is not None:
            cursor_idx = advance_cursor(candidates, cursor_idx, matched_line)
        # se non c'e' match affidabile, il cursore resta invariato

        entities_here = []
        method = None
        if matched_line is not None:
            preceding = nearest_preceding_line(matched_line, title_lines)
            if preceding is not None:
                entities_here = title_entities[preceding]
                method = "positional"

        by_type: dict[str, list[str]] = {}
        for value, etype in entities_here:
            by_type.setdefault(etype, []).append(value)

        # il match diretto (nome dell'entità letteralmente nel title) è
        # un'evidenza più forte del match posizionale: se c'è, ha la precedenza,
        # anche quando il match posizionale è "andato a buon fine" ma ha
        # agganciato l'entità sbagliata (es. righe OCR vicine ma non pertinenti)
        if title:
            fallback_by_type = fallback_match_in_title(title, entity_values_by_type)
            if fallback_by_type:
                by_type = fallback_by_type
                method = "title_direct"

        rows.append({
            "catalogue_id": catalogue_id,
            "chunk_db_id": chunk["chunk_db_id"],
            "chunk_id": chunk["chunk_index"],
            "num": chunk["num"],
            "title": title,
            "matched_line": matched_line,
            "match_score": round(best_score, 1),
            "low_confidence": matched_line is None,
            "entity_match_method": method or "none",
            "artist": "; ".join(by_type.get("artist", [])),
            "school": "; ".join(by_type.get("school", [])),
            "object_type": "; ".join(by_type.get("object_type", [])),
        })

    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="app/documents.db")
    ap.add_argument("--docs-dir", default="docling/documents")
    ap.add_argument("--out-dir", default="reviewed_lots_and_entities")
    args = ap.parse_args()

    docs_dir = Path(args.docs_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    catalogue_ids = fetch_reviewed_catalogue_ids(conn)
    print(f"{len(catalogue_ids)} cataloghi reviewed")

    for catalogue_id in catalogue_ids:
        chunk_group = fetch_chunks_for_catalogue(conn, catalogue_id)
        if chunk_group.empty:
            continue
        dir_path = docs_dir / catalogue_id
        result_df = process_catalogue(dir_path, catalogue_id, chunk_group)
        if result_df.empty:
            continue
        out_path = out_dir / f"{catalogue_id}.csv"
        result_df.to_csv(out_path, index=False, encoding="utf-8")
        n_low = result_df["low_confidence"].sum()
        print(f"{catalogue_id}: {len(result_df)} lotti → {out_path} "
              f"({n_low} match a bassa confidenza)")

    conn.close()


if __name__ == "__main__":
    main()
