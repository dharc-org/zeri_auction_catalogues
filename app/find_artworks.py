import sqlite3
import csv
import re
from collections import defaultdict
from pathlib import Path

DB_PATH = "documents.db"
OUTPUT_PATH = "catalogues_with_artworks_titles.csv"

ARTWORK_KEYWORDS = [
    # English
    "painting", "paintings", "picture", "pictures", "artwork", "artworks",
    "sculpture", "sculptures", "drawing", "drawings", "engraving", "engravings",
    "watercolor", "watercolour", "sketch", "sketches", "portrait", "portraits",
    "landscape", "still life", "fresco", "print", "prints", "lithograph",
    "etching", "canvas", "panel", "miniature", "tapestry", "bas-relief",
    "relief", "bust", "statuette", "bronze", "marble", "terracotta",
    # French
    "tableau", "tableaux", "peinture", "peintures", "dessin", "dessins",
    "gravure", "gravures", "aquarelle", "aquarelles", "esquisse", "esquisses",
    "portrait", "portraits", "paysage", "paysages", "nature morte", "fresque",
    "estampe", "estampes", "lithographie", "eau-forte", "panneau", "miniature",
    "tapisserie", "bas-relief", "buste", "statuette", "bronze", "marbre",
    "terre cuite", "sculpture", "sculptures", "oeuvre", "oeuvres",
    # Italian
    "dipinto", "dipinti", "pittura", "pitture", "disegno", "disegni",
    "incisione", "incisioni", "acquarello", "acquarelli", "schizzo", "schizzi",
    "ritratto", "ritratti", "paesaggio", "paesaggi", "natura morta", "affresco",
    "stampa", "stampe", "litografia", "acquaforte", "tela", "tavola",
    "miniatura", "arazzo", "bassorilievo", "busto", "statuetta", "bronzo",
    "marmo", "terracotta", "scultura", "sculture", "opera", "opere",
    "tempera", "gouache",
    # German
    "gemälde", "gemalde", "bild", "bilder", "malerei", "zeichnung", "zeichnungen",
    "stich", "stiche", "aquarell", "aquarelle", "skizze", "skizzen",
    "portrait", "porträt", "portrat", "landschaft", "landschaften", "stilleben",
    "fresko", "druckgraphik", "lithographie", "radierung", "tafel", "miniatur",
    "wandteppich", "flachrelief", "büste", "buste", "statuette", "bronze",
    "marmor", "terrakotta", "skulptur", "skulpturen", "kunstwerk", "kunstwerke",
    "holzschnitt", "kupferstich",
]

_keyword_pattern = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in ARTWORK_KEYWORDS) + r')\b',
    re.IGNORECASE
)

# Matches any line starting with one or more # characters
_heading_pattern = re.compile(r'^#{1,}\s+(.+)$', re.MULTILINE)

def extract_headings(text):
    """Return concatenated heading text from a chunk."""
    matches = _heading_pattern.findall(text)
    return ' '.join(matches)

def find_matches(text):
    return [m.lower() for m in _keyword_pattern.findall(text)]

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT catalogue_id, text FROM chunks")
    rows = cursor.fetchall()
    conn.close()

    catalogue_matches = defaultdict(list)

    for catalogue_id, text in rows:
        if not text:
            continue
        headings = extract_headings(text)
        if not headings:
            continue
        matches = find_matches(headings)
        if matches:
            catalogue_matches[catalogue_id].extend(matches)

    output = Path(OUTPUT_PATH)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["catalogue_id", "occurrences", "types"])
        for cid in sorted(catalogue_matches):
            all_matches = catalogue_matches[cid]
            unique_types = sorted(set(all_matches))
            writer.writerow([cid, len(all_matches), "|".join(unique_types)])

    print(f"Found {len(catalogue_matches)} catalogues with artworks -> {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
