import aggregate_entities_embeddings as agg

df = agg.load_sheet(agg.SPREADSHEET_ID, agg.GID)
df.columns = [c.strip().lower() for c in df.columns]

# 1. È presente nel dataframe grezzo?
mask = df["value"].astype(str).str.contains("Jan Both", case=False, na=False)
print("Nel dataframe grezzo:", mask.sum())
print(df[mask])

subset = df[df["type"].str.lower() == "artist"]
values_raw = [agg.normalize(v) for v in subset["value"].dropna() if str(v).strip()]
print("Jan Both" in values_raw)  # 2. sopravvive a normalize/filtro?

from collections import Counter
counts = Counter(values_raw)
print(counts.get("Jan Both"))  # 3. presente nel counter?

unique_values = list(counts.keys())
print("Jan Both" in unique_values)  # 4. presente nella lista finale prima del clustering?

cfg = agg.PER_TYPE_CONFIG["artist"]
labels, embeddings = agg.cluster_values(
    agg.SentenceTransformer(agg.MODEL_NAME), unique_values,
    string_weight=cfg["string_weight"],
    semantic_weight=cfg["semantic_weight"],
    threshold=cfg["distance_threshold"],
)

idx = unique_values.index("Jan Both")
print("Indice:", idx, "Label:", labels[idx])

# quanti indici condividono la stessa label (cioè finiscono nello stesso gruppo)?
import numpy as np
same_group = np.where(labels == labels[idx])[0]
print("Valori nello stesso gruppo:", [unique_values[i] for i in same_group])

groups = agg.build_groups(unique_values, counts, labels)
found = [g for g in groups if "Jan Both" in g["variants"]]
print(found)
