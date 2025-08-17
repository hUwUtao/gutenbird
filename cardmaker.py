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
import threading
import queue
import re

PLACEHOLDER_TEXT_COLOR = "#008080ff"
MAX_IMAGE_DIM = 512
VERSION = "0.1.0"

# Restrict CSV fields to at most 1 GiB to avoid excessive memory usage
csv.field_size_limit(1024 * 1024 * 1024)

# cairo prec
if os.name == 'nt':
    os.environ['PATH'] += ';C:\\Program Files\\GTK3-Runtime Win64\\bin'
import cairosvg

def process_image(image_path):
    """Convert an image to a square ratio with a white background and return its data URL, scaling to fit the largest dimension."""
    with Image.open(image_path) as img:
        img = img.convert("RGBA")
        target_dim = MAX_IMAGE_DIM
        # Scale so the largest dimension matches target_dim
        scale = target_dim / max(img.width, img.height)
        new_size = (round(img.width * scale), round(img.height * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        # Create a white RGBA square background
        square_bg = Image.new("RGBA", (target_dim, target_dim), (255, 255, 255, 255))
        # Center the resized image on the square background
        offset = ((target_dim - img.width) // 2, (target_dim - img.height) // 2)
        temp_img = Image.new("RGBA", (target_dim, target_dim), (0, 0, 0, 0))
        temp_img.paste(img, offset)
        composed = Image.alpha_composite(square_bg, temp_img)
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
                f.flush()
                f.close()
        except Exception as e:
            print(f"Failed to read image cache: {e}")
            exit(1)
    return cache

# def append_image_cache_csv(cache_path, file_path, mtime, data_url):
#     try:
#         with gzip.open(cache_path, 'at', encoding='utf-8', newline='') as f:
#             writer = csv.writer(f)
#             writer.writerow([file_path, mtime, data_url])
#     except Exception as e:
#         print(f"Failed to append to image cache: {e}")

def wal_writer_thread(cache_path, wal_queue, stop_event):
    with gzip.open(cache_path, 'at', encoding='utf-8', newline='') as f:
        csv_writer = csv.writer(f)
        while not stop_event.is_set() or not wal_queue.empty():
            try:
                entry = wal_queue.get(timeout=0.1)
                if entry is None:
                    break
                file_path, mtime, data_url = entry
                csv_writer.writerow([file_path, mtime, data_url])
                wal_queue.task_done()
            except queue.Empty:
                continue

def process_image_with_cache(image_path, cache, cache_path, wal_queue=None):
    try:
        mtime = os.path.getmtime(image_path)
    except Exception:
        mtime = None
    cache_key = f"{image_path}|{mtime}"
    if cache_key in cache:
        return cache[cache_key]
    data_url = process_image(image_path)
    cache[cache_key] = data_url
    if wal_queue is not None:
        wal_queue.put((image_path, mtime, data_url))
    # else:
    #     append_image_cache_csv(cache_path, image_path, mtime, data_url)
    return data_url

def process_image_with_index(args):
    img_info, idx, total, set_name, cache, cache_path, wal_queue = args
    data_url = process_image_with_cache(img_info['file_path'], cache, cache_path, wal_queue)
    return ({
        "label": img_info['label'],
        "image": data_url,
        "original_name": img_info['original_name']
    }, idx - 1)  # -1 because idx starts from 1

def filter_label(label: str) -> str:
    # Trim the label
    label = label.strip()
    # Split by ., ,, _, -
    parts = re.split(r'[.,_\-]', label)
    # Trim each part
    parts = [p.strip() for p in parts]
    # Remove first part if it's empty, a single number, or a single character
    if parts and (parts[0] == "" or (len(parts[0]) == 1) or parts[0].isdigit()):
        parts = parts[1:]
    # Remove last part if it's empty, a single number, or a single character
    if parts and (parts[-1] == "" or (len(parts[-1]) == 1) or parts[-1].isdigit()):
        parts = parts[:-1]
    # Join with space
    return " ".join(parts)

def process_image_sets(image_sets, cache_path="./dist/.imgcache"):
    print("\n=== Processing Images (Parallel, with WAL CSV cache via queue) ===")
    processed_sets = {}
    cache = get_image_cache_csv(cache_path)
    wal_queue = queue.Queue()
    stop_event = threading.Event()
    writer_thread = threading.Thread(target=wal_writer_thread, args=(cache_path, wal_queue, stop_event))
    writer_thread.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as executor:
            for set_name, images in image_sets.items():
                total = len(images)
                futures = []
                for idx, img_info in enumerate(images, 1):
                    future = executor.submit(
                        process_image_with_index,
                        (img_info, idx, total, set_name, cache, cache_path, wal_queue)
                    )
                    futures.append(future)
                results = []
                for future in concurrent.futures.as_completed(futures):
                    result, original_idx = future.result()
                    results.append((original_idx, result))
                processed_sets[set_name] = [r[1] for r in sorted(results, key=lambda x: x[0])]
        wal_queue.join()
    finally:
        stop_event.set()
        wal_queue.put(None)
        writer_thread.join()
    return processed_sets

ONEPIXEL = "data:image/webp;base64,UklGRhYAAABXRUJQVlA4TAoAAAAvAAAAAEX/I/of"
DEFAULT_SLICE_SIZE = 1

def make_slices(images, slice_size, set_name):
    slices = []
    for i in range(0, len(images), slice_size):
        chunk = images[i:i+slice_size]
        # Pad if not enough
        if len(chunk) < slice_size:
            chunk = chunk + [{"label": "", "image": ONEPIXEL}] * (slice_size - len(chunk))
        slices.append({"set": set_name, "items": chunk})
    return slices

def discover_and_process_images(root_path, cache_path, slice_size, onepixel):
    image_sets = discover_image_sets(root_path)
    if not image_sets:
        print("\nNo image sets found!")
        return None
    processed_sets = process_image_sets(image_sets, cache_path=cache_path)
    return processed_sets

def load_template_info(template_path):
    tokenizer = bird.SVGTokenizer(template_path)
    tokenizer.parse_and_tokenize()
    groups = tokenizer.get_matched_groups()
    slots_per_page = len(groups)
    slice_size = DEFAULT_SLICE_SIZE
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r"\(slice=(\d+)\)", content)
        if match:
            slice_size = int(match.group(1))
    except Exception:
        pass
    print(f"\nTemplate info:")
    print(f"- Cards per page: {slots_per_page}")
    print(f"- Slice size: {slice_size}")
    return tokenizer, groups, slots_per_page, slice_size

def collect_all_slices(processed_sets, slice_size):
    all_slices = []
    for set_name, images in processed_sets.items():
        slices = make_slices(images, slice_size, set_name)
        all_slices.extend(slices)
    return all_slices

def group_slices_into_pages(all_slices, slots_per_page, slice_size):
    slices_per_page = slots_per_page // slice_size
    if slices_per_page == 0:
        print(f"Template has too few groups for slice size {slice_size}!")
        return None, 0
    page_slices = [all_slices[i:i+slices_per_page] for i in range(0, len(all_slices), slices_per_page)]
    print(f"- {sum(len(slice['items']) for slice in all_slices)} images split into {len(all_slices)} slices, {len(page_slices)} pages")
    return page_slices, slices_per_page

def create_svg_pages(page_slices, template_path, slots_per_page, onepixel, svg_dir):
    svg_pdf_pairs = []
    page_counter = 1
    for page_idx, slice_group in enumerate(page_slices):
        tokenizer = bird.SVGTokenizer(template_path)
        tokenizer.parse_and_tokenize()
        groups = tokenizer.get_matched_groups()
        page_items = [item for slice_ in slice_group for item in slice_["items"]]
        if len(page_items) < slots_per_page:
            page_items += [{"label": "", "image": onepixel}] * (slots_per_page - len(page_items))
        set_names = [slice_["set"] for slice_ in slice_group]
        print(f"\nCreating page {page_idx+1}/{len(page_slices)} with {len(page_items)} items from sets: {set_names}")
        for idx, item in enumerate(page_items):
            tokenizer.modify_group_labels(idx, filter_label(item["label"]))
            tokenizer.modify_group_images(idx, item["image"])
        output_svg = os.path.join(svg_dir, f"page_{page_counter:03d}.svg")
        output_pdf = os.path.join(os.path.dirname(svg_dir), "pdf", f"page_{page_counter:03d}.pdf")
        tokenizer.save_svg(output_svg)
        print(f"Saved SVG as {os.path.basename(output_svg)}")
        svg_pdf_pairs.append((output_svg, output_pdf))
        page_counter += 1
    return svg_pdf_pairs

def convert_svgs_to_pdfs(svg_pdf_pairs):
    print("\n=== Converting SVGs to PDFs in parallel ===")
    for (svg_path, pdf_path) in svg_pdf_pairs:
        print(f"Converting {os.path.basename(svg_path)} to PDF...")
        cairosvg.svg2pdf(url=svg_path, write_to=pdf_path)

def merge_pdfs(svg_pdf_pairs, output_dir):
    print("\n=== Merging all PDFs into dist/final.pdf ===")
    from pypdf import PdfWriter
    pdf_files = [pdf_path for (_, pdf_path) in svg_pdf_pairs]
    writer = PdfWriter()
    for pdf_file in pdf_files:
        with open(pdf_file, "rb") as f:
            writer.append(f)
    final_pdf_path = os.path.join(output_dir, "final.pdf")
    final_pdf_path = os.path.abspath(final_pdf_path)
    with open(final_pdf_path, "wb") as out_f:
        writer.write(out_f)
    print(f"Merged {len(pdf_files)} PDFs into {final_pdf_path}")

def process_image_set(root_path, template_path, output_dir):
    svg_dir = os.path.join(output_dir, "svg")
    pdf_dir = os.path.join(output_dir, "pdf")
    os.makedirs(svg_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)
    cache_path = os.path.join(output_dir, ".imgcache")
    # Step 1: Discover and process images
    processed_sets = discover_and_process_images(root_path, cache_path, DEFAULT_SLICE_SIZE, ONEPIXEL)
    if not processed_sets:
        return
    # Step 2: Load template info
    tokenizer, groups, slots_per_page, slice_size = load_template_info(template_path)
    # Step 3: Collect all slices
    all_slices = collect_all_slices(processed_sets, slice_size)
    # Step 4: Group slices into pages
    page_slices, slices_per_page = group_slices_into_pages(all_slices, slots_per_page, slice_size)
    if not page_slices:
        return
    # Step 5: Create SVG pages
    svg_pdf_pairs = create_svg_pages(page_slices, template_path, slots_per_page, ONEPIXEL, svg_dir)
    # Step 6: Convert SVGs to PDFs
    convert_svgs_to_pdfs(svg_pdf_pairs)
    # Step 7: Merge PDFs
    merge_pdfs(svg_pdf_pairs, output_dir)
def main():
    parser = argparse.ArgumentParser(description="Create SVG card pages from image directories.")
    parser.add_argument("--version", action="version", version=f"cardmaker {VERSION}")
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
