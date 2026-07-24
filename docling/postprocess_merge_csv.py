"""
postprocess_merge_csv.py

Rifinisce un CSV già generato da aggregate_entities_embeddings.py
(colonne: canonical, variants, count) unendo le righe il cui valore
'canonical' è molto simile ad un'altra (inclusi i casi di canonical
identico ripetuto su più righe), senza rilanciare tutta la pipeline
né ritoccare i threshold originali.

Usa la stessa combinazione string-similarity (rapidfuzz) + embeddings
semantici (sentence-transformers) già usata nello script principale,
ma applicata solo alla colonna 'canonical', con un unico threshold
pensato per essere conservativo (unisce solo ciò che è chiaramente
la stessa entità).

Usage:
    python3 postprocess_merge_csv.py artists.csv artists_merged.csv \
        --threshold 0.12 --string-weight 0.7 --semantic-weight 0.3
"""

from __future__ import annotations

import os
os.environ["USE_TF"] = "0"

import csv
import argparse
import numpy as np
from rapidfuzz.distance import JaroWinkler
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_distances
from sentence_transformers import SentenceTransformer

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


def load_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def combined_distance(values: list[str], model: SentenceTransformer,
                       string_weight: float, semantic_weight: float) -> np.ndarray:
    embeddings = model.encode(values, normalize_embeddings=True, show_progress_bar=True)
    semantic_dist = cosine_distances(embeddings)

    n = len(values)
    string_dist = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            sim = JaroWinkler.normalized_similarity(values[i].lower(), values[j].lower())
            string_dist[i, j] = string_dist[j, i] = 1 - sim

    return string_weight * string_dist + semantic_weight * semantic_dist


def merge_rows(rows: list[dict], threshold: float, model: SentenceTransformer,
               string_weight: float, semantic_weight: float) -> list[dict]:
    canonicals = [r["canonical"] for r in rows]

    dist_matrix = combined_distance(canonicals, model, string_weight, semantic_weight)

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        affinity="precomputed",  # 'metric' su sklearn >= 1.2
        linkage="average",
    )
    labels = clustering.fit_predict(dist_matrix)

    merged_map: dict[int, dict] = {}
    for row, lab in zip(rows, labels):
        variants = [v.strip() for v in row["variants"].split("|") if v.strip()]
        count = int(row.get("count", 0) or 0)

        if lab not in merged_map:
            merged_map[lab] = {"canonical": row["canonical"], "variants": [], "count": 0}
        merged_map[lab]["variants"].extend(variants)
        merged_map[lab]["count"] += count

    # scegli come canonical definitivo quello della riga con count massimo nel gruppo
    best_canonical: dict[int, tuple[str, int]] = {}
    for row, lab in zip(rows, labels):
        count = int(row.get("count", 0) or 0)
        if lab not in best_canonical or count > best_canonical[lab][1]:
            best_canonical[lab] = (row["canonical"], count)

    result = []
    for lab, group in merged_map.items():
        result.append({
            "canonical": best_canonical[lab][0],
            "variants": sorted(set(group["variants"])),
            "count": group["count"],
        })
    return result


def write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["canonical", "variants", "count"])
        writer.writeheader()
        for r in sorted(rows, key=lambda x: -x["count"]):
            writer.writerow({
                "canonical": r["canonical"],
                "variants": " | ".join(r["variants"]),
                "count": r["count"],
            })


def main():
    parser = argparse.ArgumentParser(description="Merge righe con canonical simili in un CSV già generato.")
    parser.add_argument("input_csv")
    parser.add_argument("output_csv")
    parser.add_argument("--threshold", type=float, default=0.12,
                         help="Soglia di distanza combinata (default: 0.12, conservativa)")
    parser.add_argument("--string-weight", type=float, default=0.7)
    parser.add_argument("--semantic-weight", type=float, default=0.3)
    args = parser.parse_args()

    print(f"Carico {args.input_csv}...")
    rows = load_csv(args.input_csv)
    print(f"  {len(rows)} righe")

    print("Carico modello di embedding...")
    model = SentenceTransformer(MODEL_NAME)

    print(f"Calcolo similarità e merge (threshold={args.threshold})...")
    merged = merge_rows(rows, args.threshold, model, args.string_weight, args.semantic_weight)
    print(f"  {len(rows)} righe -> {len(merged)} righe dopo merge")

    write_csv(merged, args.output_csv)
    print(f"Scritto {args.output_csv}")


if __name__ == "__main__":
    main()
