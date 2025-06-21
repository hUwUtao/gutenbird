import os
import sys
import argparse
import base64
from PIL import Image
import io
import bird
import concurrent.futures
import csv
import gzip
from typing import Dict, List, Tuple

MAX_IMAGE_DIM = 512

csv.field_size_limit(sys.maxsize)

# cairo prec
os.environ['PATH'] += ';C:\\Program Files\\GTK3-Runtime Win64\\bin'
import cairosvg

def process_image(image_path):
    """Convert an image to a square ratio with a white background and return its data URL, with alpha composited on white."""
    with Image.open(image_path) as img:
        # Convert to RGBA to ensure alpha channel is present
        img = img.convert("RGBA")
        # Determine target square size
        target_dim = MAX_IMAGE_DIM if MAX_IMAGE_DIM is not None else max(img.size)
        # Calculate scale to fit image within the square, preserving aspect ratio
        scale = min(target_dim / img.width, target_dim / img.height, 1.0)
        new_size = (round(img.width * scale), round(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)
        # Create a white RGBA square background
        square_bg = Image.new("RGBA", (target_dim, target_dim), (255, 255, 255, 255))
        # Center the resized image on the square background
        offset = ((target_dim - img.width) // 2, (target_dim - img.height) // 2)
        temp_img = Image.new("RGBA", (target_dim, target_dim), (0, 0, 0, 0))
        temp_img.paste(img, offset)
        composed = Image.alpha_composite(square_bg, temp_img)
        # Convert back to RGB for PNG/JPEG encoding
        final_img = composed.convert("RGB")
        img_bytes = io.BytesIO()
        final_img.save(img_bytes, format="JPEG", quality=90, optimize=True)
        img_bytes = img_bytes.getvalue()
        b64_img = base64.b64encode(img_bytes).decode('utf-8')
        return f"data:image/jpg;base64,{b64_img}"

def discover_image_sets(root_path):
    """Discover all image sets and their files in the directory structure."""
    print("\n=== Discovering Image Sets ===")
    image_sets = {}
    total_files = 0
    
    for dirpath, dirnames, filenames in os.walk(root_path):
        set_name = os.path.basename(dirpath)
        if set_name == os.path.basename(root_path):
            continue  # Skip the root directory itself
        
        # Filter image files
        image_files = [f for f in filenames if os.path.splitext(f)[1].lstrip(".").lower() in ["jpg", "jpeg", "png", "bmp", "gif"]]
        if not image_files:
            continue
            
        # print(f"\nDiscovered set '{set_name}':")
        # print(f"- Contains {len(image_files)} image files")
        # for f in image_files:
        #     print(f"  └─ {f}")
            
        image_sets[set_name] = [
            {
                "file_path": os.path.join(dirpath, f),
                "label": os.path.splitext(f)[0],
                "original_name": f
            }
            for f in image_files
        ]
        total_files += len(image_files)
    
    print(f"\nTotal sets discovered: {len(image_sets)}")
    print(f"Total images found: {total_files}")
    return image_sets

def get_image_cache_csv(cache_path):
    cache = {}
    if os.path.exists(cache_path):
        try:
            with gzip.open(cache_path, 'rt', encoding='utf-8', newline='') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 3:
                        file_path, mtime, data_url = row
                        cache_key = f"{file_path}|{mtime}"
                        cache[cache_key] = data_url
        except Exception as e:
            print(f"Failed to read image cache: {e}")
    return cache

def append_image_cache_csv(cache_path, file_path, mtime, data_url):
    try:
        with gzip.open(cache_path, 'at', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([file_path, mtime, data_url])
    except Exception as e:
        print(f"Failed to append to image cache: {e}")

def process_image_with_cache(image_path, cache, cache_path):
    try:
        mtime = os.path.getmtime(image_path)
    except Exception:
        mtime = None
    cache_key = f"{image_path}|{mtime}"
    if cache_key in cache:
        return cache[cache_key]
    data_url = process_image(image_path)
    cache[cache_key] = data_url
    append_image_cache_csv(cache_path, image_path, mtime, data_url)
    return data_url

def process_image_with_index(args):
    img_info, idx, total, set_name, cache, cache_path = args
    data_url = process_image_with_cache(img_info['file_path'], cache, cache_path)
    return ({
        "label": img_info['label'],
        "image": data_url,
        "original_name": img_info['original_name']
    }, idx - 1)  # -1 because idx starts from 1

def process_image_sets(image_sets, cache_path="./dist/.imgcache"):
    print("\n=== Processing Images (Parallel, with WAL CSV cache) ===")
    processed_sets = {}
    cache = get_image_cache_csv(cache_path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as executor:
        for set_name, images in image_sets.items():
            total = len(images)
            futures = []
            for idx, img_info in enumerate(images, 1):
                future = executor.submit(
                    process_image_with_index,
                    (img_info, idx, total, set_name, cache, cache_path)
                )
                futures.append(future)
            results = []
            for future in concurrent.futures.as_completed(futures):
                result, original_idx = future.result()
                results.append((original_idx, result))
            processed_sets[set_name] = [r[1] for r in sorted(results, key=lambda x: x[0])]
    return processed_sets

def process_image_set(root_path, template_path, output_dir):
    svg_dir = os.path.join(output_dir, "svg")
    pdf_dir = os.path.join(output_dir, "pdf")
    os.makedirs(svg_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)
    # Step 1: Discover all image sets
    image_sets = discover_image_sets(root_path)
    if not image_sets:
        print("\nNo image sets found!")
        return
    # Step 2: Process all images
    processed_sets = process_image_sets(image_sets)
    print("\n=== Creating SVG Pages ===")
    page_counter = 1
    # Load template once to get number of slots
    tokenizer = bird.SVGTokenizer(template_path)
    tokenizer.parse_and_tokenize()
    groups = tokenizer.get_matched_groups()
    slots_per_page = len(groups)
    print(f"\nTemplate info:")
    print(f"- Cards per page: {slots_per_page}")
    svg_pdf_pairs = []
    for set_name, images in processed_sets.items():
        print(f"\nProcessing pages for set '{set_name}':")
        num_pages = (len(images) + slots_per_page - 1) // slots_per_page
        print(f"- {len(images)} images will be split into {num_pages} pages")
        for i in range(0, len(images), slots_per_page):
            tokenizer = bird.SVGTokenizer(template_path)
            tokenizer.parse_and_tokenize()
            groups = tokenizer.get_matched_groups()
            batch = images[i:i + slots_per_page]
            current_page = (i // slots_per_page) + 1
            print(f"\nCreating page {current_page}/{num_pages} with {len(batch)} cards:")
            for idx, image_data in enumerate(batch):
                if idx >= len(groups):
                    break
                tokenizer.modify_group_labels(idx, image_data["label"])
                tokenizer.modify_group_images(idx, image_data["image"])
            output_svg = os.path.join(svg_dir, f"page_{page_counter:03d}.svg")
            output_pdf = os.path.join(pdf_dir, f"page_{page_counter:03d}.pdf")
            tokenizer.save_svg(output_svg)
            print(f"Saved SVG as {os.path.basename(output_svg)}")
            svg_pdf_pairs.append((output_svg, output_pdf))
            page_counter += 1
    # Convert SVGs to PDFs in parallel
    print("\n=== Converting SVGs to PDFs in parallel ===")
    for (svg_path, pdf_path) in svg_pdf_pairs:
        # Use CairoSVG to convert SVG to PDF
        cairosvg.svg2pdf(url=svg_path, write_to=pdf_path)
    # def svg_to_pdf_task(pair):
    #     svg_path, pdf_path = pair
    #     try:
    #         print(f"Exported PDF as {os.path.basename(pdf_path)}")
    #     except Exception as e:
    #         print(f"Failed to export PDF {os.path.basename(pdf_path)}: {e}")
    # with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    #     executor.map(svg_to_pdf_task, svg_pdf_pairs)

def main():
    parser = argparse.ArgumentParser(description="Create SVG card pages from image directories.")
    parser.add_argument("root", type=str, help="Root directory to search for images")
    parser.add_argument("template", type=str, help="SVG template file to use")
    parser.add_argument("--output-dir", type=str, default="dist", help="Output directory for SVG files (default: dist)")
    args = parser.parse_args()

    process_image_set(args.root, args.template, args.output_dir)

if __name__ == "__main__":
    main()

# --- Font Embedding in SVG to PDF (CairoSVG) ---
# To embed Inter or NotoSans, add to your SVG template:
# <style>@font-face { font-family: 'Inter'; src: url('fonts/InterVariable.ttf'); }
#        @font-face { font-family: 'NotoSans'; src: url('fonts/NotoSansVariable.ttf'); }</style>
# and use <text style="font-family: 'Inter';"> or <text style="font-family: 'NotoSans';">
# The font file path must be correct relative to the SVG or absolute.
