# RUN ON THE SAME SERVER AS /app
# RETURN RDF OF TRANSCRIBED CATALOGUES
import sqlite3
from pathlib import Path
import rdflib
from rdflib import Namespace, URIRef, Literal, Graph, ConjunctiveGraph, RDF, RDFS, XSD
from rdflib.store import Store
import ZAC_NER

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

# Create a context-aware graph using a Memory store
g = Graph(identifier="http://w3id.org/zac/catalogues")

# Bind namespaces to the graph
g.bind("rdf", RDF)
g.bind("rdfs", RDFS)
g.bind("xsd", XSD)
g.bind("dc", DC)
g.bind("zac", ZAC)
g.bind("crm", CRM)
g.bind("la", LA)
g.bind("aat", AAT)

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "documents.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")  # safer concurrent access
    return conn


def fetch_reviewed_catalogues(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id
        FROM catalogues
        WHERE reviewed = 1
    """)
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


def process_lot_descriptions(catalogue_id, chunks):
    print(f"Processing {catalogue_id} ({len(chunks)} chunks)")

    g.add(( URIRef(ZAC[catalogue_id+'_auction']), CRM.P16_used_specific_object, URIRef(ZAC[catalogue_id+'_lots']) ))
    g.add(( URIRef(ZAC[catalogue_id+'_lots']), RDF.type, LA["Set"] ))
    g.add(( URIRef(ZAC[catalogue_id+'_lots']), CRM.P2_has_type, AAT["300411307"] ))

    for chunk in chunks:
        num = chunk["num"]
        text = chunk["title"]
        full_text = chunk["text"]
        image_online = chunk["image_online"]
        lot_id = catalogue_id+'_lot_'+num.strip()
        # part of
        g.add(( URIRef(ZAC[catalogue_id+'_lots']), CRM.P46_is_composed_of, URIRef(ZAC[lot_id]) ))
        g.add(( URIRef(ZAC[lot_id]), RDF.type, LA["Set"] ))
        g.add(( URIRef(ZAC[lot_id]), RDFS.label, Literal(num+' - '+text) ))
        # lot id
        g.add(( URIRef(ZAC[lot_id]), CRM.P1_is_identified_by, URIRef(ZAC[lot_id+'_id']) ))
        g.add(( URIRef(ZAC[lot_id+'_id']), RDF.type, CRM.E42_Identifier ))
        g.add(( URIRef(ZAC[lot_id+'_id']), RDFS.label, Literal(catalogue_id+'-'+num) ))
        # lot title
        g.add(( URIRef(ZAC[lot_id]), CRM.P102_has_title, URIRef(ZAC[lot_id+'_title']) ))
        g.add(( URIRef(ZAC[lot_id+"_title"]), RDFS.label, Literal(text) ))
        # lot description
        g.add(( URIRef(ZAC[lot_id]), CRM.P67i_is_referred_to_by, URIRef(ZAC[lot_id+'_description']) ))
        g.add(( URIRef(ZAC[lot_id+'_description']),RDF.type, CRM.E33_Linguistic_Object ))
        g.add(( URIRef(ZAC[lot_id+'_description']),RDFS.label, Literal(full_text) ))
        g.add(( URIRef(ZAC[lot_id+'_description']),CRM.P2_has_type, AAT["300435416"] )) # nota generica
        # catalogue page (not tavola)
        g.add(( URIRef(ZAC[lot_id]), CRM.P138i_has_representation, URIRef(image_online) ))

        # NER
        pipe = AuctionPipeline()
        result = pipe.process(text, reconcile=True)
        print(f"author      : {result.author}")
        print(f"school      : {result.school}")
        print(f"period      : {result.period}")
        print(f"object_type : {result.object_type}")
        print(f"ULAN        : {result.ulan_id} — {result.ulan_label}")
        print(f"AAT         : {result.aat_id} — {result.aat_label}")
        print(f"Wikidata    : {result.wikidata_id} — {result.wikidata_label}")
        
        # TODO
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

    g.serialize('zac_lot_descriptions.trig', format='trig')


def main():
    conn = get_db()
    catalogues = fetch_reviewed_catalogues(conn)

    if not catalogues:
        print("No reviewed catalogues.")
        return

    for catalogue_id in catalogues:
        chunks = fetch_chunks(conn, catalogue_id)
        process_lot_descriptions(catalogue_id, chunks)

    conn.close()


if __name__ == "__main__":
    main()
