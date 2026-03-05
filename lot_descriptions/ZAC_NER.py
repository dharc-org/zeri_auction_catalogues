"""
NER pipeline per cataloghi d'asta (IT/EN/DE)
Estrae: autore, scuola artistica, periodo, tipologia oggetto
NER via Claude API (claude-haiku-3-5)
Riconcilia con: AAT (Getty), ULAN (Getty), Wikidata

pip install anthropic requests
"""

import os
import re
import json
import time
import requests
from dataclasses import dataclass
from typing import Optional, List
from functools import lru_cache

import anthropic


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
# 2. NER CON CLAUDE API
# ─────────────────────────────────────────

SYSTEM_PROMPT = """Sei un esperto di cataloghi d'asta di opere d'arte.
Estrai le seguenti entità dal testo fornito (può essere in italiano, inglese o tedesco):
- author: nome dell'artista o autore (solo il nome, senza "attr.", "scuola di", ecc.)
- school: scuola artistica, bottega, cerchia, seguace, attr. a (tutta la stringa incluso "Scuola di", "Follower of", ecc.)
- period: periodo o datazione (es. "XVII secolo", "ca. 1650", "1580-1620", "16. Jahrhundert")
- object_type: tipologia dell'oggetto (es. "dipinto", "scultura", "tappezzeria", "bronzo", "oil on panel")

Regole:
- Se author e school sono presenti, author è il nome nudo (es. "Tiziano"), school è la relazione (es. "Scuola di Tiziano")
- Se è solo "attr. a X" o "Follower of X", metti null in author e la stringa completa in school
- Se l'autore è certo (nome senza qualificatori), metti il nome in author e null in school
- Rispondi SOLO con un oggetto JSON valido, nessun testo aggiuntivo, nessun markdown.

Formato risposta:
{"author": "...", "school": "...", "period": "...", "object_type": "..."}
"""


class AuctionNER:
    """NER via Claude API (claude-haiku). Nessuna dipendenza ML locale."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-haiku-4-5-20251001"):
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )
        self.model = model

    def extract(self, text: str) -> dict:
        empty = {"author": None, "school": None, "period": None, "object_type": None}
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}]
            )
            raw = message.content[0].text.strip()
            # Rimuovi eventuale markdown ```json ... ```
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
            # Normalizza: valori vuoti o "null" stringa → None
            for k in empty:
                v = parsed.get(k)
                if not v or str(v).lower() in ("null", "none", ""):
                    parsed[k] = None
            return {**empty, **parsed}
        except Exception as e:
            print(f"Claude API error: {e}")
            return empty

    def extract_batch(self, texts: List[str], delay: float = 0.1) -> List[dict]:
        results = []
        for text in texts:
            results.append(self.extract(text))
            time.sleep(delay)
        return results


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
    def __init__(self, api_key: Optional[str] = None):
        self.ner = AuctionNER(api_key=api_key)
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

    def process_batch(self, texts: List[str], **kwargs) -> List[ArtworkEntity]:
        return [self.process(t, **kwargs) for t in texts]


# ─────────────────────────────────────────
# 7. ESEMPIO USO
# ─────────────────────────────────────────

#if __name__ == "__main__":
    # samples = [
    #     "Scuola di Tiziano, dipinto su tela raffigurante la Vergine, XVII secolo",
    #     "Follower of Rembrandt van Rijn, oil on panel, ca. 1650",
    #     "Umkreis des Lucas Cranach d.Ä., Gemälde auf Holz, 16. Jahrhundert",
    #     "Attr. a Giovanni Bellini, Madonna col Bambino, fine XV secolo",
    #     "Tappezzeria fiamminga, lana e seta, 1580-1620",
    # ]
    #
    # # API key: passa direttamente o imposta variabile d'ambiente ANTHROPIC_API_KEY
    # # export ANTHROPIC_API_KEY="sk-ant-..."
    # pipe = AuctionPipeline()  # oppure AuctionPipeline(api_key="sk-ant-...")
    #
    # for text in samples:
    #     print(f"\n{'─'*60}")
    #     print(f"INPUT : {text}")
    #     result = pipe.process(text, reconcile=True)
    #     print(f"author      : {result.author}")
    #     print(f"school      : {result.school}")
    #     print(f"period      : {result.period}")
    #     print(f"object_type : {result.object_type}")
    #     print(f"ULAN        : {result.ulan_id} — {result.ulan_label}")
    #     print(f"AAT         : {result.aat_id} — {result.aat_label}")
    #     print(f"Wikidata    : {result.wikidata_id} — {result.wikidata_label}")
