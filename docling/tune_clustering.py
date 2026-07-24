"""
tune_clustering.py — Colab: cella di esplorazione per tarare
DISTANCE_THRESHOLD, AMBIGUOUS_LOW, AMBIGUOUS_HIGH prima di lanciare
aggregate_entities_embeddings.py sul dataset completo.

Non chiama Claude, non scrive CSV finali: solo stampa a schermo.
"""

import os
os.environ["USE_TF"] = "0"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"

import numpy as np
from collections import Counter
from sklearn.metrics.pairwise import cosine_distances
from sentence_transformers import SentenceTransformer

import aggregate_entities_embeddings as agg  # il tuo primo script, stesso runtime Colab
from huggingface_hub import login
login(token="")
# ---------------------------------------------------------------------------
# 1. Carica dati e modello una sola volta
# ---------------------------------------------------------------------------

df = agg.load_sheet(agg.SPREADSHEET_ID, agg.GID)
df.columns = [c.strip().lower() for c in df.columns]

model = SentenceTransformer(agg.MODEL_NAME)

# ---------------------------------------------------------------------------
# 2. Prepara i valori per UN entity type alla volta
# ---------------------------------------------------------------------------

ENTITY_TYPE = "artist"  # <-- cambia qui per testare school / object_type

subset = df[df["type"].str.lower() == ENTITY_TYPE]
values_raw = [agg.normalize(v) for v in subset["value"].dropna() if str(v).strip()]
counts = Counter(values_raw)
unique_values = list(counts.keys())
print(f"{ENTITY_TYPE}: {len(unique_values)} valori unici")

# ---------------------------------------------------------------------------
# 3. Prova diversi DISTANCE_THRESHOLD
# ---------------------------------------------------------------------------

def try_threshold(threshold: float, top_n: int = 15):
    agg.DISTANCE_THRESHOLD = threshold
    labels, embeddings = agg.cluster_values(model, unique_values)
    groups = agg.build_groups(unique_values, counts, labels)

    multi = [g for g in groups if len(g["variants"]) > 1]
    print(f"\n{'='*60}\nTHRESHOLD = {threshold}")
    print(f"Gruppi totali: {len(groups)} | Gruppi con >1 variante: {len(multi)}")
    for g in sorted(multi, key=lambda x: -x["count"])[:top_n]:
        print(f"  [{g['count']:>4}] {g['canonical']!r}  <-  {g['variants']}")

    return groups, embeddings


for t in [0.10, 0.15, 0.20, 0.25, 0.30]:
    try_threshold(t)

# ---------------------------------------------------------------------------
# 4. Una volta scelto il threshold buono, ispeziona le distanze tra gruppi
#    per tarare AMBIGUOUS_LOW / AMBIGUOUS_HIGH
# ---------------------------------------------------------------------------

CHOSEN_THRESHOLD = 0.20  # <-- metti qui il valore scelto al passo 3
groups, embeddings = try_threshold(CHOSEN_THRESHOLD, top_n=0)

val_to_idx = {v: i for i, v in enumerate(unique_values)}
centroids = np.array([
    embeddings[[val_to_idx[v] for v in g["variants"]]].mean(axis=0)
    for g in groups
])
dist_matrix = cosine_distances(centroids)

n = len(groups)
pair_dists = [(i, j, dist_matrix[i, j]) for i in range(n) for j in range(i + 1, n)]
pair_dists.sort(key=lambda x: x[2])

print(f"\n{'='*60}\nCoppie di gruppi più vicine (candidate a merge o banda ambigua)")
for i, j, d in pair_dists[:30]:
    print(f"{d:.3f}  {groups[i]['canonical']!r}  vs  {groups[j]['canonical']!r}")

# Scorri l'elenco sopra dal basso (distanza minore) verso l'alto:
# individua dove smette di avere senso unire i due gruppi -> quella distanza
# è AMBIGUOUS_HIGH; individua dove sei sicuro al 100% che siano la stessa
# entità -> quella distanza è AMBIGUOUS_LOW.
