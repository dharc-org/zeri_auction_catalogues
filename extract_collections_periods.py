"""
extract_collections_periods.py

Pre-processing da eseguire PRIMA di assign_entities_via_title_match.py.
Estrae dal solo "title" del lotto (mai dai titoli di sezione) due tipi di
entità candidate, non ancora canonicalizzate:

1. COLLEZIONI: se il title contiene "collezion", "collection" o "sammlung"
   (case-insensitive), estrae il testo che segue il trigger fino al primo
   punto fermo (o fino a fine stringa se non c'e' punto), es. da
   "...proveniente dalla collezione Rothschild. Altro testo." estrae
   " Rothschild".

2. PERIODI/SECOLI: due casistiche indipendenti, entrambe cercate SOLO nel
   title:
   a) menzione diretta di un secolo: un numero di due cifre o un numerale
      romano MAIUSCOLO adiacente (prima o dopo, token contiguo) a
      "secolo"/"century"/"siecle"/"jahr*", es. "Sec. XVI", "XVIIIe
      siecle", "16. Jahrhundert".
   b) uno o piu' anni a 4 cifre (1000-1999), singoli o in range
      (es. "1592-1630", "1679"), da ricondurre manualmente al secolo in
      un secondo momento.

I candidati (stringhe grezze, non normalizzate) vengono APPESI, senza
sovrascrivere nulla, a extracted_collections.csv / extracted_periods.csv
(colonne ZERI, variants; ZERI resta vuoto, va compilato a mano dopo la
revisione). Un candidato viene scartato se e' gia' presente come variante
(case-insensitive) nel Google Sheet di riferimento o nel CSV locale
stesso, cosi' run successive non duplicano le righe.

Richiede: pandas, requests
"""
from __future__ import annotations
import argparse
import io
import re
import sqlite3
from pathlib import Path

import pandas as pd
import requests

SPREADSHEET_ID = "11vB7CbMkboR2mwDneOK4RkTnaOeD1k7xi30eiv5ziZI"
GID_COLLEZIONI = "1845857607"
GID_PERIODI = "333540236"

CSV_COLUMNS = ["ZERI", "variants", "new"]

COLLECTION_TRIGGERS = ("collezion", "collection", "sammlung")
PERIOD_TRIGGERS = ("jahr", "siecle", "siècle", "century", "secolo")

TWO_DIGIT_RE = re.compile(r"^\d{2}$")
ROMAN_NUM_RE = re.compile(r"^[IVXLCDM]+(me|e|ème|er|ère)?$")  # roman MAIUSCOLO, suffisso ordinale francese ammesso lowercase

YEAR_RANGE_RE = re.compile(r"\b1[0-9]{3}\s*-\s*1[0-9]{3}\b")
YEAR_SINGLE_RE = re.compile(r"\b1[0-9]{3}\b")


# ============================================================
# DB (minimo indispensabile, self-contained: nessuna dipendenza pesante)
# ============================================================

def fetch_catalogue_ids(conn: sqlite3.Connection, only_reviewed: bool = True) -> list[str]:
    query = "SELECT id FROM catalogues WHERE reviewed = 1 ORDER BY id" if only_reviewed else "SELECT id FROM catalogues ORDER BY id"
    cur = conn.execute(query)
    return [r[0] for r in cur.fetchall()]


def fetch_titles_for_catalogue(conn: sqlite3.Connection, catalogue_id: str) -> list[str]:
    cur = conn.execute(
        "SELECT title FROM chunks WHERE catalogue_id = ? ORDER BY chunk_index",
        (catalogue_id,),
    )
    return [str(r[0] or "") for r in cur.fetchall()]


# ============================================================
# GOOGLE SHEETS
# ============================================================

def sheet_csv_url(gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"


def load_known_variants(gid: str) -> set[str]:
    """Tutte le varianti gia' presenti (pipe-separated) nel tab di riferimento, normalizzate lower."""
    r = requests.get(sheet_csv_url(gid), timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), dtype=str).fillna("")
    known = set()
    for cell in df.get("variants", []):
        for v in str(cell).split("|"):
            v = v.strip()
            if v:
                known.add(v.lower())
    return known


# ============================================================
# ESTRAZIONE
# ============================================================

def extract_collections(title: str) -> list[str]:
    found = []
    for trigger in COLLECTION_TRIGGERS:
        # \w* dopo il trigger: "collezion" e' prefisso di "collezione"/"collezioni",
        # senza consumare tutta la parola resterebbe una lettera finale attaccata
        pattern = re.compile(re.escape(trigger) + r"\w*", re.IGNORECASE)
        for m in pattern.finditer(title):
            after = title[m.end():]
            stop = after.find(".")
            segment = after if stop == -1 else after[:stop]
            segment = segment.strip(" ,;:-")
            if segment:
                found.append(segment)
    return found


def extract_periods(title: str) -> list[str]:
    found = []

    tokens = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", title)]

    for i, (tok, start, end) in enumerate(tokens):
        tok_clean = tok.strip(".,;:")
        # "sec"/"sec." va confrontato per uguaglianza esatta del token, non come
        # substring: "secondo", "sezione" ecc. contengono "sec" come prefisso e
        # darebbero falsi positivi se trattato come gli altri trigger
        is_sec_abbrev = tok_clean.lower() == "sec"
        if not (is_sec_abbrev or any(trig in tok_clean.lower() for trig in PERIOD_TRIGGERS)):
            continue

        neighbours = []
        if i > 0:
            neighbours.append(tokens[i - 1])
        if i + 1 < len(tokens):
            neighbours.append(tokens[i + 1])

        for ntok, nstart, nend in neighbours:
            ntok_clean = ntok.strip(".,;:")
            if TWO_DIGIT_RE.match(ntok_clean) or ROMAN_NUM_RE.match(ntok_clean):
                span_start, span_end = min(start, nstart), max(end, nend)
                segment = title[span_start:span_end].strip(" .,;:-")
                if segment:
                    found.append(segment)

    # anni (range o singolo), indipendente dai trigger sopra
    consumed = set()
    for m in YEAR_RANGE_RE.finditer(title):
        found.append(m.group(0))
        consumed.update(range(m.start(), m.end()))
    for m in YEAR_SINGLE_RE.finditer(title):
        if not any(p in consumed for p in range(m.start(), m.end())):
            found.append(m.group(0))

    return found


# ============================================================
# APPEND CSV (idempotente)
# ============================================================

def load_or_init_table(csv_path: Path) -> pd.DataFrame:
    if csv_path.exists():
        df = pd.read_csv(csv_path, dtype=str).fillna("")
        for col in ("ZERI", "variants"):
            if col not in df.columns:
                df[col] = ""
        return df[["ZERI", "variants"]]
    return pd.DataFrame(columns=["ZERI", "variants"])


def build_updated_table(csv_path: Path, values: list[str], known_online: set[str]) -> tuple[pd.DataFrame, int]:
    """
    Carica il csv esistente, appende le varianti nuove trovate in questo run,
    poi ricalcola la colonna 'new' su TUTTE le righe confrontando con il
    Google Sheet: 'new' = variante non ancora presente online. Le righe
    'new' finiscono in fondo (stable sort), cosi' sono sempre pronte da
    copiare per la revisione, e una volta portate online spariscono da
    'new' al run successivo senza bisogno di pulizia manuale.
    """
    df = load_or_init_table(csv_path)
    existing_variants_lower = {v.strip().lower() for v in df["variants"] if str(v).strip()}

    seen = known_online | existing_variants_lower
    new_rows = []
    for v in values:
        key = v.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        new_rows.append({"ZERI": "", "variants": v.strip()})

    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)

    df["new"] = df["variants"].apply(lambda v: str(v).strip().lower() not in known_online)
    df = df.sort_values(by="new", kind="stable").reset_index(drop=True)

    return df, len(new_rows)


def write_table(csv_path: Path, df: pd.DataFrame):
    df.to_csv(csv_path, index=False, encoding="utf-8", columns=CSV_COLUMNS)


# ============================================================
# MAIN
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="app/documents.db")
    ap.add_argument("--collections-csv", default="extracted_collections.csv")
    ap.add_argument("--periods-csv", default="extracted_periods.csv")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    catalogue_ids = fetch_catalogue_ids(conn, False) # fetch all catalogues not only reviewed
    print(f"{len(catalogue_ids)} cataloghi reviewed")

    print("[sheets] carico varianti note (collezioni, periodi)...")
    known_collections = load_known_variants(GID_COLLEZIONI)
    known_periods = load_known_variants(GID_PERIODI)

    all_collections: list[str] = []
    all_periods: list[str] = []

    for catalogue_id in catalogue_ids:
        titles = fetch_titles_for_catalogue(conn, catalogue_id)
        for title in titles:
            all_collections.extend(extract_collections(title))
            all_periods.extend(extract_periods(title))

    conn.close()

    collections_path = Path(args.collections_csv)
    collections_df, n_new_c = build_updated_table(collections_path, all_collections, known_collections)
    write_table(collections_path, collections_df)
    print(f"{collections_path.name}: +{n_new_c} nuove varianti in questo run, "
          f"{int(collections_df['new'].sum())} totali da rivedere")

    periods_path = Path(args.periods_csv)
    periods_df, n_new_p = build_updated_table(periods_path, all_periods, known_periods)
    write_table(periods_path, periods_df)
    print(f"{periods_path.name}: +{n_new_p} nuove varianti in questo run, "
          f"{int(periods_df['new'].sum())} totali da rivedere")


if __name__ == "__main__":
    main()
