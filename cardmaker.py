import os
import sys
import argparse
import base64
import json
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
DEFAULT_SLICE_SIZE = None

# Restrict CSV fields to at most 1 GiB to avoid excessive memory usage
csv.field_size_limit(1024 * 1024 * 1024)

# cairo prec
if os.name == 'nt':
    os.environ['PATH'] += ';C:\\Program Files\\GTK3-Runtime Win64\\bin'
import cairosvg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

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
                    if len(row) != 3:
                        continue
                    file_path, mtime_str, data_url = row
                    if not file_path:
                        continue
                    try:
                        mtime = int(mtime_str)
                    except (TypeError, ValueError):
                        try:
                            mtime = int(round(float(mtime_str) * 1000))
                        except (TypeError, ValueError):
                            mtime = None
                    cache[file_path] = (mtime, data_url)
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
                mtime_value = '' if mtime is None else str(mtime)
                csv_writer.writerow([file_path, mtime_value, data_url])
                f.flush()
                wal_queue.task_done()
            except queue.Empty:
                continue

def get_normalized_mtime(image_path):
    try:
        return int(round(os.path.getmtime(image_path) * 1000))
    except Exception:
        return None

def process_image_with_cache(image_path, cache, cache_path, wal_queue=None):
    mtime = get_normalized_mtime(image_path)
    cache_entry = cache.get(image_path)
    if cache_entry is not None:
        cached_mtime, data_url = cache_entry
        if cached_mtime == mtime:
            return data_url
    data_url = process_image(image_path)
    cache[image_path] = (mtime, data_url)
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

def make_slices(images, slice_size, set_name):
    slices = []
    for i in range(0, len(images), slice_size):
        chunk = images[i:i+slice_size]
        # Pad if not enough
        if len(chunk) < slice_size:
            chunk = chunk + [{"label": "", "image": ONEPIXEL}] * (slice_size - len(chunk))
        slices.append({"set": set_name, "items": chunk})
    return slices

def discover_and_process_images(root_path, cache_path, onepixel, stats=None):
    image_sets = discover_image_sets(root_path)
    if not image_sets:
        print("\nNo image sets found!")
        if stats is not None:
            stats["sets"] = 0
            stats["images"] = 0
            stats["status"] = "error"
            stats["error"] = "No image sets found."
        return None
    processed_sets = process_image_sets(image_sets, cache_path=cache_path)
    if stats is not None:
        stats["sets"] = len(processed_sets)
        stats["images"] = sum(len(images) for images in processed_sets.values())
    return processed_sets

def load_template_info(template_path, stats=None):
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
    if slice_size is None:
        slice_size = slots_per_page
    print(f"\nTemplate info:")
    print(f"- Cards per page: {slots_per_page}")
    print(f"- Slice size: {slice_size}")
    if stats is not None:
        stats["slots_per_page"] = slots_per_page
        stats["slice_size"] = slice_size
    return tokenizer, groups, slots_per_page, slice_size

def collect_all_slices(processed_sets, slice_size):
    all_slices = []
    for set_name, images in processed_sets.items():
        slices = make_slices(images, slice_size, set_name)
        all_slices.extend(slices)
    return all_slices

def group_slices_into_pages(all_slices, slots_per_page, slice_size, stats=None):
    slices_per_page = slots_per_page // slice_size
    if slices_per_page == 0:
        print(f"Template has too few groups for slice size {slice_size}!")
        if stats is not None:
            stats["status"] = "error"
            stats["error"] = f"Template has too few groups for slice size {slice_size}."
        return None, 0
    page_slices = [all_slices[i:i+slices_per_page] for i in range(0, len(all_slices), slices_per_page)]
    print(f"- {sum(len(slice['items']) for slice in all_slices)} images split into {len(all_slices)} slices, {len(page_slices)} pages")
    if stats is not None:
        stats["slices"] = len(all_slices)
        stats["page_count"] = len(page_slices)
    return page_slices, slices_per_page


def collect_parity_slices(processed_sets, slice_size, parity, placeholder):
    """Collect slices using parity layout.

    Each slice pulls one item from a group of sets equal to ``slice_size``. Items
    are selected at positions ``p + k*parity`` for each parity ``p``.
    """
    sets = list(processed_sets.items())
    while len(sets) % slice_size != 0:
        sets.append((None, []))  # pad with empty sets
    grouped = [sets[i:i + slice_size] for i in range(0, len(sets), slice_size)]
    group_max = [max(len(images) for _, images in group) for group in grouped]

    parity_slices = [[] for _ in range(parity)]
    for p_idx in range(parity):
        offset = 0
        while True:
            pos = p_idx + offset * parity
            any_added = False
            for group_idx, group in enumerate(grouped):
                max_len = group_max[group_idx]
                if pos >= max_len:
                    continue
                any_added = True
                slice_items = []
                set_names = []
                for set_name, images in group:
                    if set_name is not None:
                        set_names.append(set_name)
                    if pos < len(images):
                        slice_items.append(images[pos])
                    else:
                        slice_items.append({"label": "", "image": placeholder})
                parity_slices[p_idx].append({
                    "set": "+".join(set_names),
                    "items": slice_items,
                })
            if not any_added:
                break
            offset += 1
    return parity_slices


def group_parity_slices_into_pages(parity_slices, slots_per_page, slice_size, parity, lock_cells=False, stats=None):
    """Arrange parity slices into page groups.

    When ``lock_cells`` is True, slices from all parities are interleaved by
    position so that each set occupies the same cell index across pages. The
    default behaviour groups pages per parity without enforcing cell
    consistency.
    """
    slices_per_page = slots_per_page // slice_size
    if slices_per_page == 0:
        print(f"Template has too few groups for slice size {slice_size}!")
        if stats is not None:
            stats["status"] = "error"
            stats["error"] = f"Template has too few groups for slice size {slice_size}."
        return None

    pages = []
    if lock_cells:
        # Interleave slices by position across parities
        max_len = max(len(lst) for lst in parity_slices)
        interleaved = []
        for idx in range(max_len):
            for p_idx in range(parity):
                lst = parity_slices[p_idx]
                if idx < len(lst):
                    interleaved.append(lst[idx])
        for i in range(0, len(interleaved), slices_per_page):
            pages.append(interleaved[i:i + slices_per_page])
    else:
        parity_lists = [list(lst) for lst in parity_slices]
        while any(parity_lists):
            for p_idx in range(parity):
                lst = parity_lists[p_idx]
                if not lst:
                    continue
                page_slice_group = lst[:slices_per_page]
                parity_lists[p_idx] = lst[slices_per_page:]
                pages.append(page_slice_group)

    total_images = sum(len(slice_["items"]) for group in parity_slices for slice_ in group)
    total_slices = sum(len(group) for group in parity_slices)
    print(f"- {total_images} images split into {total_slices} slices, {len(pages)} pages")
    if stats is not None:
        stats["slices"] = total_slices
        stats["page_count"] = len(pages)
    return pages

def create_svg_pages(page_slices, template_path, slots_per_page, onepixel, svg_dir, stats=None):
    svg_pdf_pairs = []
    page_counter = 1
    pages_meta = [] if stats is not None else None
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
        if pages_meta is not None:
            pages_meta.append({
                "index": page_counter,
                "svg": os.path.abspath(output_svg),
                "pdf": os.path.abspath(output_pdf),
                "sets": set_names,
                "items": len(page_items),
            })
        page_counter += 1
    if stats is not None:
        stats["pages_detail"] = pages_meta
        stats["page_count"] = len(svg_pdf_pairs)
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
    return final_pdf_path

def process_image_set(root_path, template_path, output_dir, parity=1, lock_cells=False, stats=None):
    stats = stats or {}
    stats["version"] = VERSION
    stats["parity"] = parity
    stats["lock_cells"] = bool(lock_cells)
    stats["output_dir"] = os.path.abspath(output_dir)
    stats["album_root"] = os.path.abspath(root_path)
    stats["template"] = os.path.abspath(template_path)
    svg_dir = os.path.join(output_dir, "svg")
    pdf_dir = os.path.join(output_dir, "pdf")
    os.makedirs(svg_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)
    stats["svg_dir"] = os.path.abspath(svg_dir)
    stats["pdf_dir"] = os.path.abspath(pdf_dir)
    cache_path = os.path.join(output_dir, ".imgcache")
    # Step 1: Discover and process images
    processed_sets = discover_and_process_images(root_path, cache_path, ONEPIXEL, stats=stats)
    if not processed_sets:
        return stats
    # Step 2: Load template info
    tokenizer, groups, slots_per_page, slice_size = load_template_info(template_path, stats=stats)
    stats["status"] = "processing"
    # Step 3/4: Layout slices into pages
    if parity > 1:
        parity_slices = collect_parity_slices(processed_sets, slice_size, parity, ONEPIXEL)
        page_slices = group_parity_slices_into_pages(
            parity_slices, slots_per_page, slice_size, parity, lock_cells, stats=stats
        )
        stats["layout"] = "parity"
    else:
        all_slices = collect_all_slices(processed_sets, slice_size)
        page_slices, _ = group_slices_into_pages(all_slices, slots_per_page, slice_size, stats=stats)
        stats["layout"] = "sequential"
    if stats.get("status") == "error":
        return stats
    if not page_slices:
        stats["status"] = "error"
        stats["error"] = "No pages produced."
        return stats
    # Step 5: Create SVG pages
    svg_pdf_pairs = create_svg_pages(page_slices, template_path, slots_per_page, ONEPIXEL, svg_dir, stats=stats)
    # Step 6: Convert SVGs to PDFs
    convert_svgs_to_pdfs(svg_pdf_pairs)
    # Step 7: Merge PDFs
    final_pdf = merge_pdfs(svg_pdf_pairs, output_dir)
    stats["final_pdf"] = final_pdf
    stats["status"] = "ok"
    return stats


def main():
    parser = argparse.ArgumentParser(description="Create SVG card pages from image directories.")
    parser.add_argument("--version", action="version", version=f"cardmaker {VERSION}")
    parser.add_argument("root", type=str, help="Root directory to search for images")
    parser.add_argument("template", type=str, help="SVG template file to use")
    parser.add_argument("--output-dir", type=str, default="dist", help="Output directory for SVG files (default: dist)")
    parser.add_argument("--parity", type=int, default=1, help="Parity grouping value")
    parser.add_argument(
        "--lock-cells",
        action="store_true",
        help="Keep each set in a fixed cell position across parity pages",
    )
    parser.add_argument(
        "--metadata-json",
        type=str,
        default=None,
        help="Write generation metadata to the given JSON file.",
    )
    parser.add_argument(
        "--emit-metadata",
        action="store_true",
        help="Emit generation metadata as JSON to stdout.",
    )
    args = parser.parse_args()

    stats = process_image_set(
        args.root,
        args.template,
        args.output_dir,
        parity=args.parity,
        lock_cells=args.lock_cells,
    )
    if args.metadata_json:
        metadata_dir = os.path.dirname(os.path.abspath(args.metadata_json))
        if metadata_dir:
            os.makedirs(metadata_dir, exist_ok=True)
        with open(args.metadata_json, "w", encoding="utf-8") as fh:
            json.dump(stats, fh, indent=2)
    if args.emit_metadata:
        print(json.dumps(stats, indent=2))

    status = (stats or {}).get("status")
    if status != "ok":
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())

# --- Font Embedding in SVG to PDF (CairoSVG) ---
# To embed Inter or NotoSans, add to your SVG template:
# <style>@font-face { font-family: 'Inter'; src: url('fonts/InterVariable.ttf'); }
#        @font-face { font-family: 'NotoSans'; src: url('fonts/NotoSansVariable.ttf'); }</style>
# and use <text style="font-family: 'Inter';"> or <text style="font-family: 'NotoSans';">
# The font file path must be correct relative to the SVG or absolute.
