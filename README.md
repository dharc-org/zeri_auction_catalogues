# Zeri Auction Catalogues

Scripts and data of 1.9K auction catalogues from the Zeri photo archive



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

[PIPELINE] `lot_descriptions/zac_lot_descriptions.py` --> `lot_descriptions/zac_lot_descriptions.trig`

Reads `documents.db` locally, selects catalogues that have been reviewed and returns the RDF description of lots associated to those catalogues.

`lot_descriptions/zac_lots_ner.csv` (obsolete)

Produces an initial NER from long text descriptions.

### 5. NER extraction

[PIPELINE] `docling/extract_catalogue_entities.py` --> `docling/documents/all_entities.csv` ; `docling/documents/<ID>/entities.csv`

Reads `documents.db` locally, calls Claude Sonnet 5 APIs (API key read from env -- `export ANTHROPIC_API_KEY=<KEY>`) to perform NER over section titles, returns entities in csv files (aggregated and for each folder). Notice that retrieved entities are not (yet) associated to lots, nor are disambiguated (e.g. normalised, translated, reconciled, etc.).

[ONE TIME OP] `docling/rebuild_all_entities.py` --> `docling/documents/all_entities.csv`

Fixes a bug in the concatenation of named entities in the unique file. The final file includes NER from 1815 catalogues. 73 catalogues have empty entities.csv files and must be revised.

`docling/aggregate_entities.py` --> `docling/schools.csv`; `docling/artists.csv`; `docling/object_types.csv`

Reads `docling/documents/all_entities.csv`, calls Claude Sonnet 5 APIs (API key read from env), and performs disambiguation of retrieved entities, returns aggregated terms and all their original occurrences for human revision.

NB. Currently performed only on a subset of ~230 catalogues.

TODO:

 * finalise human-revision of reconciliation and regenerate the RDF dataset to add Wikidata links
 * aggregate entities extracted with NER
 * associate Named entities to lots
 * revised 73 catalogues returning empty NER
 * remember to add catalogues missing because the OCR failed
 * remember to add 5 new catalogues that have been lately scanned (total must be 1900 catalogues) - do the pipeline from beginning
