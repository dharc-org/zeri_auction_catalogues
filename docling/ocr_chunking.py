import os
import pandas as pd
import urllib.parse
from urllib.parse import urlparse
from urllib.parse import unquote
import re
import requests
import json
import conf as c
from docling.document_converter import DocumentConverter
import csv
from pathlib import Path
import time
from collections import defaultdict

#IIIF_SEARCH_URL = "http://137.204.64.39/presentation/iiif/search?q=collection_id=LOTTO1;classification=Item+Description;is_table=0"
IIIF_SEARCH_URL = "http://137.204.64.39/presentation/iiif/search?q=filename=BO0624_81777;collection_id=LOTTO1;classification=Item+Description;is_table=0"

def fetch_pages_from_iiif(
    base_url=IIIF_SEARCH_URL,
    sleep=0.15,
    max_retries=3,
    timeout=30,
    verbose=True
):
    folder_images_dict = defaultdict(list)
    page = 1
    total_images = 0

    session = requests.Session()

    while True:
        url = f"{base_url}&page={page}"

        # ---- retry logic ----
        for attempt in range(max_retries):
            try:
                r = session.get(url, timeout=timeout)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Failed page {page}: {e}")
                time.sleep(1.5 * (attempt + 1))

        canvases = data.get("items", [])
        if not canvases:
            if verbose:
                print(f"✅ Finished at page {page-1} — {total_images} images")
            break

        page_count = 0

        for canvas in canvases:
            for annotation_page in canvas.get("items", []):
                for annotation in annotation_page.get("items", []):
                    body = annotation.get("body", {})
                    img_url = body.get("id")

                    if not img_url or not img_url.endswith("default.jpg"):
                        continue

                    folder_id = extract_folder_id(img_url)
                    folder_images_dict[folder_id].append(img_url)
                    #print(folder_images_dict)
                    total_images += 1
                    page_count += 1

        if verbose:
            print(f"📄 Page {page} → {page_count} images (total {total_images})")

        page += 1
        time.sleep(sleep)

    return dict(folder_images_dict)


def extract_folder_id(img_url):
    """
    Extracts folder_id from IIIF image URLs
    """
    # split after /iiif/3/ before !
    tail = img_url.split("/iiif/3/")[-1]
    folder_id = tail.split("!")[0]
    return folder_id

def main():
    # get pages
    # url_pages_to_be_parsed = f'https://docs.google.com/spreadsheets/d/{c.spreadsheet_id}/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(c.sheet_pages)}'
    # df_pages = pd.read_csv(url_pages_to_be_parsed)
    # # filter pages by type: only Item/lot description
    # #df_filtered = df_pages[df_pages["classification"] == c.filter_pages].reset_index(drop=True) if c.filter_pages else df_pages
    # df_filtered = (
    # df_pages[
    #     (df_pages["classification"] == c.filter_pages) &
    #     (df_pages["is_table"] == 0)
    # ].reset_index(drop=True)
    # if c.filter_pages
    # else df_pages[df_pages["is_table"] == 0].reset_index(drop=True)
    # )
    # # group images by folder name
    # folder_images_dict = group_pages_by_catalogue(df_filtered)
    # parse online images, perform OCR and chunking
    folder_images_dict = fetch_pages_from_iiif()
    run_transcription(folder_images_dict, chunking=c.chunking)

def get_image(chunks_df, input_folder, catalogue_id):
    "Add iiif image url to the csv"
    md_dir = Path(input_folder)   # directory with your .md files
    df = chunks_df

    # Read all markdown files into memory once
    markdown_files = {
        md_file.name: md_file.read_text(encoding="utf-8", errors="ignore")
        for md_file in md_dir.glob("*.md")
        if md_file.name != "all.md"
    }

    # Helper: find first markdown file containing the text
    def find_markdown_file(text):
        text_clean = str(text).strip()
        for fname, content in markdown_files.items():
            if text_clean in content:
                page_uri = c.iiif_page_uri_base + catalogue_id + '!' + urllib.parse.quote(fname[:-3]) + '/full/max/0/default.jpg'
                print(page_uri)
                return page_uri
        return None

    # Add column to dataframe
    df["image_online"] = df["text"].apply(find_markdown_file)

    # Save updated CSV
    #df.to_csv("chunks_with_images.csv", index=False)
    return df


def chunk_md_files(input_folder):
    catalogue_id = input_folder
    input_file = input_folder + "/all.md"
    output_file = input_folder + "/chunks.csv"
    inconsistencies_file = input_folder + "/inconsistencies.csv"

    print(f"\nProcessing catalogue: {catalogue_id}")
    text = Path(input_file).read_text(encoding="utf-8")

    # --- Step 1: Initial chunking ---
    result = analyze_and_chunk_markdown(text)
    chunks = result["chunks"]
    for ch in chunks:
        ch["catalogue_id"] = catalogue_id

    chunks_df = pd.DataFrame(chunks)

    # --- Step 2: Postprocessing ---
    chunks_df = split_based_on_gap(chunks_df)
    chunks_df = merge_sandwiched_errors(chunks_df)

    # --- Step 3: Recalculate inconsistencies ---
    inconsistencies_df = recalc_inconsistencies(chunks_df)

    chunks_df = get_image(chunks_df, input_folder, catalogue_id)
    # --- Step 4: Save outputs ---
    chunks_df.to_csv(output_file, index=False, encoding="utf-8")
    inconsistencies_df.to_csv(inconsistencies_file, index=False, encoding="utf-8")
    print(f"💾 Saved {len(chunks_df)} chunks to {output_file}")


def run_transcription(folder_images_dict, chunking=False):
    parsed_folders = add_folder_to_parsed()
    error_path = 'errors.txt'
    mode = 'a' if os.path.exists(error_path) else 'w'
    for folder_path, files_list in folder_images_dict.items():
        print(f"## NEW Parsing {folder_path}")
        if folder_path not in parsed_folders:
            for img_path in files_list:
                run_docling(folder_path, img_path)
                print(f"##### Parsed {folder_path}/{img_path}")
            # concat markdown files into one
            output_file_path = os.path.join(c.parent_folder, folder_path, 'all.md')
            concatenate_markdown_files(os.path.join(c.parent_folder, folder_path), output_file_path)
            print(f"##### Md files concatenated: {folder_path}/all.md")

            # chunk markdown files
            if c.chunking == True:
                try:
                    chunk_md_files(os.path.join(c.parent_folder, folder_path))
                    print(f"##### Md files chunked: {folder_path}/chunks.csv")
                except Exception as e:
                    message = img_path + ": " + str(e)
                    with open(error_path, mode) as f:
                        f.write(message + '\n')
            # 🔥 CLEANUP individual markdown files
            cleanup_markdown_files(os.path.join(c.parent_folder, folder_path))
            print(f"##### Removed individual .md files in {folder_path}")
            # record parsed folders
            parsed_folders = add_folder_to_parsed(folder_path)
            print(f"## DONE Parsing {folder_path}")


# def group_pages_by_catalogue(df_item_desc):
#     # Group images by folder in a dictionary
#     folder_images_dict = {}
#     for index, row in df_item_desc.iterrows():
#         filename = row['filename_output'] # revised filename
#         folder_id = row['item_id']
#         if pd.notna(filename):
#             if folder_id not in folder_images_dict:
#                 folder_images_dict[folder_id] = []
#             folder_images_dict[folder_id].append(filename)
#     return folder_images_dict


def parse_iiif_url(iiif_url: str):
    # extract between ! and .jpg
    m = re.search(r'!(.+?)\.jpg', iiif_url)
    if not m:
        raise ValueError("Invalid IIIF URL")

    raw_token = m.group(1)
    decoded_token = unquote(raw_token)
    grey_url = iiif_url.replace("default.jpg", "gray.jpg")

    return decoded_token, grey_url


def run_docling(folder_path, img_path):
    # output md
    img_name, grey_url = parse_iiif_url(img_path)
    page_uri = grey_url
    md_path = os.path.join(c.parent_folder, folder_path, img_name + '.md')
    if not os.path.exists(md_path):
        # prepare output files
        error_path = 'errors.txt'
        mode = 'a' if os.path.exists(error_path) else 'w'
        try:
            # build URI for greyscale image, e.g. http://137.204.64.39/image/iiif/3/BO0624_4466!BO0624_4466_000132-p.%201.jpg/full/max/0/gray.jpg
            #page_uri = c.iiif_page_uri_base + folder_path + '!' + urllib.parse.quote(img_path) + '/full/max/0/gray.jpg'
            #page_uri = greyscale_url
            print(f"##### Retrieved greyscale page: {page_uri}")
            # OCR
            converter = DocumentConverter()
            result = converter.convert(page_uri)
            print(f"##### Transcribed page: {page_uri}")

            if not os.path.exists(c.parent_folder):
                os.makedirs(c.parent_folder)
            if not os.path.exists(os.path.join(c.parent_folder, folder_path)):
                os.makedirs(os.path.join(c.parent_folder, folder_path))
            with open(md_path, 'w') as file:
                res = result.document.export_to_markdown()
                try:
                    file.write(res)
                    print(f"##### Transcription written in md file: {page_uri}")
                except Exception as e:
                    message = folder_path + img_name + ": " + str(e)
                    with open(error_path, mode) as f:
                        f.write(message + '\n')
        except Exception as e:
            message = folder_path + img_name + ": " + str(e)
            with open(error_path, mode) as f:
                f.write(message + '\n')


def concatenate_markdown_files(input_folder, output_file, index_file=None):
    """
    Concatenates all markdown files in a folder into a single markdown file and
    creates an index mapping each file to its starting line number.

    Args:
        input_folder (str or Path): Folder containing .md files.
        output_file (str or Path): File where the merged markdown is saved.
        index_file (str or Path, optional): File where the line index is saved.
                                            If None, writes <output_file>.index.txt
    """
    try:
        input_folder = Path(input_folder)
        output_file = Path(output_file)

        if index_file is None:
            index_file = input_folder / "all_index.json"
        else:
            index_file = Path(index_file)

        markdown_files = sorted([p for p in input_folder.iterdir() if p.suffix == ".md"])

        line_index = {}   # filename → starting line number
        current_line = 1  # Lines are 1-based

        with output_file.open("w", encoding="utf-8") as outfile:
            for md_file in markdown_files:
                line_index[md_file.name] = current_line

                with md_file.open("r", encoding="utf-8") as infile:
                    for line in infile:
                        outfile.write(line)
                        current_line += 1

                # Add a separating newline between files
                outfile.write("\n")
                current_line += 1

        # Save index file
        with index_file.open("w", encoding="utf-8") as idx:
            json.dump(line_index, idx, indent=2)
    except:
        pass


def add_folder_to_parsed(folder_path=None):
    mode = 'a' if os.path.exists("parsed_folders.txt") else 'w'
    if folder_path:
        with open("parsed_folders.txt", mode, encoding="utf-8") as f:
            f.write(folder_path + '\n')

    if os.path.exists("parsed_folders.txt"):
        with open("parsed_folders.txt", "r", encoding="utf-8") as f:
            parsed_folders = [line.strip() for line in f.readlines()]
    else:
        parsed_folders = []
    return parsed_folders


def analyze_and_chunk_markdown(text):
    """
    Splits the Markdown into chunks based on the most frequent numbering pattern.
    """
    regex_patterns = {
        "generic": re.compile(
            r'^(?:\|?\s*)?(?:#{1,6}\s*)?(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
        "header": re.compile(
            r'^(?:\|?\s*)?#{1,6}\s*(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
        "bullet": re.compile(
            r'^(?:\|?\s*)?(?:[-*]\s*)?(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
        "pipe_prefix": re.compile(
            r'^\|\s*(?P<num>I{1,3}\d*|[1-9]\d*)[.\-—–]*\s*(?P<title>.+)',
            re.MULTILINE
        ),
    }

    # Detect the most common numbering pattern
    all_matches = [(name, list(p.finditer(text))) for name, p in regex_patterns.items()]
    pattern_name, matches = max(all_matches, key=lambda x: len(x[1]))

    print(f"🧩 Most recurring pattern: {pattern_name} ({len(matches)} occurrences)")

    # Build chunks
    positions = [(m.start(), m.group("num"), m.group("title")) for m in matches]
    positions.sort(key=lambda x: x[0])

    chunks = []
    for i, (pos, num, title) in enumerate(positions):
        start = pos
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chunk_text = text[start:end].strip()
        chunks.append({
            "index": i + 1,
            "num": num.strip(),
            "title": title.strip(),
            "text": chunk_text,
        })

    return {"pattern": pattern_name, "chunks": chunks}


def split_based_on_gap(df):
    """
    Split rows when missing lot numbers are found embedded in text
    and they exactly fill the numeric gap.
    """
    lot_pattern = re.compile(r'(?:^|\n|\| |## |### |# |\s|•)(\d{1,3})(?:\s*[\.\-–—]\s*)(?=[A-ZÀ-ÖØ-öø-ÿ])')
    split_rows = []

    df = df.sort_values(['catalogue_id', 'index']).reset_index(drop=True)

    for i, row in df.iterrows():
        catalogue_id = row['catalogue_id']
        text = str(row['text'])
        index = row['index']

        try:
            current_num = int(re.sub(r'\D', '', str(row['num'])))
        except:
            split_rows.append(row.to_dict())
            continue

        # Determine next number
        next_num = None
        if i + 1 < len(df) and df.loc[i + 1, 'catalogue_id'] == catalogue_id:
            try:
                next_num = int(re.sub(r'\D', '', str(df.loc[i + 1, 'num'])))
            except:
                pass

        if not next_num:
            split_rows.append(row.to_dict())
            continue

        gap = next_num - current_num - 1
        if gap <= 0:
            split_rows.append(row.to_dict())
            continue

        embedded_nums = sorted(set(
            int(m.group(1)) for m in lot_pattern.finditer(text)
            if current_num < int(m.group(1)) < next_num
        ))

        if len(embedded_nums) == gap and embedded_nums == list(range(current_num + 1, next_num)):
            print(f"🔍 Splitting row {index} ({current_num}) → found embedded lots {embedded_nums}")
            matches = list(lot_pattern.finditer(text))
            segments = []
            for j, m in enumerate(matches):
                start = m.start()
                end = matches[j + 1].start() if j + 1 < len(matches) else len(text)
                seg_text = text[start:end].strip()
                num_match = re.match(lot_pattern, seg_text)
                if not num_match:
                    continue
                seg_num = int(num_match.group(1))
                if current_num <= seg_num < next_num:
                    segments.append((seg_num, seg_text))

            for seg_num, seg_text in segments:
                split_rows.append({
                    "catalogue_id": catalogue_id,
                    "index": f"{index}.{seg_num}",
                    "num": seg_num,
                    "title": seg_text.split('\n', 1)[0][:120],
                    "text": seg_text.strip(),
                })
        else:
            split_rows.append(row.to_dict())

    new_df = pd.DataFrame(split_rows)
    new_df['index'] = range(1, len(new_df) + 1)
    return new_df


def merge_sandwiched_errors(df):
    """
    Merge OCR errors where a wrong number is sandwiched between two sequential ones.
    """
    fixed_rows = []

    for catalogue_id, group in df.groupby('catalogue_id', sort=False):
        group = group.sort_values('index').reset_index(drop=True)
        rows = group.to_dict(orient='records')
        merged_rows = []
        i = 0
        while i < len(rows):
            current = rows[i]
            def parse_num(val):
                try:
                    return int(str(val).strip().strip('.-–—'))
                except:
                    return None

            curr_num = parse_num(current['num'])
            prev_num = parse_num(rows[i - 1]['num']) if i > 0 else None
            next_num = parse_num(rows[i + 1]['num']) if i + 1 < len(rows) else None

            if prev_num and next_num and prev_num + 1 == next_num and curr_num != prev_num + 1:
                merged = merged_rows.pop() if merged_rows else rows[i - 1].copy()
                merged['title'] += " " + str(current['title'])
                merged['text'] += " " + str(current['text'].strip())
                merged_rows.append(merged)
                i += 1
                continue

            merged_rows.append(current)
            i += 1

        for idx, row in enumerate(merged_rows):
            row['index'] = idx + 1
        fixed_rows.extend(merged_rows)

    return pd.DataFrame(fixed_rows)


def recalc_inconsistencies(df):
    """
    Recalculate inconsistencies *after* postprocessing.
    """
    inconsistencies = []

    for catalogue_id, group in df.groupby("catalogue_id"):
        group = group.sort_values("index")
        last_num = None

        for _, row in group.iterrows():
            try:
                num_val = int(re.sub(r'\D', '', str(row["num"])))
            except:
                num_val = None

            if last_num and num_val and num_val != last_num + 1:
                inconsistencies.append({
                    "catalogue_id": catalogue_id,
                    "prev_num": last_num,
                    "current_num": num_val,
                    "title": row["title"],
                    "excerpt": row["text"].strip()
                })
            if num_val:
                last_num = num_val

    return pd.DataFrame(inconsistencies)


def cleanup_markdown_files(folder_path, keep_file="all.md"):
    folder = Path(folder_path)
    for md_file in folder.glob("*.md"):
        if md_file.name != keep_file:
            md_file.unlink()

if __name__ == "__main__":
    main()
