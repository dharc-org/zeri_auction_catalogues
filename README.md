# Zeri Auction Catalogues

Scripts and data of 1.9K auction catalogues from the Zeri photo archive

## RDF transformation

`Zeri_cataloghi_RDF.ipynb` --> `zac_catalogues_<date>.trig` ; `reconciled_agents.csv`

RDF transformation of bibliographic data from the Zeri foundation (export from Sebina), stored in a google spreadsheet (link in the notebook).

Automatic reconciliation of auction houses. Outputs are uploaded in a separated tab of the above spreadsheet for human-revision.

TODO:

 * finalise human-revision of reconciliation
 * regenerate the RDF dataset to add Wikidata links
 * revise classes assignment to people / groups (incorrect)
 * remove duplicate entities (different forms of same name in the original data generate different URIs)

## OCR

`transcription.py`

Initial attempts with Pixtral, script used directly on the server where images are accessed on the file system

`1_ocr.py` --> `all.md`

Select pages to be parsed (those with lots description) from a given list, transform images in greyscale, and use Docling to perform OCR of pages. Concat all transcriptions of each catalogue into the output file `all.md`. The script is run locally on a benchmark group of catalogue images, outputs not included here.

`2_chunking.py` --> `all_chunks.csv` ; `inconsistencies.csv`

Parses `all.md` files, performs regex to separate lot descriptions and concat them into `chunks.csv` for each catalogue (not included here). All chunks are concat in `all_chunks.csv`, available on the aforementioned spreadsheet for human revision. Errors detected in the chunking (mainly based on numbering sequence inconsistencies) are collected in `inconsistencies.csv`, also included in the spreadsheet.

TODO:

 * improve chunking docling:
   * e.g. "203 bis."
   * wrong numbers at the beginning of lines (from OCR) that split one lot in two. e.g. "18. bla \n 2.bla \n 19. bla"
   * update inconsistencies after merging lines
 * finalise pipeline for pixtral with the same benchmark group of images
 * compare outputs of both pipelines
