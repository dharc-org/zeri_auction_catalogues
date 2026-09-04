# RUN ON THE SAME SERVER AS /app
# RETURN RDF OF TRANSCRIBED CATALOGUES
from __future__ import annotations
import argparse, csv, io, re, sqlite3
from pathlib import Path
from urllib.parse import unquote
import pandas as pd, requests
from rdflib import Literal, Namespace, RDF, RDFS, URIRef
from concurrent.futures import ThreadPoolExecutor, as_completed

RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
DC = Namespace("http://purl.org/dc/elements/1.1/")
CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
LA = Namespace("https://linked.art/ns/terms/")
AAT = Namespace("http://vocab.getty.edu/aat/")
ZAC = Namespace("http://w3id.org/zac/")


class NTriplesWriter:
    """Scrive N-Triples in streaming, bypassando del tutto lo store rdflib
    (oxrdflib incluso): con 16M+ triple l'overhead FFI Python<->Rust di
    16M chiamate .add() singole e' comunque significativo. Qui si scrive
    direttamente il file, una riga per triple, senza tenere nulla in
    memoria e senza fase di serialize() separata a fine run."""

    __slots__ = ("_f", "count")

    def __init__(self, path):
        self._f = open(path, "w", encoding="utf-8", buffering=1024 * 1024)
        self.count = 0

    @staticmethod
    def _term(t) -> str:
        if isinstance(t, Literal):
            val = str(t).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
            if t.datatype:
                return f'"{val}"^^<{t.datatype}>'
            if t.language:
                return f'"{val}"@{t.language}'
            return f'"{val}"'
        return f"<{t}>"

    def add(self, triple):
        s, p, o = triple
        self._f.write(f"{self._term(s)} {self._term(p)} {self._term(o)} .\n")
        self.count += 1

    def __len__(self):
        return self.count

    def close(self):
        self._f.close()


# assegnato in main() una volta noto output_path; le funzioni sotto lo
# referenziano come global, quindi vedono l'istanza reale a runtime.
g: NTriplesWriter | None = None

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

# HTTP session riusata per tutti i download (manifest Historica, sheet):
# evita di riaprire una connessione TCP/TLS ad ogni richiesta.
SESSION = requests.Session()

# secolo (numerale romano, forma canonica "ZERI" del tab periodi) -> termine AAT
AAT_CENTURY = {
    "I": "300404493",
    "II": "300404494",
    "III": "300404495",
    "IV": "300404496",
    "V": "300404497",
    "VI": "300404498",
    "VII": "300404499",
    "VIII": "300404500",
    "IX": "300404501",
    "X": "300404502",
    "XI": "300404503",
    "XII": "300404504",
    "XIII": "300404505",
    "XIV": "300404506",
    "XV": "300404465",
    "XVI": "300404510",
    "XVII": "300404511",
    "XVIII": "300404512",
    "XIX": "300404513",
    "XX": "300404514",
}

LEADING_SPECIAL_RE = re.compile(r"^[\W_]+", re.UNICODE)  # tutto cio' che non e' lettera/numero
PUNCT_SPACE_RE = re.compile(r"([.,])(?!\s|$)")


def clean_lot_title(title: str) -> str:
    title = title.strip()

    # 1. rimuove caratteri speciali iniziali (-, –, —, ecc.) fino alla prima parola/numero
    title = LEADING_SPECIAL_RE.sub("", title)

    # 3. spazio dopo "." e "," se manca
    title = PUNCT_SPACE_RE.sub(r"\1 ", title)

    # 2. prime 4 parole: se una parola ha piu' di un carattere maiuscolo al suo
    # interno (OCR che ha letto lettere miste maiuscole/minuscole), forziamo tutto maiuscolo
    words = title.split(" ")
    for i in range(min(4, len(words))):
        w = words[i]
        if sum(1 for c in w if c.isupper()) > 1:
            words[i] = w.upper()
    title = " ".join(words)

    return title


def load_sheet_tab(spreadsheet_id: str, gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    r = SESSION.get(url, timeout=60)
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
    """Riscrittura completa e ordinata: usarla SOLO una volta a fine run.
    Chiamarla dopo ogni catalogo e' O(cataloghi x dimensione_mappa) e con
    molti cataloghi diventa il vero collo di bottiglia (era questo, non
    la serializzazione, a far durare ore il run precedente)."""
    if not mapping:
        print("[historica] nessun mapping da salvare.")
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [{"catalogue_id": cid, "page_label": label, "iiif_url": url} for (cid, label), url in mapping.items()]
    df = pd.DataFrame(rows, columns=HISTORICA_MAPPING_COLUMNS).sort_values(["catalogue_id", "page_label"])
    df.to_csv(HISTORICA_MAPPING_PATH, index=False, encoding="utf-8")
    print(f"[historica] cache aggiornata: {HISTORICA_MAPPING_PATH} ({len(df)} mapping totali)")


def append_historica_mappings(rows: list[tuple[str, str, str]]):
    """Persistenza incrementale economica: appende SOLO le righe nuove
    scoperte in questo catalogo (no rewrite, no sort, no pandas). Se il run
    si interrompe, alla ripartenza load_historica_mapping() rilegge tutto
    e i duplicati vengono deduplicati automaticamente (ultimo vince)."""
    if not rows:
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = HISTORICA_MAPPING_PATH.exists()
    with open(HISTORICA_MAPPING_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(HISTORICA_MAPPING_COLUMNS)
        writer.writerows(rows)


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
    r = SESSION.get(manifest_url, timeout=60)
    r.raise_for_status()
    return r.json()


def build_historica_index(manifest: dict) -> dict[str, str]:
    """page_label normalizzata -> image url. Costruito UNA VOLTA per
    manifest invece di scansionare tutte le canvas per ogni lotto
    (era O(lotti x pagine) per catalogo, ora O(pagine) una tantum + O(1)
    per lookup)."""
    index: dict[str, str] = {}
    for sequence in manifest.get("sequences", []):
        for canvas in sequence.get("canvases", []):
            label = canvas.get("label", "")
            if isinstance(label, dict):
                label = label.get("it") or label.get("en") or label.get("@value") or ""
            label = normalize_page_label(label)
            if not label:
                continue
            images = canvas.get("images", [])
            if images:
                index[label] = images[0].get("resource", {}).get("@id")
    return index


def parse_variants(cell: str) -> list[str]:
    return [v.strip().lower() for v in str(cell).split("|") if v.strip()]


def parse_bool(cell: str) -> bool:
    return str(cell).strip().lower() in {"true", "1", "vero", "yes", "si", "sì"}


def clean(value: str) -> str:
    return re.sub(r"[^\w]+", "_", str(value).strip().lower(), flags=re.UNICODE).strip("_")


IRI_SEGMENT_RE = re.compile(r"[^\w\-.]", re.UNICODE)


def to_iri_segment(value: str) -> str:
    """Sanifica un valore per l'uso come segmento di URIRef. A differenza di
    clean(), non forza il lowercase (serve preservare lot number/id cosi'
    come sono). Necessario perche' oxrdflib/Oxigraph valida rigorosamente
    gli IRI (il default IOMemory store di rdflib era permissivo e lasciava
    passare caratteri come '[', ']', spazi, ecc. presenti nei num sporcati
    dall'OCR)."""
    return IRI_SEGMENT_RE.sub("_", str(value).strip())


def load_object_type_map(df: pd.DataFrame) -> dict[str, dict]:
    """variante_normalizzata -> {"zeri": forma canonica, "rivisto": bool}.
    Serve preservare 'rivisto' per poter distinguere i valori di object_type
    che arrivano gia' validati (dal tab oggetti) da quelli che il matching
    sui chunk ha assegnato ma che non compaiono affatto (o non sono ancora
    stati revisionati) come variante nota."""
    variant_map = {}
    for _, row in df.iterrows():
        normalized = row.get("ZERI", "").strip() or row.get("ZERI SOTTOCATEGORIA", "").strip()
        if not normalized:
            continue
        entry = {"zeri": normalized, "rivisto": parse_bool(row.get("rivisto", ""))}
        for variant in parse_variants(row.get("variants", "")):
            variant_map[variant] = entry
        variant_map[normalized.lower()] = entry
    return variant_map


def load_school_map(df: pd.DataFrame) -> dict[str, dict]:
    variant_map = {}
    for _, row in df.iterrows():
        entry = {"rivisto": parse_bool(row.get("rivisto", "")),
                  "zeri": row.get("ZERI", "").strip(),
                  "zeri_sottocategoria": row.get("ZERI SOTTOCATEGORIA", "").strip(),
                  "artista": parse_bool(row.get("artista", "")),
                  "oggetti": parse_bool(row.get("oggetti", "")),
                  "collezione": parse_bool(row.get("collezione", "")),
                  "casa d'aste": parse_bool(row.get("casa d'aste", ""))
                  }
        for variant in parse_variants(row.get("variants", "")):
            variant_map[variant] = entry
        variant_map[row.get("ZERI SOTTOCATEGORIA", "").strip().lower()] = entry
    return variant_map


def load_artist_map(df: pd.DataFrame) -> dict[str, dict]:
    variant_map = {}
    for _, row in df.iterrows():
        entry = {"rivisto": parse_bool(row.get("rivisto", "")), "zeri": row.get("ZERI", "").strip()}
        for variant in parse_variants(row.get("variants", "")):
            variant_map[variant] = entry
        variant_map[row.get("ZERI", "").strip().lower()] = entry
    return variant_map


def map_period_to_aat(period: str) -> str | None:
    return AAT_CENTURY.get(period.replace("Sec. ", "").strip().upper())


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
            by_chunk[int(row["chunk_id"])] = {
                "artist": row.get("artist", ""),
                "school": row.get("school", ""),
                "object_type": row.get("object_type", ""),
                "collection": row.get("collection", ""),
                "period": row.get("period", ""),
            }
    return by_chunk


def normalize_object_type(object_type: str, object_type_map: dict[str, dict]) -> str:
    """Solo la forma canonica, senza stato di validazione. Usata per i casi
    in cui il valore arriva gia' da una fonte a monte considerata affidabile
    (es. entity_type=='oggetti' risolto dal tab scuole, gia' 'rivisto' li')."""
    entry = object_type_map.get(object_type.strip().lower())
    return entry["zeri"] if entry else object_type.strip()


def resolve_object_type(object_type: str, object_type_map: dict[str, dict]) -> tuple[str, str]:
    """Come normalize_object_type ma restituisce anche lo stato di
    validazione, per i valori che arrivano direttamente dal csv dei chunk
    (colonna 'object_type'): se il valore non compare affatto tra le
    varianti note, o compare ma la riga non e' 'rivisto', va flaggato
    'not_validated' -- stessa logica gia' usata per artist/school."""
    entry = object_type_map.get(object_type.strip().lower())
    if entry and entry["rivisto"]:
        return entry["zeri"], "validated"
    return object_type.strip(), "not_validated"


def normalize_school(
    school: str,
    school_map: dict[str, dict]
) -> tuple[str, str | None, str, str]:
    entry = school_map.get(school.strip().lower())
    if not entry or not entry["rivisto"]:
        return school.strip(), None, 'scuola', 'not validated'

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
    return (sotto, zeri or None, 'scuola', 'validated') if sotto else (zeri or school.strip(), None, 'scuola', 'not validated')


def normalize_author(
    author: str,
    artist_map: dict[str, dict]
) -> tuple[str, str]:
    entry = artist_map.get(author.strip().lower())
    return (entry["zeri"], 'validated') if entry and entry["rivisto"] else (author.strip(), 'not validated')


def add_entity_triples(lot_id: str, author: str, school: str, object_type: str, collection: str, period: str,
                        object_type_map: dict[str, dict], school_map: dict[str, dict], artist_map: dict[str, dict]):

    catalogue_id = lot_id.split('_', 1)[0]

    if object_type:
        norm, ot_validated = resolve_object_type(object_type, object_type_map)
        object_uri = URIRef(ZAC[f"type/{clean(norm)}"])
        g.add((URIRef(ZAC[lot_id]), CRM.P2_has_type, object_uri))
        g.add((object_uri, RDFS.label, Literal(norm)))

        # stato di validazione per LOTTO (non sull'object_uri, che e' condiviso
        # tra piu' lotti): stesso pattern gia' usato per l'attribuzione autore
        type_assignment_uri = URIRef(ZAC[f"{lot_id}_object_type_assignment"])
        g.add((type_assignment_uri, RDF.type, CRM.E13_Attribute_Assignment))
        g.add((type_assignment_uri, CRM.P140_assigned_attribute_to, URIRef(ZAC[lot_id])))
        g.add((type_assignment_uri, CRM.P141_assigned, object_uri))
        g.add((type_assignment_uri, CRM.P177_assigned_property_of_type, CRM.P2_has_type))
        g.add((type_assignment_uri, CRM.P2_has_type, URIRef(ZAC[ot_validated])))

    # collezione risolta direttamente dal tab "collezioni" (colonna "collection" nel csv):
    # si affianca, non sostituisce, al caso sotto in cui e' il tab "scuole" a rivelare
    # che una riga e' in realta' una collezione
    if collection:
        for coll in collection.split(";"):
            collection_uri = URIRef(ZAC[clean(coll.strip())])
            g.add((URIRef(ZAC[catalogue_id + '_auction']), CRM.P16_used_specific_object, collection_uri))
            g.add((collection_uri, RDF.type, CRM.E78_Curated_Holding))
            g.add((collection_uri, RDFS.label, Literal(coll.strip())))
            g.add((collection_uri, CRM.P46_is_composed_of, URIRef(ZAC[lot_id])))

    # risolvi entity_type da school/author PRIMA di decidere se creare la
    # creation: righe del tab "scuole" possono in realta' essere artista,
    # oggetti, collezione o casa d'aste, non solo "scuola"
    artist_or_school, broader, entity_type, validated = None, None, None, None
    if school and not author:
        normalized = normalize_school(school, school_map)
        artist_or_school = normalized[0]
        broader = normalized[1]
        entity_type = normalized[2]
        validated = normalized[3]
    elif (author and not school) or (author and school):
        normalized = normalize_author(author, artist_map)
        artist_or_school = normalized[0]
        entity_type = 'artista'
        validated = normalized[1]

    is_actor = entity_type in ('artista', 'scuola')

    # creation: va creata solo se c'e' un vero attore (artista/scuola) o un
    # periodo. NON va creata quando school si risolve in collezione/oggetti/
    # casa d'aste: in quei casi non c'e' un evento di creazione da esprimere,
    # solo un'altra relazione (composizione di collezione, tipo, ecc.)
    creation_uri = URIRef(ZAC[f"creation_{lot_id}"])
    if is_actor or period:
        g.add((URIRef(ZAC[lot_id]), CRM.P94i_was_created_by, creation_uri))
        g.add((creation_uri, RDF.type, CRM.E65_Creation))

    if period:
        aat_id = map_period_to_aat(period)
        if aat_id:
            g.add((creation_uri, CRM["P4_has_time-span"], AAT[aat_id]))
            g.add((AAT[aat_id], RDFS.label, Literal(period)))
        else:
            print(f"  [warn] {lot_id}: periodo '{period}' non mappato a un termine AAT (AAT_CENTURY)")

    # school or artist in table "scuole"
    if is_actor:
        actor_uri = URIRef(ZAC[clean(artist_or_school)])
        g.add((creation_uri, CRM.P14_carried_out_by, actor_uri))
        g.add((actor_uri, RDFS.label, Literal(artist_or_school)))
        if 'attrib' in artist_or_school.lower() or 'zugeschrieben' in artist_or_school.lower():
            g.add((URIRef(ZAC[lot_id+'_attribution']), RDF.type, CRM.E13_Attribute_Assignment))
            g.add((URIRef(ZAC[lot_id+'_attribution']), CRM.P140_assigned_attribute_to, URIRef(ZAC[lot_id])))
            g.add((URIRef(ZAC[lot_id+'_attribution']), CRM.P141_assigned, actor_uri))
            g.add((URIRef(ZAC[lot_id+'_attribution']), CRM.P177_assigned_property_of_type, CRM.P14_carried_out_by))

        if entity_type == 'scuola':
            g.add((actor_uri, RDF.type, CRM.E74_Group))

        if entity_type == 'artista':
            g.add((actor_uri, RDF.type, CRM.E21_Person))

        if validated and validated == 'validated':
            g.add((creation_uri, CRM.P2_has_type, URIRef(ZAC['validated'])))
        else:
            g.add((creation_uri, CRM.P2_has_type, URIRef(ZAC['not_validated'])))

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

        if entity_type == 'collezione':
            collection_uri = URIRef(ZAC[clean(artist_or_school)])
            g.add((URIRef(ZAC[catalogue_id+'_auction']), CRM.P16_used_specific_object, collection_uri))
            g.add((collection_uri, RDF.type, CRM.E78_Curated_Holding))
            g.add((collection_uri, RDFS.label, Literal(artist_or_school)))
            g.add((collection_uri, CRM.P46_is_composed_of, URIRef(ZAC[lot_id])))


def fill_missing_historica_images(image_urls: list[str | None]) -> list[str | None]:
    """
    Riempie i buchi (None) nella sequenza di image_url risolti per lotto,
    in ordine di catalogo. Il caso tipico e' un lotto senza image_online
    (o con estrazione della page label fallita) che in realta' condivide
    la stessa pagina scansionata del lotto precedente.

    Regola: forward-fill (eredita dal lotto precedente). Se il buco e'
    all'inizio del catalogo e non esiste un lotto precedente risolto,
    backward-fill (eredita dal primo lotto successivo risolto).

    Non tocca i valori gia' risolti. Buchi multipli consecutivi ereditano
    tutti lo stesso valore del lotto precedente noto (nessuna interpolazione
    verso il valore successivo, che potrebbe essere una pagina diversa).
    """
    filled = list(image_urls)

    last_seen = None
    for i, url in enumerate(filled):
        if url is not None:
            last_seen = url
        elif last_seen is not None:
            filled[i] = last_seen

    next_seen = None
    for i in range(len(filled) - 1, -1, -1):
        if filled[i] is not None:
            next_seen = filled[i]
        elif next_seen is not None:
            filled[i] = next_seen

    return filled

def collect_missing_historica_page_labels(catalogues, chunks_by_catalogue, historica_mapping, historica_manifest_map) -> dict[str, set[str]]:
    needs: dict[str, set[str]] = {}
    for catalogue_id, _ in catalogues:
        manifest_url = historica_manifest_map.get(catalogue_id)
        if not manifest_url:
            continue
        for chunk in chunks_by_catalogue[catalogue_id]:
            image_online = chunk["image_online"]
            if not image_online:
                continue
            page_label = extract_historica_page_label(image_online)
            if not page_label:
                continue
            if (catalogue_id, page_label) in historica_mapping:
                continue
            needs.setdefault(manifest_url, set()).add(page_label)
    return needs


def prefetch_historica_indexes(needed_manifest_urls, max_workers: int = 10) -> dict[str, dict[str, str]]:
    index_cache: dict[str, dict[str, str]] = {}
    if not needed_manifest_urls:
        return index_cache

    def fetch_and_index(url: str):
        try:
            manifest = load_historica_manifest(url)
            return url, build_historica_index(manifest)
        except (requests.RequestException, ValueError) as e:
            print(f"  [historica] errore manifest {url}: {e}")
            return url, {}

    total = len(needed_manifest_urls)
    print(f"[historica] download/indicizzazione parallela di {total} manifest necessari...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_and_index, url) for url in needed_manifest_urls]
        for i, future in enumerate(as_completed(futures), 1):
            url, index = future.result()
            index_cache[url] = index
            if i % 20 == 0 or i == total:
                print(f"  [historica] {i}/{total} manifest indicizzati")
    return index_cache


def get_historica_image_for_lot(catalogue_id, image_online, historica_manifest_map, historica_mapping, historica_index_cache, new_historica_mappings):
    page_label = extract_historica_page_label(image_online)
    if not page_label:
        print(f"  [historica] {catalogue_id}: page label non trovato")
        return None

    key = (catalogue_id, page_label)
    if key in historica_mapping:
        return historica_mapping[key]

    manifest_url = historica_manifest_map.get(catalogue_id)
    if not manifest_url:
        print(f"  [historica] {catalogue_id}: manifest non trovato")
        return None

    # indice pagina->url costruito una sola volta per manifest (era la
    # scansione lineare ripetuta per ogni lotto: O(lotti x pagine))
    if manifest_url not in historica_index_cache:
        print(f"  [historica] DOWNLOAD + INDEX MANIFEST | {catalogue_id}")
        try:
            manifest = load_historica_manifest(manifest_url)
        except (requests.RequestException, ValueError) as e:
            print(f"  [historica] {catalogue_id}: errore manifest: {e}")
            historica_index_cache[manifest_url] = {}
            return None
        historica_index_cache[manifest_url] = build_historica_index(manifest)

    image_url = historica_index_cache[manifest_url].get(page_label)
    if not image_url:
        print(f"  [historica] {catalogue_id}: '{page_label}' non trovato")
        return None

    historica_mapping[key] = image_url
    new_historica_mappings.append((catalogue_id, page_label, image_url))
    return image_url


def process_lot_descriptions(catalogue_id, reviewed, chunks, entities_by_chunk, object_type_map, school_map, artist_map, historica_manifest_map, historica_mapping, historica_index_cache, new_historica_mappings):
    print(f"Processing {catalogue_id} ({len(chunks)} chunks, reviewed={reviewed})")

    short_id = to_iri_segment(catalogue_id.split("_", 1)[1])
    auction_uri, lots_uri = URIRef(ZAC[f"{short_id}_auction"]), URIRef(ZAC[f"{short_id}_lots"])
    g.add((auction_uri, CRM.P16_used_specific_object, lots_uri))
    g.add((lots_uri, RDF.type, LA["Set"]))
    g.add((lots_uri, CRM.P2_has_type, AAT["300411307"]))

    if reviewed:
        g.add((URIRef(ZAC[short_id]), CRM.P2_has_type, URIRef(ZAC["reviewed"])))

    # add link to manifest: WEIRD IDs
    cur_manifest = historica_manifest_map.get(catalogue_id.replace("BO0614", "BO0624"))
    if cur_manifest:
        g.add((URIRef(ZAC[short_id]), CRM.P138i_has_representation, URIRef(cur_manifest)))

    lot_uris = []
    resolved_images = []

    for chunk in chunks:
        num, title, full_text, image_online = chunk["num"], chunk["title"], chunk["text"], chunk["image_online"]
        lot_id = f"{short_id}_lot_{to_iri_segment(num)}"
        lot_uri = URIRef(ZAC[lot_id])

        # post-processing: normalise lot titles with rules
        title = clean_lot_title(title)

        g.add((lots_uri, CRM.P46_is_composed_of, lot_uri))
        g.add((lot_uri, RDF.type, LA["Set"]))

        lot_identifier_uri = URIRef(ZAC[f"{lot_id}_id"])
        g.add((lot_uri, CRM.P1_is_identified_by, lot_identifier_uri))
        g.add((lot_identifier_uri, RDF.type, CRM.E42_Identifier))
        g.add((lot_identifier_uri, CRM.P2_has_type, ZAC["lot_identifier"]))
        g.add((lot_identifier_uri, RDFS.label, Literal(f"{catalogue_id}-{num}")))

        lot_num_uri = URIRef(ZAC[f"{lot_id}_num"])
        g.add((lot_uri, CRM.P1_is_identified_by, lot_num_uri))
        g.add((lot_num_uri, RDF.type, CRM.E42_Identifier))
        g.add((lot_num_uri, CRM.P2_has_type, ZAC["lot_number"]))
        g.add((lot_num_uri, RDFS.label, Literal(num.strip())))

        title_uri = URIRef(ZAC[f"{lot_id}_title"])
        g.add((lot_uri, CRM.P102_has_title, title_uri))
        g.add((title_uri, RDFS.label, Literal(title)))
        g.add((lot_uri, RDFS.label, Literal(title)))

        description_uri = URIRef(ZAC[f"{lot_id}_description"])
        g.add((lot_uri, CRM.P67i_is_referred_to_by, description_uri))
        g.add((description_uri, RDF.type, CRM.E33_Linguistic_Object))
        g.add((description_uri, RDFS.label, Literal(full_text)))
        g.add((description_uri, CRM.P2_has_type, AAT["300435416"]))

        historica_image_url = None
        if image_online:
            historica_image_url = get_historica_image_for_lot(catalogue_id, image_online, historica_manifest_map, historica_mapping, historica_index_cache, new_historica_mappings)

        lot_uris.append(lot_uri)
        resolved_images.append(historica_image_url)

        ent = entities_by_chunk.get(chunk["chunk_index"], {})
        author, school, object_type = ent.get("artist", ""), ent.get("school", ""), ent.get("object_type", "")
        collection, period = ent.get("collection", ""), ent.get("period", "")
        add_entity_triples(lot_id, author, school, object_type, collection, period, object_type_map, school_map, artist_map)

        # TODO: crm:P57_has_number_of_parts, la:members_exemplified_by

    filled_images = fill_missing_historica_images(resolved_images)
    for lot_uri, original_url, filled_url in zip(lot_uris, resolved_images, filled_images):
        if filled_url:
            g.add((lot_uri, CRM.P138i_has_representation, URIRef(filled_url)))
            if original_url is None:
                print(f"  [historica] INFERRED FROM NEIGHBOUR LOT | {lot_uri} -> {filled_url}")


def split_nt_file(path: Path, n_parts: int = 3):
    """Divide un file .nt in n_parts file di dimensione simile (split per
    righe: ogni riga .nt e' gia' una tripla completa, quindi e' sicuro
    tagliare linea per linea senza spezzare una tripla a meta').
    Cancella l'originale dopo lo split. Nomina: stem_part1.nt, stem_part2.nt..."""
    total_lines = sum(1 for _ in open(path, "r", encoding="utf-8"))
    if total_lines == 0:
        print(f"[split] {path}: vuoto, nessuno split necessario.")
        return

    lines_per_part = -(-total_lines // n_parts)  # ceil division
    stem, suffix = path.stem, path.suffix
    part_paths = [path.with_name(f"{stem}_part{i+1}{suffix}") for i in range(n_parts)]

    with open(path, "r", encoding="utf-8") as src:
        for part_path in part_paths:
            with open(part_path, "w", encoding="utf-8") as dst:
                for _ in range(lines_per_part):
                    line = src.readline()
                    if not line:
                        break
                    dst.write(line)

    path.unlink()
    for part_path in part_paths:
        size_mb = part_path.stat().st_size / (1024 * 1024)
        print(f"[split] {part_path} ({size_mb:.1f} MB)")


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
    new_historica_mappings = []

    print("[historica] lettura chunk dal db...")
    chunks_by_catalogue = {cid: fetch_chunks(conn, cid) for cid, _ in catalogues}

    missing_by_manifest = collect_missing_historica_page_labels(catalogues, chunks_by_catalogue, historica_mapping, historica_manifest_map)
    historica_index_cache = prefetch_historica_indexes(list(missing_by_manifest.keys()))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "zac_lot_descriptions.nt"

    global g
    g = NTriplesWriter(output_path)

    try:
        for catalogue_id, reviewed in catalogues:
            chunks = chunks_by_catalogue[catalogue_id]
            entities_by_chunk = load_entities_for_catalogue(catalogue_id)
            catalogue_new_mappings: list[tuple[str, str, str]] = []
            process_lot_descriptions(catalogue_id, reviewed, chunks, entities_by_chunk, object_type_map, school_map, artist_map, historica_manifest_map, historica_mapping, historica_index_cache, catalogue_new_mappings)
            append_historica_mappings(catalogue_new_mappings)
            new_historica_mappings.extend(catalogue_new_mappings)
    finally:
        conn.close()
        g.close()

    seen, unique_new_mappings = set(), []
    for row in new_historica_mappings:
        key = (row[0], row[1])
        if key not in seen:
            seen.add(key)
            unique_new_mappings.append(row)

    # unica riscrittura completa e ordinata, a fine run (dedup + sort):
    # qui il costo O(n log n) e' pagato una volta sola, non per catalogo
    save_historica_mapping(historica_mapping)

    print(f"[write] {len(g)} triple scritte -> {output_path}")

    print("[split] divisione del file finale in 3 parti per il limite di GitHub...")
    split_nt_file(output_path, n_parts=30)

    print()
    print("=" * 50)
    print("DONE")
    print("=" * 50)
    print(f"RDF: {output_path.stem}_part[1-3]{output_path.suffix} in {output_path.parent}")
    print(f"Historica mapping CSV: {HISTORICA_MAPPING_PATH}")
    print(f"Nuovi mapping in questa run: {len(unique_new_mappings)}")
    print(f"Mapping totali in cache: {len(historica_mapping)}")
    print(f"Manifest indicizzati: {len(historica_index_cache)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
