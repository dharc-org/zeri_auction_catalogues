"""
NER pipeline per cataloghi d'asta (IT/EN/DE)
Estrae: autore, scuola artistica, periodo, tipologia oggetto
Riconcilia con: AAT (Getty), ULAN (Getty), Wikidata
"""

import re
import time
import requests
from dataclasses import dataclass, field
from typing import Optional
from functools import lru_cache

# --- pip install gliner spacy requests ---
# python -m spacy download xx_ent_wiki_sm  (fallback multilingue)


# ─────────────────────────────────────────
# 1. DATA STRUCTURES
# ─────────────────────────────────────────

@dataclass
class ArtworkEntity:
    text: str                          # testo originale
    author: Optional[str] = None
    school: Optional[str] = None       # scuola/bottega/cerchia
    period: Optional[str] = None       # es. "XVII secolo", "1650-1700"
    object_type: Optional[str] = None  # dipinto, scultura, tappezzeria...
    # Reconciliation results
    ulan_id: Optional[str] = None
    ulan_label: Optional[str] = None
    aat_id: Optional[str] = None
    aat_label: Optional[str] = None
    wikidata_id: Optional[str] = None
    wikidata_label: Optional[str] = None


# ─────────────────────────────────────────
# 2. NER CON GLINER (zero-shot, multilingue)
# ─────────────────────────────────────────

class AuctionNER:
    """
    GLiNER: modello zero-shot per NER con label personalizzate.
    Funziona su IT/EN/DE senza fine-tuning.
    Repo: https://github.com/urchade/GLiNER
    """

    LABELS = [
        "person",           # autore / artista
        "art school",       # scuola artistica, bottega, cerchia
        "time period",      # secolo, datazione, periodo storico
        "object type",      # tipologia oggetto d'arte
    ]

    def __init__(self, model_name: str = "urchade/gliner_multi-v2.1"):
        try:
            from gliner import GLiNER
            self.model = GLiNER.from_pretrained(model_name)
            self._use_gliner = True
        except ImportError:
            print("GLiNER non installato. Uso fallback regex.")
            self._use_gliner = False

    def extract(self, text: str, threshold: float = 0.4) -> dict:
        if self._use_gliner:
            "Usa gliner"
            return self._gliner_extract(text, threshold)
        return self._regex_fallback(text)

    def _gliner_extract(self, text: str, threshold: float) -> dict:
        entities = self.model.predict_entities(text, self.LABELS, threshold=threshold)
        result = {"author": None, "school": None, "period": None, "object_type": None}
        for ent in entities:
            label = ent["label"]
            val = ent["text"].strip()
            if label == "person" and not result["author"]:
                result["author"] = val
            elif label == "art school" and not result["school"]:
                result["school"] = val
            elif label == "time period" and not result["period"]:
                result["period"] = val
            elif label == "object type" and not result["object_type"]:
                result["object_type"] = val
        return result

    def _regex_fallback(self, text: str) -> dict:
        """Regex multilingue come fallback."""
        result = {"author": None, "school": None, "period": None, "object_type": None}

        # Periodo: "XVII secolo", "17th century", "17. Jahrhundert", "ca. 1650", "1620-1680"
        period_patterns = [
            r'\b(?:ca\.?\s*)?\d{4}(?:\s*[-–]\s*\d{2,4})?\b',
            r'\b[IVXLCDM]+\s+(?:secolo|sec\.|century|Jahrhundert)\b',
            r'\b\d+(?:st|nd|rd|th)\s+century\b',
            r'\b\d+\.\s*Jahrhundert\b',
        ]
        for pat in period_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                result["period"] = m.group(0).strip()
                break

        # Scuola: "Scuola veneziana", "School of ...", "Schule des ..."
        school_patterns = [
            r'(?:Scuola|Bottega|Cerchia|Seguace)\s+(?:di\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            r'(?:School|Circle|Workshop|Studio|Follower)\s+of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            r'(?:Schule|Werkstatt|Umkreis|Nachfolge)\s+(?:des?\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            r'(?:maniera|attr(?:ibuito)?\.?\s+a)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        ]
        for pat in school_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                result["school"] = m.group(0).strip()
                break

        # Tipologia oggetto
        obj_patterns = [
            r'\b(?:dipinto|tela|tavola|affresco|acquerello|disegno|incisione|stampa)\b',
            r'\b(?:scultura|statua|busto|rilievo|bronzo|marmo|terracotta)\b',
            r'\b(?:tappezzeria|arazzo|tessuto|ricamo)\b',
            r'\b(?:painting|canvas|panel|drawing|print|engraving)\b',
            r'\b(?:sculpture|statue|bust|bronze|marble)\b',
            r'\b(?:Gemälde|Leinwand|Zeichnung|Skulptur|Bronze)\b',
        ]
        for pat in obj_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                result["object_type"] = m.group(0).strip()
                break

        return result


# ─────────────────────────────────────────
# 3. RECONCILIATION: ULAN (Getty)
# ─────────────────────────────────────────

class ULANReconciler:
    """
    Getty ULAN SPARQL endpoint.
    Cerca artisti/architetti per nome.
    """
    ENDPOINT = "https://vocab.getty.edu/sparql.json"

    @lru_cache(maxsize=256)
    def search(self, name: str, lang: str = "it") -> Optional[dict]:
        if not name:
            return None
        query = f"""
        SELECT ?subject ?label WHERE {{
          ?subject a gvp:PersonConcept ;
                   skos:prefLabel|skos:altLabel ?label .
          FILTER(regex(str(?label), "{re.escape(name)}", "i"))
        }} LIMIT 3
        """
        try:
            r = requests.get(
                self.ENDPOINT,
                params={"query": query, "Accept": "application/sparql-results+json"},
                timeout=10
            )
            r.raise_for_status()
            bindings = r.json().get("results", {}).get("bindings", [])
            if bindings:
                b = bindings[0]
                uri = b["subject"]["value"]
                ulan_id = uri.split("/")[-1]
                return {"id": ulan_id, "label": b["label"]["value"], "uri": uri}
        except Exception as e:
            print(f"ULAN error for '{name}': {e}")
        return None


# ─────────────────────────────────────────
# 4. RECONCILIATION: AAT (Getty)
# ─────────────────────────────────────────

class AATReconciler:
    """
    Getty AAT SPARQL endpoint.
    Cerca tipologie oggetto e concetti artistici.
    """
    ENDPOINT = "https://vocab.getty.edu/sparql.json"

    # Mapping rapido per termini comuni (evita chiamate API superflue)
    LOCAL_MAP = {
        "dipinto": ("300033618", "paintings"),
        "tela": ("300014078", "canvas"),
        "scultura": ("300047090", "sculpture"),
        "bronzo": ("300010957", "bronze"),
        "marmo": ("300011443", "marble"),
        "tappezzeria": ("300215302", "tapestries"),
        "disegno": ("300033973", "drawings"),
        "incisione": ("300041365", "prints"),
        "painting": ("300033618", "paintings"),
        "sculpture": ("300047090", "sculpture"),
        "drawing": ("300033973", "drawings"),
        "Gemälde": ("300033618", "paintings"),
        "Skulptur": ("300047090", "sculpture"),
    }

    @lru_cache(maxsize=256)
    def search(self, term: str) -> Optional[dict]:
        if not term:
            return None
        # Prova local map prima
        for key, (aat_id, label) in self.LOCAL_MAP.items():
            if key.lower() in term.lower():
                return {"id": aat_id, "label": label,
                        "uri": f"http://vocab.getty.edu/aat/{aat_id}"}
        # Fallback SPARQL
        query = f"""
        SELECT ?subject ?label WHERE {{
          ?subject a skos:Concept ;
                   skos:prefLabel|skos:altLabel ?label .
          ?subject skos:inScheme <http://vocab.getty.edu/aat/> .
          FILTER(regex(str(?label), "{re.escape(term)}", "i"))
        }} LIMIT 3
        """
        try:
            r = requests.get(
                self.ENDPOINT,
                params={"query": query, "Accept": "application/sparql-results+json"},
                timeout=10
            )
            r.raise_for_status()
            bindings = r.json().get("results", {}).get("bindings", [])
            if bindings:
                b = bindings[0]
                uri = b["subject"]["value"]
                aat_id = uri.split("/")[-1]
                return {"id": aat_id, "label": b["label"]["value"], "uri": uri}
        except Exception as e:
            print(f"AAT error for '{term}': {e}")
        return None


# ─────────────────────────────────────────
# 5. RECONCILIATION: WIKIDATA
# ─────────────────────────────────────────

class WikidataReconciler:
    """
    Wikidata reconciliation via API wbsearchentities.
    Utile per autori e scuole artistiche.
    """
    API = "https://www.wikidata.org/w/api.php"

    @lru_cache(maxsize=256)
    def search(self, query: str, lang: str = "it", entity_type: str = "item") -> Optional[dict]:
        if not query:
            return None
        params = {
            "action": "wbsearchentities",
            "search": query,
            "language": lang,
            "format": "json",
            "limit": 3,
            "type": entity_type,
        }
        try:
            r = requests.get(self.API, params=params, timeout=10,
                             headers={"User-Agent": "AuctionNER/1.0"})
            r.raise_for_status()
            results = r.json().get("search", [])
            if results:
                best = results[0]
                return {
                    "id": best["id"],
                    "label": best.get("label", ""),
                    "description": best.get("description", ""),
                    "uri": best.get("concepturi", f"https://www.wikidata.org/entity/{best['id']}")
                }
        except Exception as e:
            print(f"Wikidata error for '{query}': {e}")
        return None


# ─────────────────────────────────────────
# 6. PIPELINE COMPLETA
# ─────────────────────────────────────────

class AuctionPipeline:
    def __init__(self):
        self.ner = AuctionNER()
        self.ulan = ULANReconciler()
        self.aat = AATReconciler()
        self.wikidata = WikidataReconciler()

    def process(self, text: str, reconcile: bool = True, delay: float = 0.5) -> ArtworkEntity:
        entity = ArtworkEntity(text=text)

        # NER
        extracted = self.ner.extract(text)
        entity.author = extracted.get("author")
        entity.school = extracted.get("school")
        entity.period = extracted.get("period")
        entity.object_type = extracted.get("object_type")

        if not reconcile:
            return entity

        # Reconciliation autore → ULAN + Wikidata
        if entity.author:
            ulan = self.ulan.search(entity.author)
            if ulan:
                entity.ulan_id = ulan["id"]
                entity.ulan_label = ulan["label"]
            time.sleep(delay)

            wd = self.wikidata.search(entity.author)
            if wd:
                entity.wikidata_id = wd["id"]
                entity.wikidata_label = wd["label"]
            time.sleep(delay)

        # Reconciliation scuola → Wikidata (se autore non trovato)
        if entity.school and not entity.wikidata_id:
            wd = self.wikidata.search(entity.school)
            if wd:
                entity.wikidata_id = wd["id"]
                entity.wikidata_label = wd["label"]
            time.sleep(delay)

        # Reconciliation tipologia → AAT
        if entity.object_type:
            aat = self.aat.search(entity.object_type)
            if aat:
                entity.aat_id = aat["id"]
                entity.aat_label = aat["label"]
            time.sleep(delay)

        return entity

    def process_batch(self, texts: list[str], **kwargs) -> list[ArtworkEntity]:
        return [self.process(t, **kwargs) for t in texts]


# ─────────────────────────────────────────
# 7. ESEMPIO USO
# ─────────────────────────────────────────

# if __name__ == "__main__":
#     samples = [
#         "Scuola di Tiziano, dipinto su tela raffigurante la Vergine, XVII secolo",
#         "Follower of Rembrandt van Rijn, oil on panel, ca. 1650",
#         "Umkreis des Lucas Cranach d.Ä., Gemälde auf Holz, 16. Jahrhundert",
#         "Attr. a Giovanni Bellini, Madonna col Bambino, fine XV secolo",
#         "Tappezzeria fiamminga, lana e seta, 1580-1620",
#     ]
#
#     pipe = AuctionPipeline()
#
#     for text in samples:
#         print(f"\n{'─'*60}")
#         print(f"INPUT : {text}")
#         result = pipe.process(text, reconcile=True)
#         print(f"author      : {result.author}")
#         print(f"school      : {result.school}")
#         print(f"period      : {result.period}")
#         print(f"object_type : {result.object_type}")
#         print(f"ULAN        : {result.ulan_id} — {result.ulan_label}")
#         print(f"AAT         : {result.aat_id} — {result.aat_label}")
#         print(f"Wikidata    : {result.wikidata_id} — {result.wikidata_label}")
