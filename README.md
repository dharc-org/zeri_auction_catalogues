# Zeri Auction Catalogues

Scripts and data of 1.9K auction catalogues from the Zeri photo archive

## TL;DR

 - 1. catalogue metadata to RDF: `metadata/Zeri_cataloghi_RDF.ipynb` --> `metadata/zac_catalogues_metadata_<date>.trig`
 - 2. OCR and segmentation: `docling/ocr_chunking.py` --> `documents/<catalogue_id>/all.md` ;  `documents/<catalogue_id>/chunks.csv` ; `documents/<catalogue_id>/inconsistencies.csv`;
 - 3. online app for revision of OCR: `app/app.py`. Run in the folder `uvicorn app:app --reload`
 - 4. NER
  - 4.1 NER on section titles with Claude: `docling/extract_catalogue_entities.py` --> `docling/documents/all_entities.csv` ; `docling/documents/<ID>/entities.csv`
  - 4.2 cluster entities into labelled groups `docling/aggregate_entities_embeddings.py` --> `docling/schools.csv`; `docling/artists.csv`; `docling/object_types.csv`
  - 4.3 refines/aggregates similar clusters `postprocess_merge_csv.py` --> `docling/schools_merged2.csv`; `docling/artists_merged2.csv`; `docling/object_types_merged2.csv` uploaded on [Gsheet](https://docs.google.com/spreadsheets/d/11vB7CbMkboR2mwDneOK4RkTnaOeD1k7xi30eiv5ziZI/edit?usp=sharing) for human revision
 - 5. assign reviewed lot descriptions to ungrouped entities `assign_entities_via_title_match.py` --> `revieweed_lots_and_entities/{CATALOGUE_ID}.csv`
 - 6. retrieve aggregated and manually revised clusters of terms (schools artists types) and produce RDF graph w/ relations between catalogues + lots + entities: `app/build_lots_entities_graph.py` --> `lot_descriptions/zac_lot_descriptions.ttl`



### 1. Catalogue metadata to RDF

[PIPELINE] `metadata/Zeri_cataloghi_RDF.ipynb` --> `metadata/zac_catalogues_metadata_<date>.trig`

RDF transformation of bibliographic data from the Zeri foundation (export from Sebina), stored in a google spreadsheet (link in the notebook).

`reconciled_agents.csv` (obsolete)

Automatic reconciliation of auction houses. Outputs are uploaded in a separated tab of the above spreadsheet for human-revision.

### 2. OCR and segmentation

[ONE TIME OP / PIPELINE FOR NEW ONES] `docling/ocr_chunking.py` --> `documents/<catalogue_id>/all.md` ;  `documents/<catalogue_id>/chunks.csv` ; `documents/<catalogue_id>/inconsistencies.csv`

The folder `docling` is a virtual environment. Run the script in the folder.

The script `docling/ocr_chunking.py` accepts catalogue images available from the online IIIF endpoint (URL hardcoded in code). Returns transcriptions in markdown, all-in-one for each catalogue (e.g. `docling/documents/BO0624_4389/all.md`) and for each page (e.g. `docling/documents/BO0624_4389/BO0624_4389_000052-p. [5].jpg.md`). For each catalogue returns segmented lots in a csv file (e.g. `docling/documents/BO0624_4389/chunks.csv`) and inconsistencies found during segmentation, e.g. wrong number sequence (e.g. `docling/documents/BO0624_4389/inconsistencies.csv`). These two files are later ingested by the web app for human revision.

In detail:

 * Select pages to be parsed (those with lots description) as per the google spreadsheet including export of the databases.
 * Retrieve the IIIF images in greyscale
 * Use Docling (ocrmac) to perform OCR on single pages, which returns a md file.
 * Concat all transcriptions of each catalogue into the output file `all.md`.
 * Parse `all.md` files and perform regex to separate lot descriptions and concat them into `chunks.csv` for each catalogue.
 * Errors detected in the chunking (mainly based on numbering sequence inconsistencies) are collected in `all_inconsistencies.csv`.

`transcription.py` (obsolete)

Initial attempts with Pixtral, script used directly on the server where images are accessed on the file system

### 3. Web app for transcription revision

[PIPELINE] `app/app.py`. Run in the folder `uvicorn app:app --reload`

Ingests all `../docling/documents/<ID>/chunks.csv` and creates `documents.db` SQLite database for managing the changes made by human reviewers via web interface. Original chunks are stored in `../docling/documents/<ID>/chunks_original.csv`

### 4. Lot descriptions to RDF

This section is obsolete, see `assign_entities_via_title_match.py` and `app/build_lots_entities_graph.py --all`

[obsolete] `lot_descriptions/zac_lot_descriptions.py` --> `lot_descriptions/zac_lot_descriptions.trig`

Reads `documents.db` locally, selects catalogues that have been reviewed and returns the RDF description of lots associated to those catalogues.

[obsolete] `lot_descriptions/zac_lots_ner.csv`

Produces an initial NER from long text descriptions.

### 5. NER extraction

[PIPELINE] `docling/extract_catalogue_entities.py` --> `docling/documents/all_entities.csv` ; `docling/documents/<ID>/entities.csv`

Reads `documents.db` locally, calls Claude Sonnet 5 APIs (API key read from env -- `export ANTHROPIC_API_KEY=<KEY>`) to perform NER over section titles, returns entities in csv files (aggregated and for each folder). Notice that retrieved entities are not (yet) associated to lots, nor are disambiguated (e.g. normalised, translated, reconciled, etc.).

[ONE TIME OP] `docling/rebuild_all_entities.py` --> `docling/documents/all_entities.csv`

Fixes a bug in the concatenation of named entities in the unique file. The final file includes NER from 1815 catalogues. 73 catalogues have empty entities.csv files and must be revised.

`docling/aggregate_entities.py` --> `docling/schools.csv`; `docling/artists.csv`; `docling/object_types.csv` (obsolete)

Reads `docling/documents/all_entities.csv`, calls Claude Sonnet 5 APIs (API key read from env), and performs disambiguation of retrieved entities, returns aggregated terms and all their original occurrences for human revision.

NB. Currently performed only on a subset of ~230 catalogues. It's very expensive. The script is replaced by aggregate_entities_embeddings.py.

[PIPELINE] `docling/aggregate_entities_embeddings.py` --> `docling/schools.csv`; `docling/artists.csv`; `docling/object_types.csv`

Reads `docling/documents/all_entities.csv`, uses embeddings (HF: `paraphrase-multilingual-MiniLM-L12-v2`) to cluster variants, calls Claude Sonnet 5 APIs to evaluate clusters that may be similar. USes different weights depending on the entity_type (artists --> string similarity more than semantics; object_type --> semantics over similarity). Metrics are tuned using `tune_clustering.py`.

[PIPELINE] `postprocess_merge_csv.py` --> `docling/schools_merged.csv`; `docling/artists_merged.csv`; `docling/object_types_merged.csv`

```
# object types
python3 postprocess_merge_csv.py object_types.csv object_types_merged.csv --threshold 0.12 --string-weight 0.7 --semantic-weight 0.3
python3 postprocess_merge_csv.py object_types_merged.csv object_types_merged2.csv --threshold 0.15 --string-weight 0.1 --semantic-weight 0.9

# schools_merged
python3 postprocess_merge_csv.py schools.csv schools_merged.csv --threshold 0.12 --string-weight 0.7 --semantic-weight 0.3
python3 postprocess_merge_csv.py schools_merged.csv schools_merged2.csv --threshold 0.15 --string-weight 0.1 --semantic-weight 0.9

# artists_merged
python3 postprocess_merge_csv.py artists.csv artists_merged.csv --threshold 0.12 --string-weight 0.7 --semantic-weight 0.3
python3 postprocess_merge_csv.py artists_merged.csv artists_merged2.csv --threshold 0.15 --string-weight 0.1 --semantic-weight 0.9
```

Postprocesses the csv created with embeddings using different weights, comparing only "canonical" values (i.e. recommeded classifications) and merges rows.

The CSV files are uploaded in google spreadsheet for human revision.

### 6. Associate entities to lots

[PIPELINE] `assign_lots_to_entities.py` --> `documents/all_entities_with_lots.csv` (obsolete)

[NOT RELIABLE] Chunks again all.md using lines of entities detected with NER as boudaries, assigns lot numbers to that entity. There are several issues to be revised later (e.g. lot numbers are revised, added, deleted in app.py; entities are further aggregated and need to be reconciled i.e. aggregated and revised entity (spreadsheet) <-- raw entity (all_entities.csv) + lot numbers from raw transcription (all.md) --> revised lot numbers (documents.db) ).

[PIPELINE] `assign_entities_via_title_match.py` --> `reviewed_lots_and_entities/{CATALOGUE_ID}.csv`

Queries documents.db for catalogues already reviewed, extracts lots descriptions (title) and fuzzy matches this string in the original transcription "documents/{CATALOGUE_ID}/all.md". Then searches for entities in the description first (marked as "title_direct") and secondly, if no matches exist, retrieves the closest preceding section title line and searches in "documents/{CATALOGUE_ID}/entities.csv" for the entity extracted via NER. It creates a new csv file for each catalogue where the raw entity is associated to the lot.

## 7. Produce final RDF

`app/build_lots_entities_graph.py --all` --> `lot_descriptions/zac_lot_descriptions.ttl`

Retrieve the normalised aggregated entity label from the google spreadsheet (created for human revision of clusters https://docs.google.com/spreadsheets/d/11vB7CbMkboR2mwDneOK4RkTnaOeD1k7xi30eiv5ziZI/edit?usp=sharing), and produce RDF data for associations between lots and (cleaned) entities. This file, along with `metadata/zac_catalogues_metadata_<date>.trig` includes the whole RDF graph populating the final web application.

If `--all` the transformation is applied to all catalogues. Default behaviour on the revised catalogues only.

`historica_mapping.csv`

includes the mapping of IIIF images (from our server to AMS Historica), if applicable (i.e. if we had the page annotated correctly, and if we were able to find the corresponding page in Historica, since the naming conventions slightly differ).

TODO:

 * Add NER to lot descriptions in the last script and replace point 4
 * finalise human-revision of reconciliation and regenerate the RDF dataset to add Wikidata links
 * revise 73 catalogues that return empty NER and more that return partial NER
 * remember to add catalogues missing because the OCR failed
 * remember to add 5 new catalogues that have been lately scanned (total must be 1900 catalogues) - do the pipeline from beginning
 * associate an object type to every lot, if possible, especially for those that have an artist or school associated. Revise those that have no NER associated at all because the NER with Claude partially failed (e.g. lots that have artists' names in the text and not in the titles)
 * work on dates in lot descriptions
 * extract collection names, people names in front headers
 * associate lots to pages in AMS Historica
