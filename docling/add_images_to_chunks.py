import os
import pandas as pd
import ocr_chunking as ocr

# Your existing function (you said you already have it)
# def chunk_md_files(df, folder_path):
#     ...
#     return new_df

BASE_DIR = "documents"
FOLDER_LIST_FILE = "parsed_folders.txt"

with open(FOLDER_LIST_FILE, "r") as f:
    folders = [line.strip() for line in f if line.strip()]

for folder_name in folders:
    folder_path = os.path.join(BASE_DIR, folder_name)
    chunks_csv_path = os.path.join(folder_path, "chunks.csv")

    # Ensure folder & csv exist
    if not os.path.isdir(folder_path):
        print(f"❌ Folder not found: {folder_path}")
        continue

    if not os.path.isfile(chunks_csv_path):
        print(f"❌ chunks.csv not found in: {folder_path}")
        continue

    print(f"Processing {folder_path}...")

    # Load CSV
    try:
        df = pd.read_csv(chunks_csv_path)
    except Exception as e:
        print(f"⚠ Error reading CSV in {folder_path}: {e}")
        continue

    # Apply your transformation function
    try:
        new_df = ocr.get_image(df, folder_path, folder_name)
    except Exception as e:
        print(f"⚠ Error processing folder {folder_path}: {e}")
        continue

    # Overwrite the file
    try:
        new_df.to_csv(chunks_csv_path, index=False)
        print(f"✔ Updated chunks.csv in {folder_path}")
    except Exception as e:
        print(f"⚠ Error writing CSV in {folder_path}: {e}")
