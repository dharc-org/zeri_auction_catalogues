import os
import pandas as pd
import urllib.parse
import re
import requests
import json
from docling.document_converter import DocumentConverter
from PIL import Image

def convert_to_greyscale(image_path):
    """
    Converts an image to greyscale and saves it as a JPG file.

    Args:
        image_path (str): The path to the input image file.

    Returns:
        str: The path to the saved greyscale JPG image file, or None if an error occurred.
    """
    try:
        img = Image.open(image_path)
        greyscale_img = img.convert('L')

        # Create the output directory if it doesn't exist
        output_dir = os.path.join(os.path.dirname(image_path), 'greyscale')
        os.makedirs(output_dir, exist_ok=True)

        # Save the greyscale image as JPG
        base_name = os.path.basename(image_path)
        output_path = os.path.join(output_dir, os.path.splitext(base_name)[0] + '_greyscale.jpg')
        greyscale_img.save(output_path, 'JPEG')

        return output_path
    except FileNotFoundError:
        print(f"Error: Image file not found at {image_path}")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def concatenate_markdown_files(input_folder, output_file):
    """
    Accesses all markdown files in a folder, concatenates their text,
    and saves the result in a new markdown file.

    Args:
        input_folder (str): The path to the folder containing the markdown files.
        output_file (str): The path where the concatenated markdown file will be saved.
    """
    concatenated_text = ""
    # Get list of markdown files and sort them alphabetically
    markdown_files = sorted([f for f in os.listdir(input_folder) if f.endswith(".md")])

    for filename in markdown_files:
        filepath = os.path.join(input_folder, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                concatenated_text += f.read() + "\n" # Add a newline between files
        except Exception as e:
            print(f"Error reading file {filepath}: {e}")

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(concatenated_text)
        print(f"Concatenated markdown saved to {output_file}")
    except Exception as e:
        print(f"Error writing to output file {output_file}: {e}")


# Spreadsheet IDs
spreadsheet_id = '1e7LXTiTli6ChG0NXl1laAfgh2Rl9qwLaContEkeD2tg'
encoded_sheet_name_pages_1 = urllib.parse.quote('pagine_lotto_1')

# CSV
url_pages = f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_sheet_name_pages_1}'

# DF
df_pages = pd.read_csv(url_pages)

# Group images by folder in a dictionary
folder_images_dict = {}
for index, row in df_pages.iterrows():
    filename = row['filename']
    if pd.notna(filename):
        # Extract folder_id using regex
        match = re.search(r'_([A-Za-z0-9]+?)_', filename)
        if match:
            folder_id = match.group(1)
            if folder_id not in folder_images_dict:
                folder_images_dict[folder_id] = []
            folder_images_dict[folder_id].append(filename)

print("image page numbers processed\n")
# select a subset for a benchmark
catalogues_benchmark = [
'BO0624_83627', #fr LOTTO1
'BO0624_83693', # fr LOTTO1
'BO0624_81745', # de LOTTO1
'BO0624_87738', # de LOTTO1
'BO0624_4466', # it LOTTO1
'BO0624_81749' # it LOTTO1
]

base_path = 'imgs_benchmark'

matching_files = {}

if os.path.exists(base_path):
    for folder_name in os.listdir(base_path):
        # Check if the folder name is in the catalogues_benchmark list
        if folder_name in catalogues_benchmark:
            # Construct the full path to the subfolder containing images
            folder_path = os.path.join(base_path, folder_name)
            if os.path.isdir(folder_path):
                matching_files[folder_name] = []
                for filename in os.listdir(folder_path):
                    # Check if the filename is in any list within folder_images_dict
                    if any(filename in file_list for file_list in folder_images_dict.values()):
                        matching_files[folder_name].append(filename)

print("image page numbers pruned\n")
# create an error log file
error_path = 'error.txt'
mode = 'a' if os.path.exists(error_path) else 'w'

for folder_path, files_list in matching_files.items():
    for img_path in files_list:
        # convert to greyscale
        source = os.path.join(base_path, folder_path, img_path)  # document per local path or URL
        source_grey = os.path.join(base_path, folder_path, 'greyscale', img_path+'_greyscale.jpg')
        greyscale_image_path = source_grey if os.path.exists(source_grey) else convert_to_greyscale(source)
        print("greyscale done:"+greyscale_image_path)
        base_name = os.path.basename(img_path)[:-4]
        md_path = os.path.join(base_path, folder_path, 'md/' + base_name + '.md')
        # OCR
        if not os.path.exists(md_path):
            converter = DocumentConverter()
            result = converter.convert(greyscale_image_path)
            if not os.path.exists(os.path.join(base_path, folder_path, 'md')):
                os.makedirs(os.path.join(base_path, folder_path, 'md'))
            with open(md_path, 'w') as file:
                res = result.document.export_to_markdown()
                try:
                    file.write(res)
                    print("OCR done:"+img_path)
                    print(res)
                except Exception as e:
                    message = folder_path + img_path + ": " + str(e)
                    with open(error_path, mode) as f:
                        f.write(message + '\n')
                    print("Error:"+img_path)
                    print(message)

    # concat markdown files into one
    output_file_path = os.path.join(base_path, folder_path, 'md/all.md')
    input_folder_path = os.path.join(base_path, folder_path, 'md')
    concatenate_markdown_files(input_folder_path, output_file_path)
    print("concat md done:"+output_file_path)
    # chunking
