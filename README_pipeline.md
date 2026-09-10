# ZAC catalogues — pipeline

`run_pipeline.sh` orchestra 4 script Python in sequenza per aggiornare la versione RDF generata a partire dalle trascrizioni riviste manualmente su DataTune.

Deve essere lanciato
dalla root del progetto (lo script fa `cd` automaticamente nella propria
directory), perché `extract_collections_periods.py`, `assign_entities_via_title_match.py`
ed `enrich_artist_school.py` usano path relativi alla cwd.

OUTPUT `lot_descriptions/zac_lot_descriptions.nt`, splittato a fine run in **30 parti**

A questo va allegato manualmente `metadata/zac_catalogues_metadata_<date>.trig` (non generato da questa pipeline) per completare il grafo RDF dell'applicazione web.


## Struttura delle directory

```
project_root/
├── run_pipeline.sh
├── extract_collections_periods.py
├── assign_entities_via_title_match.py
├── align_titles.py                  # modulo, importato da assign_entities_via_title_match.py
├── enrich_artist_school.py          # nessun argomento CLI, path hardcoded
├── extracted_collections.csv        # generato/aggiornato dallo step 1
├── extracted_periods.csv            # generato/aggiornato dallo step 1
├── app/
│   ├── documents.db
│   └── generate_rdf.py
├── docling/
│   └── documents/
│       └── {CATALOGUE_ID}/
│           ├── all.md
│           └── entities.csv
├── reviewed_lots_and_entities/
│   └── {CATALOGUE_ID}.csv
└── lot_descriptions/
    ├── zac_lot_descriptions_part1.nt ... part30.nt
    └── historica_mapping.csv
```

⚠️ `app/generate_rdf.py` calcola i path dalla posizione dello *script*
(`BASE_DIR = Path(__file__).parent`), non dalla cwd: `documents.db` deve
stare in `app/`, mentre `reviewed_lots_and_entities/` e `lot_descriptions/`
sono directory sorelle di `app/` (un livello sopra).

## Requisiti di ingresso

| Path / risorsa | Necessario per | Note |
|---|---|---|
| `app/documents.db` | step 1, 2, 4 | Scaricare la versione aggiornata. Utilizza le tabelle `catalogues` (`id`, `reviewed`) e `chunks` (`id`, `catalogue_id`, `chunk_index`, `num`, `title`, `text`, `image_online`) |
| `docling/documents/{CATALOGUE_ID}/all.md` | step 2 | trascrizione integrale, righe candidate per il fuzzy match del `title` |
| `docling/documents/{CATALOGUE_ID}/entities.csv` | step 2 | colonne `line_number`, `value`, `type`; usate per il match posizionale sulle title line (`#`/`##`) |
| `reviewed_lots_and_entities/{CATALOGUE_ID}.csv` | step 3, 4 | prodotto dallo step 2, arricchito dallo step 3, letto dallo step 4 |
| Google Sheet **ZERI_NER** (id `11vB7CbMkboR2mwDneOK4RkTnaOeD1k7xi30eiv5ziZI`) | tutti gli step | tab usati: `collezioni` (gid `1845857607`), `periodi` (gid `333540236`), `artisti` (gid `910064299`), `scuole` (gid `379770645`), `oggetti` (gid `1330387938`) — devono essere pubblici/condivisi in lettura via export CSV |
| Google Sheet **Historica manifest** (id `1CC4sbzh8EtqYs16JSfTR9kUoNU9XfeJQpu3qC7ZWht0`, gid `1619304272`) | step 4 | colonne `inventario`, `manifest`; mapping catalogo → URL manifest IIIF Historica |
| `lot_descriptions/historica_mapping.csv` | step 4 | cache incrementale `catalogue_id,page_label,iiif_url`; se assente viene creata da zero (costa una scansione manifest completa) |
| Accesso di rete a `docs.google.com` (export CSV) e ai manifest IIIF Historica | step 1, 2, 3, 4 | tutti gli step scaricano gli sheet ad ogni run, nessuna cache locale delle varianti |

## Step

1. ESTRAE COLLEZIONI E PERIODI E CREA UNA LISTA CONTROLLATA **`extract_collections_periods.py`** `[--db app/documents.db] [--collections-csv extracted_collections.csv] [--periods-csv extracted_periods.csv]`

   Estrae dal solo `title`, ovvero il testo pieno del lotto collezioni e periodi/secoli via regex. Il testo pieno viene letto da `chunks` in `documents.db` per **tutti** i cataloghi — la funzione `fetch_catalogue_ids(conn, False)` -, non solo i `reviewed`.
   Ogni run **appende** solo i candidati non ancora presenti (case-insensitive) nel CSV locale né nello sheet online, poi ricalcola la colonna `new` (bool) confrontando ogni riga con lo sheet online e riordina mettendo le righe `new=True` in fondo.
   Output: `extracted_collections.csv`, `extracted_periods.csv`.
   ⚠️ Le righe con `new=True` vanno copiate manualmente nello spreadsheet ZERI_NER (tab `collezioni`/`periodi`, colonna `ZERI` da compilare) prima di proseguire — `run_pipeline.sh` si ferma qui (`exit 2`) se non usato con `--skip-review-check`. **Se non vengono aggiunti o rivisti su DataTune nuovi cataloghi e non vengono modificate le regole per estrarre collezioni/periodi, non è necessario stoppare lo script bash, che può essere lanciato con l'argomento `--skip-review-check`.**

2. ASSEGNA ENTITA AI LOTTI **`assign_entities_via_title_match.py`** `[--db app/documents.db] [--docs-dir docling/documents] [--out-dir reviewed_lots_and_entities]`
   Per ogni catalogo (revisionato e non) fa un fuzzy-match (rapidfuzz + tie-break con `sentence-transformers` per score ambigui 40–70) del `title` di ogni chunk (i.e. il testo del lotto rivisto in DataTune) contro le righe di `all.md` (OCR del catalogo completo *prima* della revisione manuale) per capire qual è il titolo precedente al lotto e se nel titolo c'erano entità (tipologie oggetti, artisti e scuole).
   - match posizionale sulla title line precedente più vicina in `entities.csv` → `entity_match_method = positional`
   - fallback: valore entità del catalogo cercato via `partial_ratio` direttamente nel `title` → `entity_match_method = title_direct` (sovrascrive il match posizionale se trovato)
   In più cerca collection/period nel `title` (stessa regex dello step 1) e li risolve contro le forme canonicalizzate (colonna `ZERI` non vuota) degli sheet `collezioni`/`periodi` riviste manualmente allo step precedente.
   Output: `reviewed_lots_and_entities/{CATALOGUE_ID}.csv` con colonne `catalogue_id, chunk_db_id, chunk_id, num, title, matched_line, match_score, low_confidence, entity_match_method, artist, school, object_type, collection, period`.

3. ASSEGNA ENTITA AI LOTTI (DI NUOVO) **`enrich_artist_school.py`** — nessun argomento, legge/scrive `./reviewed_lots_and_entities/*.csv`
   Sovrascrive i CSV aggiungendo artist/school/object_type mancanti (o, per object_type, non ancora validati) via fuzzy match (`token_set_ratio`) tra `title` e le varianti **revisionate** nello spreadsheet ZERI_NER (colonna `rivisto=TRUE`) degli sheet `artisti`, `scuole`, `oggetti`, escludendo le varianti in `da ricollocare`.

4. CREA IL GRAFO A PARTIRE DA LOTTI E ENTITA ESTRATTE **`app/generate_rdf.py`** `[--all]`
   Legge `app/documents.db` + `reviewed_lots_and_entities/*.csv`, risolve le forme canoniche via gli sheet `oggetti`/`scuole`/`artisti`, mappa i periodi a termini AAT (secoli I–XX), risolve le immagini Historica (con cache incrementale e forward/backward-fill per lotti senza `image_online`), e scrive in streaming N-Triples.
   `--all` → tutti i cataloghi; default → solo `reviewed=1`.
   Output: `lot_descriptions/zac_lot_descriptions.nt`, splittato a fine run in **30 parti** (`_part1.nt` … `_part30.nt`, limite dimensione file su GitHub) — il file singolo non sopravvive al run.
   Aggiorna anche `lot_descriptions/historica_mapping.csv`.


## Uso

```bash
./run_pipeline.sh --all --skip-review-check # USARE QUESTA

./run_pipeline.sh                     # fa step 1 + si ferma per controllo righe new=True su ZERI_NER, poi step 2-4 solo se non ci sono righe pendenti
./run_pipeline.sh --all               # fa step 4 con app/generate_rdf.py --all
./run_pipeline.sh --skip-review-check # salta il controllo, da usare dopo la revisione manuale su ZERI_NER
```
