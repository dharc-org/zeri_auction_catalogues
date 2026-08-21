"""
assign_entities_via_title_match.py

Per ogni lotto (chunk) di un catalogo con reviewed=1 in documents.db:
  - cerca in documents/<catalogue_id>/all.md la riga più simile (fuzzy match)
    al valore "title" del lotto (il testo può differire leggermente perché
    rivisto a mano)
  - trova la entità di titolo (artist/school/object_type, da entities.csv)
    con line_number più vicina PRECEDENTE a quella riga
  - assegna quell'entità al lotto
  - in piu': cerca nel title, via fuzzy match contro i Google Sheet
    "collezioni" e "periodi", eventuali collection/period gia' canonicalizzate
    (colonna ZERI non vuota) e le assegna alle colonne "collection"/"period"

Output: <out-dir>/<catalogue_id>.csv, uno per catalogo, con colonne:
  chunk_id, num, title, matched_line, match_score, artist, school,
  object_type, collection, period

Richiede: rapidfuzz (pip install rapidfuzz)
"""
from __future__ import annotations
from align_titles import align_titles_to_lines
from extract_collections_periods import extract_collections, extract_periods
import re
import sqlite3
import argparse
from pathlib import Path
import pandas as pd
from rapidfuzz import fuzz, process
import os
os.environ["USE_TORCH"] = "1"

TITLE_RE = re.compile(r"^#{1,2}\s+(.+)")
FALLBACK_MIN_SCORE = 85  # soglia per il fallback: valore entità contenuto nel title

# --- Google Sheet: collezioni / periodi canonicalizzati a mano ---
SPREADSHEET_ID = "11vB7CbMkboR2mwDneOK4RkTnaOeD1k7xi30eiv5ziZI"
GID_COLLEZIONI = "1845857607"
GID_PERIODI = "333540236"
CANONICAL_COL = "ZERI"
VARIANTS_COL = "variants"

MATCH_THRESHOLD_COLLECTION = 88
MATCH_THRESHOLD_PERIOD = 95  # variants spesso corte (es. "XVI") -> soglia piu' stretta per ridurre falsi positivi


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


ROMAN_RE = re.compile(r'\b[ivxlcdm]+\b', re.IGNORECASE)


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)  # rimuove punteggiatura
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def combined_score(query: str, choice: str, score_cutoff: float | None = None, **kwargs) -> float:
    q, c = normalize(query), normalize(choice)
    # ratio: sensibile a ordine/lunghezza (utile per OCR char-noise)
    # token_sort_ratio: robusto a parole spostate
    return 0.5 * fuzz.ratio(q, c) + 0.5 * fuzz.token_sort_ratio(q, c)


# --- Tie-breaker con embeddings per score ambigui ---
# pip install sentence-transformers

from sentence_transformers import SentenceTransformer
import numpy as np

AMBIGUOUS_LOW, AMBIGUOUS_HIGH = 40, 70  # range di score fuzzy considerato incerto
EMBEDDING_TOP_K = 2  # quanti candidati fuzzy passare all'embedding

_model = None
def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _model


def rerank_with_embeddings(title: str, top_candidates: list[tuple[int, str]]) -> tuple[int, str]:
    model = get_model()
    texts = [title] + [c[1] for c in top_candidates]
    embs = model.encode(texts, normalize_embeddings=True)
    sims = embs[1:] @ embs[0]
    best_idx = int(np.argmax(sims))
    return top_candidates[best_idx]


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


# ============================================================
# Collection / Period: match diretto contro Google Sheet canonicalizzato
# ============================================================

def sheet_csv_url(gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"


def split_pipe(cell) -> list[str]:
    if pd.isna(cell) or not str(cell).strip():
        return []
    return [v.strip() for v in str(cell).split("|") if v.strip()]


def build_variant_index_from_sheet(df: pd.DataFrame) -> dict[str, str]:
    """variante_normalizzata -> ZERI. Usa solo le righe con ZERI non vuoto
    (e' quello il segnale di 'canonicalizzato a mano', non serve un flag
    'rivisto' separato per questi due tab)."""
    index: dict[str, str] = {}
    for _, row in df.iterrows():
        canonical = str(row.get(CANONICAL_COL, "")).strip()
        if not canonical or canonical.lower() == "nan":
            continue
        variants = split_pipe(row.get(VARIANTS_COL, "")) + [canonical]
        for variant in variants:
            nv = normalize(variant)
            if nv:
                index[nv] = canonical
    return index


def load_collection_and_period_indexes() -> tuple[dict[str, str], dict[str, str]]:
    collezioni_df = pd.read_csv(sheet_csv_url(GID_COLLEZIONI))
    periodi_df = pd.read_csv(sheet_csv_url(GID_PERIODI))
    return build_variant_index_from_sheet(collezioni_df), build_variant_index_from_sheet(periodi_df)


def match_extracted_span(span: str, index: dict[str, str], threshold: float) -> str | None:
    """Cerca lo span estratto (stessa regex di extract_collections_periods)
    come variante nota nell'indice. Match sullo SPAN, non su tutto il
    title: e' lo stesso testo che finisce in extracted_*.csv come
    candidato, quindi deve essere confrontato allo stesso modo, altrimenti
    quello che extract_collections_periods propone per la revisione e
    quello che qui viene effettivamente riconosciuto rischiano di
    disallinearsi."""
    if not span or not index:
        return None
    norm_span = normalize(span)
    if norm_span in index:  # match esatto sulla forma normalizzata
        return index[norm_span]
    variants = list(index.keys())
    match = process.extractOne(norm_span, variants, scorer=fuzz.token_set_ratio)
    if match is None:
        return None
    variant, score, _ = match
    if score >= threshold:
        return index[variant]
    return None


def match_collection_in_title(title: str, index: dict[str, str]) -> str | None:
    for span in extract_collections(title):
        canonical = match_extracted_span(span, index, MATCH_THRESHOLD_COLLECTION)
        if canonical:
            return canonical
    return None


def match_period_in_title(title: str, index: dict[str, str]) -> str | None:
    for span in extract_periods(title):
        canonical = match_extracted_span(span, index, MATCH_THRESHOLD_PERIOD)
        if canonical:
            return canonical
    return None


def process_catalogue(dir_path, catalogue_id, chunks, collection_index, period_index):
    md_path = dir_path / "all.md"
    if not md_path.exists():
        print(f"[skip] {dir_path.name}: all.md non trovato")
        return pd.DataFrame()

    lines = md_path.read_text(encoding="utf-8").splitlines()
    title_entities = load_title_entities(dir_path, lines)
    title_lines = sorted(title_entities.keys())
    entity_values_by_type = build_entity_values_by_type(title_entities)

    candidates = [(i + 1, ln) for i, ln in enumerate(lines) if ln.strip()]

    titles = [str(t or "").strip() for t in chunks["title"]]
    alignment = align_titles_to_lines(titles, candidates)  # <-- unica chiamata, non più per-chunk

    rows = []
    for (_, chunk), title, (matched_line, best_score) in zip(chunks.iterrows(), titles, alignment):
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

        if title:
            fallback_by_type = fallback_match_in_title(title, entity_values_by_type)
            if fallback_by_type:
                by_type = fallback_by_type
                method = "title_direct"

        collection = match_collection_in_title(title, collection_index)
        period = match_period_in_title(title, period_index)

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
            "collection": collection or "",
            "period": period or "",
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

    print("[sheets] carico collezioni/periodi canonicalizzati...")
    collection_index, period_index = load_collection_and_period_indexes()
    print(f"[sheets] {len(collection_index)} varianti collezioni, {len(period_index)} varianti periodi")

    for catalogue_id in catalogue_ids:
        chunk_group = fetch_chunks_for_catalogue(conn, catalogue_id)
        if chunk_group.empty:
            continue
        dir_path = docs_dir / catalogue_id
        result_df = process_catalogue(dir_path, catalogue_id, chunk_group, collection_index, period_index)
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
