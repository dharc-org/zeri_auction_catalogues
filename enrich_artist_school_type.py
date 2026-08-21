"""
enrich_artist_school.py

Arricchisce artist, school e object_type dei CSV in
reviewed_lots_and_entities cercando nel title le varianti
note presenti nei Google Sheets.

Solo le righe con rivisto=TRUE vengono utilizzate.
Le varianti in "da ricollocare" vengono escluse.

Per object_type, il match viene rifatto anche se il campo non e' vuoto,
purche' il valore attuale non sia una variante/forma canonica nota nella
tabella "oggetti" (es. valore ereditato da una pipeline precedente e mai
validato contro questo vocabolario).

I CSV vengono sovrascritti direttamente.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process


# ============================================================
# CONFIG
# ============================================================

MATCH_THRESHOLD_ARTIST_OBJECT = 88
MATCH_THRESHOLD_SCHOOL = 95

SPREADSHEET_ID = "11vB7CbMkboR2mwDneOK4RkTnaOeD1k7xi30eiv5ziZI"

GID_ARTISTI = "910064299"
GID_SCUOLE = "379770645"
GID_OGGETTI = "1330387938"

CANONICAL_COL = "ZERI"
CANONICAL_COL_SCUOLE = "ZERI SOTTOCATEGORIA"
CANONICAL_COL_OGGETTI = "ZERI SOTTOCATEGORIA"
VARIANTS_COL = "variants"
EXCLUDE_COL = "da ricollocare"
REVIEWED_COL = "rivisto"

DOCS_DIR = Path("reviewed_lots_and_entities")


# ============================================================
# GOOGLE SHEETS
# ============================================================

def sheet_csv_url(gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"


# ============================================================
# UTILS
# ============================================================

def is_reviewed(value) -> bool:
    return not pd.isna(value) and str(value).strip().upper() == "TRUE"


def normalize(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_pipe(cell) -> list[str]:
    if pd.isna(cell) or not str(cell).strip():
        return []
    return [v.strip() for v in str(cell).split("|") if v.strip()]


def build_variant_index(df: pd.DataFrame, canonical_col: str) -> dict[str, str]:
    index = {}

    for _, row in df[df[REVIEWED_COL].apply(is_reviewed)].iterrows():
        canonical = str(row.get(canonical_col, "")).strip()
        if not canonical or canonical == "nan":
            continue

        excluded = {normalize(v) for v in split_pipe(row.get(EXCLUDE_COL))}
        variants = split_pipe(row.get(VARIANTS_COL)) + [canonical]

        for variant in variants:
            nv = normalize(variant)
            if nv and nv not in excluded:
                index[nv] = canonical

    return index

# ============================================================
# ENRICH
# ============================================================

def is_empty(value) -> bool:
    return pd.isna(value) or not str(value).strip()


def is_known_value(value, index: dict[str, str]) -> bool:
    """True se value e' gia' una variante o forma canonica presente in index."""
    if is_empty(value):
        return False
    return normalize(value) in index


def enrich(chunks, artist_index, school_index, object_type_index):
    chunks = chunks.copy()

    for col in ("artist", "school", "object_type"):
        if col not in chunks.columns:
            chunks[col] = ""

    for i, row in chunks.iterrows():
        title = str(row.get("title") or "").strip()

        if is_empty(row["artist"]):
            match = process.extractOne( normalize(title), list(artist_index), scorer=fuzz.token_set_ratio )

            if match and match[1] >= MATCH_THRESHOLD_ARTIST_OBJECT:
                chunks.at[i, "artist"] = artist_index[match[0]]

        if is_empty(row["school"]):
            match = process.extractOne( normalize(title), list(school_index), scorer=fuzz.token_set_ratio )

            if match and match[1] >= MATCH_THRESHOLD_SCHOOL:
                chunks.at[i, "school"] = school_index[match[0]]

        if is_empty(row["object_type"]) or not is_known_value(row["object_type"], object_type_index):
            match = process.extractOne( normalize(title), list(object_type_index), scorer=fuzz.token_set_ratio )

            if match and match[1] >= MATCH_THRESHOLD_ARTIST_OBJECT:
                chunks.at[i, "object_type"] = object_type_index[match[0]]

    return chunks

# ============================================================
# MAIN
# ============================================================

def main():

    artisti_df = pd.read_csv(sheet_csv_url(GID_ARTISTI))
    scuole_df = pd.read_csv(sheet_csv_url(GID_SCUOLE))
    oggetti_df = pd.read_csv(sheet_csv_url(GID_OGGETTI))

    artist_index = build_variant_index(artisti_df, CANONICAL_COL)
    school_index = build_variant_index(scuole_df, CANONICAL_COL_SCUOLE)
    object_type_index = build_variant_index(oggetti_df, CANONICAL_COL_OGGETTI)

    csv_files = sorted(DOCS_DIR.glob("*.csv"))

    print(f"Trovati {len(csv_files)} CSV in {DOCS_DIR}")

    totals = {"artist": 0, "school": 0, "object_type": 0}

    for path in csv_files:
        chunks = pd.read_csv(path)

        for col in totals:
            if col not in chunks.columns:
                chunks[col] = ""

        before = {
            col: chunks[col].fillna("").astype(str).str.strip().eq("").sum()
            for col in totals
        }

        enriched = enrich(
            chunks,
            artist_index,
            school_index,
            object_type_index,
        )

        enriched.to_csv(path, index=False, encoding="utf-8")

        assigned = {
            col: before[col] -
            enriched[col].fillna("").astype(str).str.strip().eq("").sum()
            for col in totals
        }

        for col in totals:
            totals[col] += assigned[col]

        print(
            f"{path.name}: "
            f"artist={assigned['artist']} | "
            f"school={assigned['school']} | "
            f"object_type={assigned['object_type']}"
        )

    print(
        f"\nTotale: "
        f"artist={totals['artist']} | "
        f"school={totals['school']} | "
        f"object_type={totals['object_type']}"
    )


if __name__ == "__main__":
    main()
