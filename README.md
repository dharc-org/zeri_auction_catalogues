# Zeri Auction Catalogues

Scripts and data of 1.9K auction catalogues from the Zeri photo archive

### TLDR;

 * RDF transformation: `Zeri_cataloghi_RDF.ipynb`
 * OCR and segmentation: `docling/ocr_chunking.py`
 * Web app for transcription revision: `app/app.py`

## RDF transformation

`Zeri_cataloghi_RDF.ipynb` --> `zac_catalogues_<date>.trig` ; `reconciled_agents.csv`

RDF transformation of bibliographic data from the Zeri foundation (export from Sebina), stored in a google spreadsheet (link in the notebook).

Automatic reconciliation of auction houses. Outputs are uploaded in a separated tab of the above spreadsheet for human-revision.

TODO:

 * finalise human-revision of reconciliation
 * regenerate the RDF dataset to add Wikidata links
 * revise classes assignment to people / groups (incorrect)
 * remove duplicate entities (different forms of same name in the original data generate different URIs)
 * add transformation to RDF of lot descriptions revised in the app (e.g. input `docling/documents/BO0624_4389/chunks.csv`, if the catalogue is marked as reviewed in `app/reviewed_status.csv`).

## OCR and segmentation

`docling/ocr_chunking.py` --> `documents/<catalogue_id>/all.md` ;  `documents/<catalogue_id>/chunks.csv` ; `documents/<catalogue_id>/inconsistencies.csv`

The folder `docling` is a virtual environment. Run the script in the folder.

The script `docling/ocr_chunking.py` accepts catalogue images available from the IIIF endpoint. Returns transcriptions in markdown, all-in-one for each catalogue (`docling/documents/BO0624_4389/all.md`) and for each page (e.g. `docling/documents/BO0624_4389/BO0624_4389_000052-p. [5].jpg.md`). For each catalogue returns segmented lots (e.g. `docling/documents/BO0624_4389/chunks.csv`) and inconsistencies (e.g. `docling/documents/BO0624_4389/inconsistencies.csv`).  

 * Select pages to be parsed (those with lots description) as per the google spreadsheet including export of the databases.
 * Retrieve the IIIF images in greyscale
 * Use Docling (ocrmac) to perform OCR on single pages, which returns a md file.
 * Concat all transcriptions of each catalogue into the output file `all.md`.
 * Parse `all.md` files and perform regex to separate lot descriptions and concat them into `chunks.csv` for each catalogue.
 * Errors detected in the chunking (mainly based on numbering sequence inconsistencies) are collected in `all_inconsistencies.csv`, also included in the spreadsheet.

`transcription.py`

Initial attempts with Pixtral, script used directly on the server where images are accessed on the file system


## Web app for transcription revision

`app/app.py`. Run in the folder `uvicorn app:app --reload`

TODO:

 * integrate RDF transformation
