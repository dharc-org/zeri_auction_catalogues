"""
aggregate_entities_embeddings.py — Colab version

Legge le entità da un Google Sheet (export CSV nativo, non gviz),
clusterizza con embeddings multilingue (gratis, locale) e usa Claude
solo per i cluster ambigui/borderline.

Colonne attese nel foglio: type, value  (eventualmente altre, ignorate)
"""

# ---------------------------------------------------------------------------
# 0. Setup (Colab)
# ---------------------------------------------------------------------------
# !pip install -q sentence-transformers scikit-learn anthropic

from __future__ import annotations

import os
os.environ["USE_TF"] = "0"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"

import io
import csv
import requests
import numpy as np
import pandas as pd
from collections import Counter
from sklearn.cluster import AgglomerativeClustering
from rapidfuzz.distance import JaroWinkler
from sentence_transformers import SentenceTransformer


import anthropic

# ---------------------------------------------------------------------------
# 1. Config
# ---------------------------------------------------------------------------

SPREADSHEET_ID = "11vB7CbMkboR2mwDneOK4RkTnaOeD1k7xi30eiv5ziZI"  # <-- sostituisci
GID = "1558577704"  # <-- sostituisci con il gid del tab specifico (Entities)

DISTANCE_THRESHOLD = 0.15   # fallback di default, sovrascritto da PER_TYPE_CONFIG
AMBIGUOUS_LOW = 0.12
AMBIGUOUS_HIGH = 0.25
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
CLAUDE_MODEL = "claude-sonnet-5"

#ENTITY_TYPES = ["object_type", "school", "artist"]
ENTITY_TYPES = ["artist"]

# Peso stringa/semantica e soglia per tipo di entità.
# artist: nomi propri, typo/abbreviazioni -> string similarity domina.
# school/object_type: frasi descrittive, spesso tradotte tra lingue senza
#   overlap lessicale (es. "Olgemalde alter Meister" / "OLD PAINTINGS") ->
#   semantica domina, string similarity conta poco o nulla.
PER_TYPE_CONFIG = {
    "artist":      {"string_weight": 0.7, "semantic_weight": 0.3, "distance_threshold": 0.15},
    "school":      {"string_weight": 0.2, "semantic_weight": 0.8, "distance_threshold": 0.25},
    "object_type": {"string_weight": 0.1, "semantic_weight": 0.9, "distance_threshold": 0.30},
}

# ---------------------------------------------------------------------------
# 2. Load data from Google Sheet (native CSV export, no gviz type-inference)
# ---------------------------------------------------------------------------

def load_sheet(spreadsheet_id: str, gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    r = requests.get(url)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def normalize(value: str) -> str:
    # NB: niente .upper() qui — l'uppercase distorce gli embedding semantici
    # dei modelli sentence-transformer, addestrati su testo con casing naturale.
    return " ".join(value.strip().split())


# ---------------------------------------------------------------------------
# 3. Embedding clustering
# ---------------------------------------------------------------------------

# def cluster_values(model: SentenceTransformer, values: list[str],
#                     string_weight: float = 0.5, semantic_weight: float = 0.5,
#                     threshold: float = None, candidate_semantic_radius: float = 0.5,
#                     block_size: int = 2000):
#     """Clustering scalabile per grandi n (decine di migliaia di valori).
#
#     L'approccio precedente (matrice di distanza completa n x n, sia per
#     string-similarity con loop Python sia per AgglomerativeClustering
#     precomputed) è O(n^2) in tempo E memoria: a 55k valori richiede ~1.5
#     miliardi di confronti Python (ore/giorni) e ~12GB di RAM solo per la
#     matrice. Impraticabile.
#
#     Fix (blocking, tecnica standard in entity resolution su larga scala):
#     1. Calcola similarità semantica a blocchi via moltiplicazione di matrici
#        (numpy/BLAS, velocissimo: pochi secondi anche per 55k valori),
#        MAI materializzando la matrice n x n intera in memoria.
#     2. Per ogni valore, tiene solo i candidati con distanza semantica sotto
#        una soglia larga (candidate_semantic_radius) — la maggior parte delle
#        coppie viene scartata qui, gratis.
#     3. Solo sui candidati (pochi per riga, non n) calcola la string-similarity
#        (rapidfuzz), che è l'operazione costosa in puro Python.
#     4. Usa union-find (componenti connesse) invece di AgglomerativeClustering:
#        equivalente a linkage single/complete su un grafo sparso, niente
#        matrice piena da allocare.
#
#     Se le entità reali (typo/abbreviazioni) sono in generale semanticamente
#     vicine anche se non identiche — ipotesi ragionevole per nomi propri
#     variati/abbreviati — questo non perde recall rispetto all'approccio
#     completo, ma è ordini di grandezza più veloce.
#     """
#     if threshold is None:
#         threshold = DISTANCE_THRESHOLD
#
#     n = len(values)
#     embeddings = model.encode(values, normalize_embeddings=True,
#                                batch_size=256, show_progress_bar=True)
#
#     parent = list(range(n))
#
#     def find(x):
#         while parent[x] != x:
#             parent[x] = parent[parent[x]]
#             x = parent[x]
#         return x
#
#     def union(x, y):
#         px, py = find(x), find(y)
#         if px != py:
#             parent[px] = py
#
#     lower_values = [v.lower() for v in values]
#
#     print(f"    Blocking: {n} valori, block_size={block_size}...")
#     for start in range(0, n, block_size):
#         end = min(start + block_size, n)
#         block = embeddings[start:end]              # (b, d)
#         sims = block @ embeddings.T                 # cosine sim, embeddings già normalizzati
#         sem_dist_block = 1.0 - sims                 # (b, n)
#
#         for i_local in range(end - start):
#             i_global = start + i_local
#             row = sem_dist_block[i_local]
#             candidates = np.where(row <= candidate_semantic_radius)[0]
#             for j in candidates:
#                 if j <= i_global:
#                     continue
#                 sim_str = JaroWinkler.normalized_similarity(lower_values[i_global], lower_values[j])
#                 d_combined = string_weight * (1.0 - sim_str) + semantic_weight * row[j]
#                 if d_combined <= threshold:
#                     union(i_global, j)
#
#         if (start // block_size) % 5 == 0:
#             print(f"      blocco {start}-{end}/{n}...")
#
#     labels = np.array([find(i) for i in range(n)])
#     return labels, embeddings
#
#
# def build_groups(values: list[str], counts: Counter, labels: np.ndarray) -> list[dict]:
#     groups_map: dict[int, list[str]] = {}
#     for val, lab in zip(values, labels):
#         groups_map.setdefault(lab, []).append(val)
#
#     groups = []
#     for lab, variants in groups_map.items():
#         canonical = max(variants, key=lambda v: counts[v])
#         groups.append({
#             "canonical": canonical,
#             "variants": sorted(set(variants)),
#             "count": sum(counts[v] for v in variants),
#         })
#     return groups

def cluster_values(model: SentenceTransformer, values: list[str],
                    string_weight: float = 0.5, semantic_weight: float = 0.5,
                    threshold: float = None, block_size: int = 2000):
    """Clustering scalabile per grandi n (decine di migliaia di valori).

    Fase 1 — per ogni blocco calcola SIA la distanza semantica SIA la
    string-similarity per l'intero blocco in un colpo solo, vettorizzato:
    - similarità semantica: moltiplicazione di matrici (numpy/BLAS)
    - string-similarity: rapidfuzz.process.cdist (C, multi-thread)
    Il collo di bottiglia della versione precedente era proprio qui: un
    doppio loop Python che chiamava JaroWinkler un valore alla volta sui
    candidati — con nomi corti l'embedding è poco discriminante, quindi
    ogni riga produceva migliaia di candidati e il loop esplodeva in ore.
    cdist calcola l'intero blocco in blocco unico, ordini di grandezza
    più veloce, senza pre-filtro di candidati (non serve più).

    Fase 2 — merge a COMPLETE-LINKAGE (non union-find): un merge tra due
    gruppi è permesso solo se OGNI coppia di membri tra i due gruppi ha
    distanza <= threshold. Union-find (single-linkage) è soggetto a
    "chaining": se A~B e B~C, A e C finiscono uniti anche se scorrelati,
    collassando tutto in una mega-cluster (bug osservato in precedenza).
    """
    from rapidfuzz import process
    from rapidfuzz.distance import JaroWinkler

    if threshold is None:
        threshold = DISTANCE_THRESHOLD

    n = len(values)
    embeddings = model.encode(values, normalize_embeddings=True,
                               batch_size=256, show_progress_bar=True)
    lower_values = [v.lower() for v in values]

    dist_lookup: dict[tuple[int, int], float] = {}
    candidate_edges: list[tuple[float, int, int]] = []

    print(f"    Blocking: {n} valori, block_size={block_size}...")
    for start in range(0, n, block_size):
        end = min(start + block_size, n)

        sims = embeddings[start:end] @ embeddings.T           # (b, n)
        sem_dist_block = 1.0 - sims

        str_sim_block = process.cdist(
            lower_values[start:end], lower_values,
            scorer=JaroWinkler.normalized_similarity, workers=-1,
        )                                                      # (b, n), valori in [0,1]
        str_dist_block = 1.0 - str_sim_block

        combined_block = string_weight * str_dist_block + semantic_weight * sem_dist_block

        for i_local in range(end - start):
            i_global = start + i_local
            row = combined_block[i_local]
            # solo j > i_global per evitare doppioni (i-j e j-i)
            tail = row[i_global + 1:]
            hits = np.where(tail <= threshold)[0] + (i_global + 1)
            for j in hits:
                d = float(row[j])
                dist_lookup[(i_global, int(j))] = d
                candidate_edges.append((d, i_global, int(j)))

        print(f"      blocco {start}-{end}/{n} ({len(candidate_edges)} coppie finora)...")

    print(f"    {len(candidate_edges)} coppie candidate sotto soglia, merge a complete-linkage...")
    candidate_edges.sort(key=lambda e: e[0])

    cluster_of = list(range(n))
    clusters: dict[int, set] = {i: {i} for i in range(n)}

    def get_dist(a: int, b: int) -> float:
        key = (a, b) if a < b else (b, a)
        return dist_lookup.get(key, float("inf"))

    skipped_too_big = 0
    max_cluster_check_pairs = 2000
    for dist, i, j in candidate_edges:
        ci, cj = cluster_of[i], cluster_of[j]
        if ci == cj:
            continue
        members_i = clusters[ci]
        members_j = clusters[cj]

        if len(members_i) * len(members_j) > max_cluster_check_pairs:
            skipped_too_big += 1
            continue

        if all(get_dist(a, b) <= threshold for a in members_i for b in members_j):
            clusters[ci] |= members_j
            for m in members_j:
                cluster_of[m] = ci
            del clusters[cj]

    if skipped_too_big:
        print(f"    [info] {skipped_too_big} merge saltati per gruppi troppo grandi "
              f"(max_cluster_check_pairs={max_cluster_check_pairs})")

    labels = np.array([cluster_of[i] for i in range(n)])
    return labels, embeddings

def build_groups(values: list[str], counts: Counter, labels: np.ndarray) -> list[dict]:
    groups_map: dict[int, list[str]] = {}
    for val, lab in zip(values, labels):
        groups_map.setdefault(lab, []).append(val)

    groups = []
    for lab, variants in groups_map.items():
        canonical = max(variants, key=lambda v: counts[v])
        groups.append({
            "canonical": canonical,
            "variants": sorted(set(variants)),
            "count": sum(counts[v] for v in variants),
        })
    return groups


# ---------------------------------------------------------------------------
# 4. Find borderline cluster pairs (candidates for Claude review)
# ---------------------------------------------------------------------------

def find_ambiguous_pairs(groups: list[dict], embeddings: np.ndarray, values: list[str]):
    """Compare cluster centroids; flag pairs whose distance falls in the
    ambiguous band (neither clearly same nor clearly different)."""
    from sklearn.metrics.pairwise import cosine_distances

    val_to_idx = {v: i for i, v in enumerate(values)}
    centroids = []
    for g in groups:
        idxs = [val_to_idx[v] for v in g["variants"]]
        centroids.append(embeddings[idxs].mean(axis=0))
    centroids = np.array(centroids)

    dist_matrix = cosine_distances(centroids)
    n = len(groups)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            d = dist_matrix[i, j]
            if AMBIGUOUS_LOW <= d <= AMBIGUOUS_HIGH:
                pairs.append((i, j, d))
    return pairs


# ---------------------------------------------------------------------------
# 5. Claude review of ambiguous pairs only (cheap: few calls, small payload)
# ---------------------------------------------------------------------------

REVIEW_PROMPT = """You are an expert in art history and auction catalogues (it/en/fr/de).

For each pair below, say whether groups A and B refer to the SAME entity
(person, school, object type) despite spelling/language/abbreviation differences.

{pairs_block}

Return ONLY JSONL, one line per pair, no markdown:
{{"pair_id": <int>, "same": true|false}}
"""


MAX_PAIRS_PER_CALL = 80   # coppie per chiamata Claude, evita prompt enormi
MAX_TOTAL_PAIRS = 2000    # se superato, la soglia AMBIGUOUS_HIGH è probabilmente troppo larga


def review_with_claude(client: anthropic.Anthropic, groups: list[dict], pairs: list[tuple]) -> dict:
    if not pairs:
        return {}

    if len(pairs) > MAX_TOTAL_PAIRS:
        print(f"    [warn] {len(pairs)} coppie ambigue, oltre il limite di sicurezza "
              f"({MAX_TOTAL_PAIRS}). Restringo alle {MAX_TOTAL_PAIRS} più vicine — "
              f"considera di abbassare AMBIGUOUS_HIGH per questo tipo.")
        pairs = sorted(pairs, key=lambda p: p[2])[:MAX_TOTAL_PAIRS]

    verdicts: dict[int, bool] = {}
    chunks = [pairs[i:i + MAX_PAIRS_PER_CALL] for i in range(0, len(pairs), MAX_PAIRS_PER_CALL)]

    for chunk_idx, chunk in enumerate(chunks):
        print(f"    Revisione Claude: batch {chunk_idx+1}/{len(chunks)} ({len(chunk)} coppie)...")

        lines = []
        for local_pid, (i, j, d) in enumerate(chunk):
            global_pid = chunk_idx * MAX_PAIRS_PER_CALL + local_pid
            a = groups[i]["canonical"]
            b = groups[j]["canonical"]
            lines.append(f'{local_pid}) A="{a}" (variants: {", ".join(groups[i]["variants"][:5])}) '
                          f'vs B="{b}" (variants: {", ".join(groups[j]["variants"][:5])})')

        prompt = REVIEW_PROMPT.format(pairs_block="\n".join(lines))

        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        text = text.strip("`").lstrip("json").strip()

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = __import__("json").loads(line)
                global_pid = chunk_idx * MAX_PAIRS_PER_CALL + obj["pair_id"]
                verdicts[global_pid] = obj["same"]
            except Exception:
                continue

    return verdicts, pairs


def merge_confirmed_pairs(groups: list[dict], pairs: list[tuple], verdicts: dict) -> list[dict]:
    """Union-find style merge of groups confirmed as 'same' by Claude."""
    parent = list(range(len(groups)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for pid, (i, j, d) in enumerate(pairs):
        if verdicts.get(pid):
            union(i, j)

    merged: dict[int, dict] = {}
    for idx, g in enumerate(groups):
        root = find(idx)
        if root not in merged:
            merged[root] = {"canonical": g["canonical"], "variants": [], "count": 0}
        merged[root]["variants"].extend(g["variants"])
        merged[root]["count"] += g["count"]

    # keep canonical = highest-count variant's original group canonical
    result = []
    for g in merged.values():
        result.append({
            "canonical": g["canonical"],
            "variants": sorted(set(g["variants"])),
            "count": g["count"],
        })
    return result


# ---------------------------------------------------------------------------
# 6. Process one entity type end to end
# ---------------------------------------------------------------------------

def process_type(model, client, df: pd.DataFrame, entity_type: str, out_path: str):
    subset = df[df["type"].str.lower() == entity_type]
    values_raw = [normalize(v) for v in subset["value"].dropna() if str(v).strip()]
    counts = Counter(values_raw)

    if not counts:
        print(f"  Nessun valore per '{entity_type}'")
        return

    unique_values = list(counts.keys())
    print(f"  {entity_type}: {len(unique_values)} valori unici, {sum(counts.values())} occorrenze")

    cfg = PER_TYPE_CONFIG.get(entity_type, {"string_weight": 0.5, "semantic_weight": 0.5,
                                             "distance_threshold": DISTANCE_THRESHOLD})
    labels, embeddings = cluster_values(
        model, unique_values,
        string_weight=cfg["string_weight"],
        semantic_weight=cfg["semantic_weight"],
        threshold=cfg["distance_threshold"],
    )
    groups = build_groups(unique_values, counts, labels)
    print(f"    → {len(groups)} gruppi dopo clustering embeddings")

    pairs = find_ambiguous_pairs(groups, embeddings, unique_values)
    print(f"    → {len(pairs)} coppie borderline da verificare con Claude")

    if pairs:
        verdicts, pairs_used = review_with_claude(client, groups, pairs)
        groups = merge_confirmed_pairs(groups, pairs_used, verdicts)
        print(f"    → {len(groups)} gruppi dopo merge Claude")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["canonical", "variants", "count"])
        writer.writeheader()
        for g in sorted(groups, key=lambda x: -x["count"]):
            writer.writerow({
                "canonical": g["canonical"],
                "variants": " | ".join(g["variants"]),
                "count": g["count"],
            })
    print(f"    ✓ scritto {out_path}")


# ---------------------------------------------------------------------------
# 7. Main
# ---------------------------------------------------------------------------

def main():
    print("Carico dati dal Google Sheet...")
    df = load_sheet(SPREADSHEET_ID, GID)
    df.columns = [c.strip().lower() for c in df.columns]
    assert "type" in df.columns and "value" in df.columns, f"Colonne trovate: {list(df.columns)}"

    print("Carico modello di embedding multilingue...")
    model = SentenceTransformer(MODEL_NAME)

    client = anthropic.Anthropic()  # richiede ANTHROPIC_API_KEY in env / Colab secrets

    for entity_type in ENTITY_TYPES:
        print(f"\nProcesso '{entity_type}'...")
        process_type(model, client, df, entity_type, f"{entity_type}s.csv")

    print("\nDone.")


if __name__ == "__main__":
    main()
