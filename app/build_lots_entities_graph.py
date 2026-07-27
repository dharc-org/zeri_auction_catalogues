# RUN ON THE SAME SERVER AS /app
# RETURN RDF OF TRANSCRIBED CATALOGUES
# NER già calcolata a monte (assign_entities_via_title_match.py):
# qui si leggono solo i risultati da lots_entities_output/<catalogue_id>.csv
from __future__ import annotations
import csv
import re
import io
import sqlite3
from pathlib import Path
import requests
import pandas as pd
import rdflib
from rdflib import Namespace, URIRef, Literal, Graph, RDF, RDFS, XSD

# Common namespaces
RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
DC = Namespace("http://purl.org/dc/elements/1.1/")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
LA = Namespace("https://linked.art/ns/terms/")
AAT = Namespace("http://vocab.getty.edu/aat/")

# Custom namespace
ZAC = Namespace("http://w3id.org/zac/")

g = Graph(identifier="http://w3id.org/zac/lots")

g.bind("rdf", RDF)
g.bind("rdfs", RDFS)
g.bind("xsd", XSD)
g.bind("dc", DC)
g.bind("zac", ZAC)
g.bind("crm", CRM)
g.bind("la", LA)
g.bind("aat", AAT)

BASE_DIR = Path(__file__).resolve().parent  # root/app/
DB_PATH = BASE_DIR / "documents.db"  # root/app/documents.db
ENTITIES_DIR = BASE_DIR.parent / "reviewed_lots_and_entities"  # root/reviewed_lots_and_entities
OUTPUT_DIR = BASE_DIR.parent / "lot_descriptions"  # root/lot_descriptions

# --- Google Sheet di normalizzazione entità ---
SPREADSHEET_ID = "11vB7CbMkboR2mwDneOK4RkTnaOeD1k7xi30eiv5ziZI"
GID_OGGETTI = "1330387938"
GID_SCUOLE = "379770645"
GID_ARTISTI = "910064299"


def load_sheet_tab(spreadsheet_id: str, gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    r = requests.get(url)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    return df


def parse_variants(cell: str) -> list[str]:
    return [v.strip().lower() for v in str(cell).split("|") if v.strip()]


def parse_bool(cell: str) -> bool:
    return str(cell).strip().lower() in ("true", "1", "vero", "yes", "si", "sì")


def clean(value: str) -> str:
    """Slug URI-safe. Se hai già un clean() altrove nel progetto, usa quello al suo posto."""
    value = str(value).strip().lower()
    value = re.sub(r"[^\w]+", "_", value, flags=re.UNICODE)
    return value.strip("_")


def load_object_type_map(df: pd.DataFrame) -> dict[str, str]:
    """variant -> ZERI (o ZERI SOTTOCATEGORIA se ZERI è vuoto)"""
    variant_map = {}
    for _, row in df.iterrows():
        normalized = row.get("ZERI", "").strip() or row.get("ZERI SOTTOCATEGORIA", "").strip()
        if not normalized:
            continue
        for variant in parse_variants(row.get("variants", "")):
            variant_map[variant] = normalized
    return variant_map


def load_school_map(df: pd.DataFrame) -> dict[str, dict]:
    """variant -> {"rivisto": bool, "zeri": str, "zeri_sottocategoria": str}"""
    variant_map = {}
    for _, row in df.iterrows():
        entry = {
            "rivisto": parse_bool(row.get("rivisto", "")),
            "zeri": row.get("ZERI", "").strip(),
            "zeri_sottocategoria": row.get("ZERI SOTTOCATEGORIA", "").strip(),
        }
        for variant in parse_variants(row.get("variants", "")):
            variant_map[variant] = entry
    return variant_map


def load_artist_map(df: pd.DataFrame) -> dict[str, dict]:
    """variant -> {"rivisto": bool, "zeri": str}"""
    variant_map = {}
    for _, row in df.iterrows():
        entry = {
            "rivisto": parse_bool(row.get("rivisto", "")),
            "zeri": row.get("ZERI", "").strip(),
        }
        for variant in parse_variants(row.get("variants", "")):
            variant_map[variant] = entry
    return variant_map


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def fetch_reviewed_catalogues(conn):
    cur = conn.cursor()
    cur.execute("SELECT id FROM catalogues WHERE reviewed = 1")
    return [r["id"] for r in cur.fetchall()]


def fetch_chunks(conn, catalogue_id):
    cur = conn.cursor()
    cur.execute("""
        SELECT chunk_index, num, title, text, image_online
        FROM chunks
        WHERE catalogue_id = ?
        ORDER BY chunk_index
    """, (catalogue_id,))
    return [dict(row) for row in cur.fetchall()]


def load_entities_for_catalogue(catalogue_id: str) -> dict[int, dict]:
    """chunk_id (== chunk_index) -> {"artist":..., "school":..., "object_type":...}"""
    csv_path = ENTITIES_DIR / f"{catalogue_id}.csv"
    if not csv_path.exists():
        print(f"  [warn] {catalogue_id}: nessun csv entità in {csv_path}, campi vuoti")
        return {}

    by_chunk = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_chunk[int(row["chunk_id"])] = {
                "artist": row.get("artist", ""),
                "school": row.get("school", ""),
                "object_type": row.get("object_type", ""),
            }
    return by_chunk


def normalize_object_type(object_type: str, object_type_map: dict[str, str]) -> str:
    return object_type_map.get(object_type.strip().lower(), object_type.strip())


def normalize_school(school: str, school_map: dict[str, dict]) -> tuple[str, str | None]:
    """Ritorna (valore_da_usare, valore_broader_o_None).
    Se rivisto e ci sono sia ZERI che ZERI SOTTOCATEGORIA, usa la sottocategoria
    e ritorna anche ZERI come broader term (per la tripla di gerarchia)."""
    entry = school_map.get(school.strip().lower())
    if not entry:
        return school.strip(), None
    if not entry["rivisto"]:
        return school.strip(), None

    zeri = entry["zeri"]
    sotto = entry["zeri_sottocategoria"]
    if sotto:
        return sotto, (zeri if zeri else None)
    return zeri or school.strip(), None


def normalize_author(author: str, artist_map: dict[str, dict]) -> str:
    entry = artist_map.get(author.strip().lower())
    if not entry or not entry["rivisto"]:
        return author.strip()
    return entry["zeri"] or author.strip()


def add_entity_triples(lot_id: str, author: str, school: str, object_type: str,
                        object_type_map: dict[str, str], school_map: dict[str, dict],
                        artist_map: dict[str, dict]):
    if object_type:
        normalized_object_type = normalize_object_type(object_type, object_type_map)
        g.add((URIRef(ZAC[lot_id]), CRM.P2_has_type, URIRef(ZAC["type/" + clean(normalized_object_type)])))
        g.add((URIRef(ZAC["type/" + clean(normalized_object_type)]), RDFS.label, Literal(normalized_object_type)))

    if school or author:
        broader = None
        if school:
            artist_or_school, broader = normalize_school(school, school_map)
        else:
            artist_or_school = normalize_author(author, artist_map)

        g.add((URIRef(ZAC[lot_id]), CRM.P94i_was_created_by, URIRef(ZAC["creation_" + lot_id])))
        g.add((URIRef(ZAC["creation_" + lot_id]), RDF.type, CRM.E65_Creation))
        g.add((URIRef(ZAC["creation_" + lot_id]), CRM.P14_carried_out_by, URIRef(ZAC[clean(artist_or_school)])))
        g.add((URIRef(ZAC[clean(artist_or_school)]), RDFS.label, Literal(artist_or_school)))

        if broader:
            # ZERI SOTTOCATEGORIA is part of / narrower term of ZERI
            g.add((URIRef(ZAC[clean(artist_or_school)]), CRM.P127_has_broader_term, URIRef(ZAC[clean(broader)])))
            g.add((URIRef(ZAC[clean(broader)]), RDFS.label, Literal(broader)))


def process_lot_descriptions(catalogue_id, chunks, entities_by_chunk,
                              object_type_map, school_map, artist_map):
    print(f"Processing {catalogue_id} ({len(chunks)} chunks)")

    g.add((URIRef(ZAC[catalogue_id + '_auction']), CRM.P16_used_specific_object, URIRef(ZAC[catalogue_id + '_lots'])))
    g.add((URIRef(ZAC[catalogue_id + '_lots']), RDF.type, LA["Set"]))
    g.add((URIRef(ZAC[catalogue_id + '_lots']), CRM.P2_has_type, AAT["300411307"]))

    for chunk in chunks:
        num = chunk["num"]
        text = chunk["title"]
        full_text = chunk["text"]
        image_online = chunk["image_online"]
        lot_id = catalogue_id + '_lot_' + num.strip().replace(" ", "_")

        # part of
        g.add((URIRef(ZAC[catalogue_id + '_lots']), CRM.P46_is_composed_of, URIRef(ZAC[lot_id])))
        g.add((URIRef(ZAC[lot_id]), RDF.type, LA["Set"]))
        g.add((URIRef(ZAC[lot_id]), RDFS.label, Literal(num + ' - ' + text)))
        # lot id
        g.add((URIRef(ZAC[lot_id]), CRM.P1_is_identified_by, URIRef(ZAC[lot_id + '_id'])))
        g.add((URIRef(ZAC[lot_id + '_id']), RDF.type, CRM.E42_Identifier))
        g.add((URIRef(ZAC[lot_id + '_id']), RDFS.label, Literal(catalogue_id + '-' + num)))
        # lot title
        g.add((URIRef(ZAC[lot_id]), CRM.P102_has_title, URIRef(ZAC[lot_id + '_title'])))
        g.add((URIRef(ZAC[lot_id + "_title"]), RDFS.label, Literal(text)))
        # lot description
        g.add((URIRef(ZAC[lot_id]), CRM.P67i_is_referred_to_by, URIRef(ZAC[lot_id + '_description'])))
        g.add((URIRef(ZAC[lot_id + '_description']), RDF.type, CRM.E33_Linguistic_Object))
        g.add((URIRef(ZAC[lot_id + '_description']), RDFS.label, Literal(full_text)))
        g.add((URIRef(ZAC[lot_id + '_description']), CRM.P2_has_type, AAT["300435416"]))  # nota generica
        # catalogue page (not tavola)
        g.add((URIRef(ZAC[lot_id]), CRM.P138i_has_representation, URIRef(image_online)))

        # entità già calcolate (assign_entities_via_title_match.py), non più NER live
        ent = entities_by_chunk.get(chunk["chunk_index"], {})
        author = ent.get("artist", "")
        school = ent.get("school", "")
        object_type = ent.get("object_type", "")
        print(f"{lot_id} | {author} | {school} | {object_type}")

        add_entity_triples(lot_id, author, school, object_type,
                            object_type_map, school_map, artist_map)

        # TODO
        # crm:P57_has_number_of_parts
        # crm:P2_has_type
        # crm:P4_has_time-span
        # la:members_exemplified_by :opera_001 .

        # opera
        #   rdfs:label "Opera 001"@it ;
        #   la:member_of :lotto_001 ;
        #   crm:P2_has_type
        #   crm:P94i_was_created_by :creazione_opera_001 ;
        #   crm:P45_consists_of :materiale_opera_001 ;
        #   crm:P43_has_dimension :altezza_opera_001 , :larghezza_opera_001;
        # :creazione_opera_001 a crm:E65_Creation ;
        #     rdfs:label "Creazione dell'opera"@it ;
        #     crm:P2_has_type aat:300404387 ;
        #     crm:P14_carried_out_by :artista_001 ; # o attribuito tramite E13
        #     crm:P7_took_place_at :luogo_creazione_001 ;
        #     crm:P4_has_time-span :periodo_creazione_001 ;
        #     crm:P32_used_general_technique


def main():
    conn = get_db()
    catalogues = fetch_reviewed_catalogues(conn)

    if not catalogues:
        print("No reviewed catalogues.")
        return

    object_type_map = load_object_type_map(load_sheet_tab(SPREADSHEET_ID, GID_OGGETTI))
    school_map = load_school_map(load_sheet_tab(SPREADSHEET_ID, GID_SCUOLE))
    artist_map = load_artist_map(load_sheet_tab(SPREADSHEET_ID, GID_ARTISTI))

    for catalogue_id in catalogues:
        chunks = fetch_chunks(conn, catalogue_id)
        entities_by_chunk = load_entities_for_catalogue(catalogue_id)
        process_lot_descriptions(catalogue_id, chunks, entities_by_chunk,
                                  object_type_map, school_map, artist_map)

    conn.close()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    g.serialize(OUTPUT_DIR / 'zac_lot_descriptions.ttl', format='turtle')


if __name__ == "__main__":
    main()
