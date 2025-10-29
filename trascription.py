import os
import glob
import logging
import torch
import json
import re
from PIL import Image
from vllm import LLM, SamplingParams
from fuzzywuzzy import process
import argparse

LLM_MAX_TOKENS = 20480
# TODO iterate over all folders
IMAGE_FOLDER = '/media/nas4/BO0624_84261/Export/Jpg'
# TODO extract only images with item description
image_paths = ['BO0624_84261_000007_l.jpg','BO0624_84261_000009_l.jpg',
'BO0624_84261_000011_l.jpg','BO0624_84261_000013_l.jpg',
'BO0624_84261_000014_l.jpg','BO0624_84261_000016_l.jpg',
'BO0624_84261_000018_l.jpg','BO0624_84261_000019_l.jpg',
'BO0624_84261_000020_l.jpg','BO0624_84261_000021_l.jpg','BO0624_84261_000022_l.jpg',
'BO0624_84261_000024_l.jpg','BO0624_84261_000026_l.jpg',
'BO0624_84261_000029_l.jpg','BO0624_84261_000031_l.jpg',
'BO0624_84261_000033_l.jpg','BO0624_84261_000034_l.jpg',
'BO0624_84261_000005_r.jpg','BO0624_84261_000006_r.jpg',
'BO0624_84261_000008_r.jpg','BO0624_84261_000010_r.jpg',
'BO0624_84261_000012_r.jpg','BO0624_84261_000013_r.jpg',
'BO0624_84261_000015_r.jpg','BO0624_84261_000017_r.jpg',
'BO0624_84261_000018_r.jpg','BO0624_84261_000019_r.jpg',
'BO0624_84261_000020_r.jpg','BO0624_84261_000021_r.jpg',
'BO0624_84261_000023_r.jpg','BO0624_84261_000025_r.jpg',
'BO0624_84261_000028_r.jpg','BO0624_84261_000030_r.jpg',
'BO0624_84261_000032_r.jpg','BO0624_84261_000033_r.jpg','BO0624_84261_000034_r.jpg']

# *----------------------------------------------------*
# *---------- TEST MARKDOWN TRANSCRIPTION -------------*
# *----------------------------------------------------*

def run_md_transcription():
    torch.cuda.empty_cache()
    llm = LLM(
        model="neuralmagic/Pixtral-Large-Instruct-2411-hf-quantized.w4a16",
        trust_remote_code=True,
        tensor_parallel_size=2,
        max_model_len=40960,
        dtype=torch.float16,
        gpu_memory_utilization=0.95,
    )

    sampling_params = SamplingParams(max_tokens=LLM_MAX_TOKENS)

    for i, img_path in enumerate(image_paths):
        torch.cuda.empty_cache()
        current_page_num = img_path[-6:-4]
        filename = os.path.join(IMAGE_FOLDER, img_path)
        pil_image = None
        pil_image = Image.open(filename).convert("RGB")
        # TODO single or double page?
        prompt_text = (
            f"Here is an image with its corresponding filename:\n"
            f"- {filename}\n\n"
            f"[IMG]\n\n"
            f"The image includes one page of an auction catalogue describing lots."
            f"Return the transcription of the page in Markdown paying attention to the division of text in lots. Follow these instructions:\n"
            f"1. Do not add comments in the output, return only the transcription\n."
            f"2. Ignore page numbers and headers in the same line of page numbers, usually at the top of the page, separated by a long line from the main body of the page.\n"
            f"3. Ignore any graphical element used as separator, often at the beginning of the page.\n"
            f"4. Paragraphs or sections describing lots, usually start with a number and a separator (e.g. '.' or '-'), and end with a slightly wider gap separating from the next paragraph. In the transcription, ALWAYS add before AND after the lot section THIS separator: '---------'.\n "
            f"5. Lot descriptions may include subparagraphs, usually in smaller font and aligned to the right. When a subparagraph exists, it belongs to the lot description, and the gap starts after this one, and the separator goes after this one.\n"
            f"6. Titles, usually in uppercase or in a different weight or style (e.g. bold or italic) should be properly marked. Do not skip titles and render them in the correct place in the page."
            f"7. If the transcription of some words is not confident, return words enclosed in ``, like a markdown code block."
            f"8. Do not translate the text."
        )

        generate_message = [
            {
                "prompt": prompt_text,
                "multi_modal_data": {"image": [pil_image]},
            }
        ]

        outputs = llm.generate(generate_message, sampling_params=sampling_params)
        if outputs and outputs[0].outputs and outputs[0].outputs[0].text:
            llm_raw_response = outputs[0].outputs[0].text
            base_name = os.path.basename(filename)[:-4]  # -> 'BO0624_84261_000005_l.jpg'
            md_path = os.path.join(IMAGE_FOLDER, 'md/' + base_name + '.md')
            os.makedirs(os.path.dirname(md_path), exist_ok=True)
            print(llm_raw_response)
            with open(md_path, 'w') as file:
                file.write(outputs[0].outputs[0].text )
        else:
            print(f"Error parsing image {filename}:\n\n {outputs}")

    if llm is not None:
        print("Attempting to delete LLM object and clear GPU cache...")
        del llm
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logging.info("GPU cache cleared.")
        import gc
        gc.collect()
        print("LLM object deleted and Python garbage collection run.")
        if torch.cuda.is_available():
            print(f"VRAM usage after cleanup: {torch.cuda.memory_allocated() / (1024**3):.2f} GB / {torch.cuda.max_memory_allocated() / (1024**3):.2f} GB max")
    print("Script finished cleanup.")


if __name__ == "__main__":
    run_md_transcription()
