# RUN ON THE SAME SERVER AS /app
# RETURN RDF OF TRANSCRIBED CATALOGUES
from __future__ import annotations
import argparse, csv, io, re, sqlite3
from pathlib import Path
from urllib.parse import unquote
import pandas as pd, requests
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef

RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
DC = Namespace("http://purl.org/dc/elements/1.1/")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
LA = Namespace("https://linked.art/ns/terms/")
AAT = Namespace("http://vocab.getty.edu/aat/")
ZAC = Namespace("http://w3id.org/zac/")

g = Graph(identifier="http://w3id.org/zac/lots")
for p, ns in {"rdf": RDF, "rdfs": RDFS, "xsd": XSD, "dc": DC, "zac": ZAC, "crm": CRM, "la": LA, "aat": AAT}.items():
    g.bind(p, ns)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "documents.db"
ENTITIES_DIR = BASE_DIR.parent / "reviewed_lots_and_entities"
OUTPUT_DIR = BASE_DIR.parent / "lot_descriptions"
HISTORICA_MAPPING_PATH = OUTPUT_DIR / "historica_mapping.csv"
HISTORICA_MAPPING_COLUMNS = ["catalogue_id", "page_label", "iiif_url"]

SPREADSHEET_ID = "11vB7CbMkboR2mwDneOK4RkTnaOeD1k7xi30eiv5ziZI"
GID_OGGETTI, GID_SCUOLE, GID_ARTISTI = "1330387938", "379770645", "910064299"
HISTORICA_SPREADSHEET_ID = "1CC4sbzh8EtqYs16JSfTR9kUoNU9XfeJQpu3qC7ZWht0"
HISTORICA_GID = "1619304272"

# Formato output: "nt" e' molto piu' veloce di "turtle" su grafi grandi
# (il serializzatore turtle di rdflib < 7 ha complessita' quadratica).
# Se serve leggibilita' umana e il grafo e' piccolo, rimetti "turtle".
OUTPUT_FORMAT = "turtle"


def load_sheet_tab(spreadsheet_id: str, gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    return df


def normalize_page_label(label: str) -> str:
    return str(label).strip()


def load_historica_mapping() -> dict[tuple[str, str], str]:
    if not HISTORICA_MAPPING_PATH.exists():
        print(f"[historica] cache non trovata: {HISTORICA_MAPPING_PATH}")
        return {}
    try:
        df = pd.read_csv(HISTORICA_MAPPING_PATH, dtype=str).fillna("")
    except pd.errors.EmptyDataError:
        return {}
    missing = set(HISTORICA_MAPPING_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Cache Historica: colonne mancanti: {sorted(missing)}")
    mapping = {}
    for row in df.itertuples(index=False):
        cid, label, url = str(row.catalogue_id).strip(), normalize_page_label(row.page_label), str(row.iiif_url).strip()
        if cid and label and url:
            mapping[(cid, label)] = url
    print(f"[historica] mapping caricati dalla cache: {len(mapping)}")
    return mapping


def save_historica_mapping(mapping: dict[tuple[str, str], str]):
    if not mapping:
        print("[historica] nessun mapping da salvare.")
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [{"catalogue_id": cid, "page_label": label, "iiif_url": url} for (cid, label), url in mapping.items()]
    df = pd.DataFrame(rows, columns=HISTORICA_MAPPING_COLUMNS).sort_values(["catalogue_id", "page_label"])
    df.to_csv(HISTORICA_MAPPING_PATH, index=False, encoding="utf-8")
    print(f"[historica] cache aggiornata: {HISTORICA_MAPPING_PATH} ({len(df)} mapping totali)")


def extract_historica_page_label(image_online: str) -> str | None:
    if not image_online:
        return None
    match = re.search(r"-([^/]+)\.jpg/full/", image_online, flags=re.IGNORECASE)
    return normalize_page_label(unquote(match.group(1))) if match else None


def load_historica_manifest_map() -> dict[str, str]:
    df = load_sheet_tab(HISTORICA_SPREADSHEET_ID, HISTORICA_GID)
    missing = {"inventario", "manifest"} - set(df.columns)
    if missing:
        raise ValueError(f"Google Sheet Historica: colonne mancanti: {sorted(missing)}")
    manifest_map = {}
    for row in df.itertuples(index=False):
        cid, url = str(row.inventario).strip(), str(row.manifest).strip()
        if cid and url:
            manifest_map[cid] = url
    print(f"[historica] manifest disponibili: {len(manifest_map)}")
    return manifest_map


def load_historica_manifest(manifest_url: str) -> dict:
    r = requests.get(manifest_url, timeout=60)
    r.raise_for_status()
    return r.json()


def find_historica_image(manifest: dict, page_label: str) -> str | None:
    page_label = normalize_page_label(page_label)
    for sequence in manifest.get("sequences", []):
        for canvas in sequence.get("canvases", []):
            label = canvas.get("label", "")
            if isinstance(label, dict):
                label = label.get("it") or label.get("en") or label.get("@value") or ""
            if normalize_page_label(label) != page_label:
                continue
            images = canvas.get("images", [])
            if not images:
                return None
            return images[0].get("resource", {}).get("@id")
    return None


def parse_variants(cell: str) -> list[str]:
    return [v.strip().lower() for v in str(cell).split("|") if v.strip()]


def parse_bool(cell: str) -> bool:
    return str(cell).strip().lower() in {"true", "1", "vero", "yes", "si", "sì"}


def clean(value: str) -> str:
    return re.sub(r"[^\w]+", "_", str(value).strip().lower(), flags=re.UNICODE).strip("_")


def load_object_type_map(df: pd.DataFrame) -> dict[str, str]:
    variant_map = {}
    for _, row in df.iterrows():
        normalized = row.get("ZERI", "").strip() or row.get("ZERI SOTTOCATEGORIA", "").strip()
        if not normalized:
            continue
        for variant in parse_variants(row.get("variants", "")):
            variant_map[variant] = normalized
    return variant_map


def load_school_map(df: pd.DataFrame) -> dict[str, dict]:
    variant_map = {}
    for _, row in df.iterrows():
        entry = {   "rivisto": parse_bool(row.get("rivisto", "")),
                    "zeri": row.get("ZERI", "").strip(),
                    "zeri_sottocategoria": row.get("ZERI SOTTOCATEGORIA", "").strip(),
                    "artista":parse_bool(row.get("artista", "")),
                    "oggetti":parse_bool(row.get("oggetti", "")),
                    "collezione":parse_bool(row.get("collezione", "")),
                    "casa d'aste":parse_bool(row.get("casa d'aste", ""))
                    }
        for variant in parse_variants(row.get("variants", "")):
            variant_map[variant] = entry
    return variant_map


def load_artist_map(df: pd.DataFrame) -> dict[str, dict]:
    variant_map = {}
    for _, row in df.iterrows():
        entry = {"rivisto": parse_bool(row.get("rivisto", "")), "zeri": row.get("ZERI", "").strip()}
        for variant in parse_variants(row.get("variants", "")):
            variant_map[variant] = entry
    return variant_map


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def fetch_catalogues(conn, only_reviewed: bool):
    query = "SELECT id, reviewed FROM catalogues WHERE reviewed = 1" if only_reviewed else "SELECT id, reviewed FROM catalogues"
    return [(row["id"], bool(row["reviewed"])) for row in conn.execute(query).fetchall()]


def fetch_chunks(conn, catalogue_id):
    rows = conn.execute("SELECT chunk_index, num, title, text, image_online FROM chunks WHERE catalogue_id = ? ORDER BY chunk_index", (catalogue_id,)).fetchall()
    return [dict(row) for row in rows]


def load_entities_for_catalogue(catalogue_id: str) -> dict[int, dict]:
    csv_path = ENTITIES_DIR / f"{catalogue_id}.csv"
    if not csv_path.exists():
        print(f"  [warn] {catalogue_id}: nessun CSV entità: {csv_path}")
        return {}
    by_chunk = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_chunk[int(row["chunk_id"])] = {"artist": row.get("artist", ""), "school": row.get("school", ""), "object_type": row.get("object_type", "")}
    return by_chunk


def normalize_object_type(object_type: str, object_type_map: dict[str, str]) -> str:
    return object_type_map.get(object_type.strip().lower(), object_type.strip())


def normalize_school(school: str, school_map: dict[str, dict]) -> tuple[str, str | None]:
    entry = school_map.get(school.strip().lower())
    if not entry or not entry["rivisto"]:
        return school.strip(), None, None, 'not validated'

    zeri, sotto = entry["zeri"], entry["zeri_sottocategoria"]
    # if artist
    if entry and entry['artista']:
        return (sotto, zeri, 'artista', 'validated') if sotto else (zeri, None, 'artista', 'validated')
    # if object type
    if entry and entry['oggetti']:
        return (sotto, zeri, 'oggetti', 'validated') if sotto else (zeri, None, 'oggetti', 'validated')
    # if collection
    if entry and entry['collezione']:
        return (sotto, zeri, 'collezione', 'validated') if sotto else (zeri, None, 'collezione', 'validated')
    # if casa d'aste
    if entry and entry["casa d'aste"]:
        return (sotto, zeri, "casa d'aste", 'validated') if sotto else (zeri, None, "casa d'aste", 'validated')
    # if school or artist
    return (sotto, zeri or None, None, 'validated') if sotto else (zeri or school.strip(), None, None, 'not validated')


def normalize_author(author: str, artist_map: dict[str, dict]) -> str:
    entry = artist_map.get(author.strip().lower())
    return entry["zeri"] or author.strip() if entry and entry["rivisto"] else author.strip()


def add_entity_triples(lot_id: str, author: str, school: str, object_type: str, object_type_map: dict[str, str], school_map: dict[str, dict], artist_map: dict[str, dict]):

    #catalogue_id = lot_id
    if object_type:
        norm = normalize_object_type(object_type, object_type_map)
        object_uri = URIRef(ZAC[f"type/{clean(norm)}"])
        g.add((URIRef(ZAC[lot_id]), CRM.P2_has_type, object_uri))
        g.add((object_uri, RDFS.label, Literal(norm)))

    if not (school or author):
        return

    broader, entity_type, validated = None, None, None
    artist_or_school = normalize_school(school, school_map)[0] if school else normalize_author(author, artist_map)
    if school:
        artist_or_school, broader, entity_type, validated = normalize_school(school, school_map)

    # school or artist in table "scuole"
    if not entity_type or entity_type == 'artista':
        creation_uri = URIRef(ZAC[f"creation_{lot_id}"])
        actor_uri = URIRef(ZAC[clean(artist_or_school)])
        g.add((URIRef(ZAC[lot_id]), CRM.P94i_was_created_by, creation_uri))
        g.add((creation_uri, RDF.type, CRM.E65_Creation))
        g.add((creation_uri, CRM.P14_carried_out_by, actor_uri))
        g.add((actor_uri, RDFS.label, Literal(artist_or_school)))

        if not entity_type:
            g.add((actor_uri, RDF.type, CRM.E74_Group ))

        if entity_type == 'artista':
            g.add((actor_uri, RDF.type, CRM.E21_Person ))

        if validated and validated == 'validated':
            g.add((creation_uri, CRM.P2_has_type, URIRef(ZAC['validated']) ))
        else:
            g.add((creation_uri, CRM.P2_has_type, URIRef(ZAC['not_validated']) ))

        if broader:
            broader_uri = URIRef(ZAC[clean(broader)])
            g.add((actor_uri, CRM.P127_has_broader_term, broader_uri))
            g.add((broader_uri, RDFS.label, Literal(broader)))
    else:
        if entity_type == 'oggetti':
            norm = normalize_object_type(artist_or_school, object_type_map)
            object_uri = URIRef(ZAC[f"type/{clean(norm)}"])
            g.add((URIRef(ZAC[lot_id]), CRM.P2_has_type, object_uri))
            g.add((object_uri, RDFS.label, Literal(norm)))

        # if entity_type == 'collezione':
        #     # crm:P16_used_specific_object
        # if entity_type == "casa d'aste":


def get_historica_image_for_lot(catalogue_id, image_online, historica_manifest_map, historica_mapping, historica_manifest_cache, new_historica_mappings):
    page_label = extract_historica_page_label(image_online)
    if not page_label:
        print(f"  [historica] {catalogue_id}: page label non trovato")
        return None

    key = (catalogue_id, page_label)
    if key in historica_mapping:
        print(f"  [historica] CACHE HIT | {catalogue_id} | {page_label}")
        return historica_mapping[key]

    manifest_url = historica_manifest_map.get(catalogue_id)
    if not manifest_url:
        print(f"  [historica] {catalogue_id}: manifest non trovato")
        return None

    if manifest_url not in historica_manifest_cache:
        print(f"  [historica] DOWNLOAD MANIFEST | {catalogue_id}")
        try:
            historica_manifest_cache[manifest_url] = load_historica_manifest(manifest_url)
        except (requests.RequestException, ValueError) as e:
            print(f"  [historica] {catalogue_id}: errore manifest: {e}")
            return None

    image_url = find_historica_image(historica_manifest_cache[manifest_url], page_label)
    if not image_url:
        print(f"  [historica] {catalogue_id}: '{page_label}' non trovato")
        return None

    historica_mapping[key] = image_url
    new_historica_mappings.append((catalogue_id, page_label, image_url))
    print(f"  [historica] NEW MAPPING | {catalogue_id} | {page_label} -> {image_url}")
    return image_url


def process_lot_descriptions(catalogue_id, reviewed, chunks, entities_by_chunk, object_type_map, school_map, artist_map, historica_manifest_map, historica_mapping, historica_manifest_cache, new_historica_mappings):
    print(f"Processing {catalogue_id} ({len(chunks)} chunks, reviewed={reviewed})")

    short_id = catalogue_id.split("_", 1)[1]
    auction_uri, lots_uri = URIRef(ZAC[f"{short_id}_auction"]), URIRef(ZAC[f"{short_id}_lots"])
    g.add((auction_uri, CRM.P16_used_specific_object, lots_uri))
    g.add((lots_uri, RDF.type, LA["Set"]))
    g.add((lots_uri, CRM.P2_has_type, AAT["300411307"]))

    if reviewed:
        g.add((URIRef(ZAC[short_id]), CRM.P2_has_type, URIRef(ZAC["reviewed"])))

    # add link to manifest: WEIRD IDs 
    cur_manifest = historica_manifest_map[catalogue_id.replace("BO0614", "BO0624")] or None
    if cur_manifest:
        g.add((URIRef(ZAC[short_id]), CRM.P138i_has_representation, URIRef(cur_manifest) ))

    for chunk in chunks:
        num, title, full_text, image_online = chunk["num"], chunk["title"], chunk["text"], chunk["image_online"]
        lot_id = f"{short_id}_lot_{num.strip().replace(' ', '_')}"
        lot_uri = URIRef(ZAC[lot_id])

        g.add((lots_uri, CRM.P46_is_composed_of, lot_uri))
        g.add((lot_uri, RDF.type, LA["Set"]))
        #g.add((lot_uri, RDFS.label, Literal(f"{num} - {title}")))

        lot_identifier_uri = URIRef(ZAC[f"{lot_id}_id"])
        g.add((lot_uri, CRM.P1_is_identified_by, lot_identifier_uri))
        g.add((lot_identifier_uri, RDF.type, CRM.E42_Identifier))
        g.add((lot_identifier_uri, RDFS.label, Literal(f"{catalogue_id}-{num}")))

        title_uri = URIRef(ZAC[f"{lot_id}_title"])
        g.add((lot_uri, CRM.P102_has_title, title_uri))
        g.add((title_uri, RDFS.label, Literal(title)))
        g.add((lot_uri, RDFS.label, Literal(title)))

        description_uri = URIRef(ZAC[f"{lot_id}_description"])
        g.add((lot_uri, CRM.P67i_is_referred_to_by, description_uri))
        g.add((description_uri, RDF.type, CRM.E33_Linguistic_Object))
        g.add((description_uri, RDFS.label, Literal(full_text)))
        g.add((description_uri, CRM.P2_has_type, AAT["300435416"]))

        if image_online:
            #g.add((lot_uri, CRM.P138i_has_representation, URIRef(image_online)))
            historica_image_url = get_historica_image_for_lot(catalogue_id, image_online, historica_manifest_map, historica_mapping, historica_manifest_cache, new_historica_mappings)
            if historica_image_url:
                g.add((lot_uri, CRM.P138i_has_representation, URIRef(historica_image_url)))

        ent = entities_by_chunk.get(chunk["chunk_index"], {})
        author, school, object_type = ent.get("artist", ""), ent.get("school", ""), ent.get("object_type", "")
        print(f"{lot_id} | {author} | {school} | {object_type}")
        add_entity_triples(lot_id, author, school, object_type, object_type_map, school_map, artist_map)

        # TODO: crm:P57_has_number_of_parts, crm:P4_has_time-span, la:members_exemplified_by


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Processa tutti i cataloghi, non solo quelli reviewed=1")
    args = parser.parse_args()
    only_reviewed = not args.all

    conn = get_db()
    catalogues = fetch_catalogues(conn, only_reviewed)
    if not catalogues:
        print("Nessun catalogo trovato." if args.all else "Nessun catalogo reviewed.")
        conn.close()
        return

    object_type_map = load_object_type_map(load_sheet_tab(SPREADSHEET_ID, GID_OGGETTI))
    school_map = load_school_map(load_sheet_tab(SPREADSHEET_ID, GID_SCUOLE))
    artist_map = load_artist_map(load_sheet_tab(SPREADSHEET_ID, GID_ARTISTI))

    print("[historica] caricamento manifest map...")
    historica_manifest_map = load_historica_manifest_map()

    print("[historica] caricamento cache CSV...")
    historica_mapping = load_historica_mapping()
    historica_manifest_cache = {}
    new_historica_mappings = []

    try:
        for catalogue_id, reviewed in catalogues:
            chunks = fetch_chunks(conn, catalogue_id)
            entities_by_chunk = load_entities_for_catalogue(catalogue_id)
            process_lot_descriptions(catalogue_id, reviewed, chunks, entities_by_chunk, object_type_map, school_map, artist_map, historica_manifest_map, historica_mapping, historica_manifest_cache, new_historica_mappings)
    finally:
        conn.close()

    seen, unique_new_mappings = set(), []
    for row in new_historica_mappings:
        key = (row[0], row[1])
        if key not in seen:
            seen.add(key)
            unique_new_mappings.append(row)

    save_historica_mapping(historica_mapping)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ext = "nt" if OUTPUT_FORMAT == "nt" else "ttl"
    output_path = OUTPUT_DIR / f"zac_lot_descriptions.{ext}"

    print(f"[serialize] {len(g)} triple, formato={OUTPUT_FORMAT} -> {output_path}")
    g.serialize(destination=str(output_path), format=OUTPUT_FORMAT)
    print("[serialize] completato.")

    print()
    print("=" * 50)
    print("DONE")
    print("=" * 50)
    print(f"RDF: {output_path}")
    print(f"Historica mapping CSV: {HISTORICA_MAPPING_PATH}")
    print(f"Nuovi mapping in questa run: {len(unique_new_mappings)}")
    print(f"Mapping totali in cache: {len(historica_mapping)}")
    print(f"Manifest scaricati: {len(historica_manifest_cache)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
