import os
import sys
import argparse
import base64
import json
import math
import random
from dataclasses import dataclass, field
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


@dataclass
class PagePlan:
    """Represents a fully expanded page ready to be rendered."""

    items: list  # length equals slots_per_page
    sets: list   # metadata for logging/debugging
    space: list = field(default_factory=list)  # parity space metadata per slot


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def parse_testmode_spec(spec):
    """Parse ``<sets>:<min>,<max>`` into integers."""
    try:
        sets_part, cards_part = spec.split(":", 1)
        min_part, max_part = cards_part.split(",", 1)
        set_count = int(sets_part)
        min_cards = int(min_part)
        max_cards = int(max_part)
    except ValueError as exc:  # pragma: no cover - guard against programming slip
        raise ValueError("Expected format <sets>:<min>,<max>") from exc

    if set_count <= 0:
        raise ValueError("Set count must be greater than zero")
    if min_cards < 0 or max_cards < min_cards:
        raise ValueError("Card range must satisfy 0 <= min <= max")
    return set_count, min_cards, max_cards


def generate_test_sets(set_count, min_cards, max_cards, placeholder, rng=None):
    """Create synthetic sets for test mode."""
    rng = rng or random.Random()
    processed_sets = {}
    for idx in range(set_count):
        card_total = rng.randint(min_cards, max_cards)
        items = []
        for card_idx in range(card_total):
            label = f"s{idx + 1}c{card_idx + 1}"
            items.append({"label": label, "image": placeholder})
        processed_sets[f"set{idx + 1}"] = items
    return processed_sets

def make_slices(images, slice_size, set_name, placeholder, set_lookup):
    slices = []
    for i in range(0, len(images), slice_size):
        chunk = list(images[i:i + slice_size])
        if len(chunk) < slice_size:
            padding = [
                build_placeholder_card(placeholder, set_name=set_name, set_lookup=set_lookup)
                for _ in range(slice_size - len(chunk))
            ]
            chunk.extend(padding)
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

def collect_all_slices(processed_sets, slice_size, placeholder, set_lookup):
    all_slices = []
    for set_name, images in processed_sets.items():
        slices = make_slices(images, slice_size, set_name, placeholder, set_lookup)
        all_slices.extend(slices)
    return all_slices


def apply_copies(processed_sets, copies):
    if copies <= 1:
        return processed_sets

    expanded_sets = {}
    for set_name, images in processed_sets.items():
        expanded_items = []
        for image in images:
            for _ in range(copies):
                expanded_items.append(dict(image))
        expanded_sets[set_name] = expanded_items
    return expanded_sets


def annotate_sets_with_meta(processed_sets, copies):
    annotated_sets = {}
    set_lookup = {}
    for set_index, (set_name, images) in enumerate(processed_sets.items()):
        annotated_items = []
        for item_idx, image in enumerate(images):
            new_item = dict(image)
            meta = dict(new_item.get("_meta") or {})
            meta.update({
                "set": set_name,
                "set_index": set_index,
                "card_index": item_idx // copies if copies else item_idx,
                "copy_index": item_idx % copies if copies else 0,
                "global_index": item_idx,
                "copies": copies,
                "placeholder": False,
            })
            new_item["_meta"] = meta
            annotated_items.append(new_item)
        annotated_sets[set_name] = annotated_items
        set_lookup[set_name] = {
            "set_index": set_index,
            "items": len(images),
        }
    return annotated_sets, set_lookup


def build_placeholder_card(placeholder, set_name=None, set_lookup=None):
    set_index = None
    if set_lookup and set_name in set_lookup:
        set_index = set_lookup[set_name]["set_index"]
    return {
        "label": "",
        "image": placeholder,
        "_meta": {
            "set": set_name,
            "set_index": set_index,
            "card_index": None,
            "copy_index": None,
            "global_index": None,
            "copies": None,
            "placeholder": True,
        },
    }


def build_space_entry(item, slot_index, stack_index, cell_index, extra=None):
    meta = dict(item.get("_meta") or {})
    entry = {
        "slot": slot_index,
        "stack": stack_index,
        "cell": cell_index,
        "set": meta.get("set"),
        "set_index": meta.get("set_index"),
        "card_index": meta.get("card_index"),
        "copy_index": meta.get("copy_index"),
        "global_index": meta.get("global_index"),
        "copies": meta.get("copies"),
        "placeholder": meta.get("placeholder", False),
        "label": item.get("label"),
    }
    if extra:
        entry.update(extra)
    return entry


def build_parity_space_summary(
    page_plans,
    layout_mode,
    parity,
    slots_per_page,
    copies,
    set_lookup,
    cells_per_page=None,
    cell_stack_mode=False,
):
    ordered_sets = sorted(
        (
            {"name": name, **meta}
            for name, meta in set_lookup.items()
        ),
        key=lambda entry: entry.get("set_index", 0),
    )
    pages = []
    for page_index, plan in enumerate(page_plans, start=1):
        placements = []
        for entry in getattr(plan, "space", []):
            enriched = dict(entry)
            enriched.setdefault("stack", 0 if parity <= 1 else enriched.get("stack"))
            enriched["page"] = page_index
            placements.append(enriched)
        pages.append({
            "page": page_index,
            "placements": placements,
        })
    summary = {
        "mode": layout_mode,
        "stacks": parity if parity > 1 else 1,
        "copies": copies,
        "slots_per_page": slots_per_page,
        "cells_per_page": cells_per_page if cells_per_page is not None else slots_per_page,
        "page_count": len(page_plans),
        "sets": ordered_sets,
        "set_sequence": [entry["name"] for entry in ordered_sets],
        "pages": pages,
        "cell_stack_mode": bool(cell_stack_mode),
    }
    return summary

def group_slices_into_pages(
    all_slices,
    slots_per_page,
    slice_size,
    placeholder,
    parity,
    set_lookup,
    stats=None,
):
    slices_per_page = slots_per_page // slice_size
    if slices_per_page == 0:
        print(f"Template has too few groups for slice size {slice_size}!")
        if stats is not None:
            stats["status"] = "error"
            stats["error"] = f"Template has too few groups for slice size {slice_size}."
        return None, None

    stack_count = max(1, parity)
    rows_per_page = slices_per_page
    if stack_count > 1:
        if rows_per_page % stack_count != 0:
            print(
                f"Template rows ({rows_per_page}) cannot be split into {stack_count} parity stacks."
            )
            if stats is not None:
                stats["status"] = "error"
                stats["error"] = (
                    f"Rows per page ({rows_per_page}) must be divisible by parity ({stack_count})."
                )
            return None, None
        rows_per_stack = rows_per_page // stack_count
        cells_per_page = rows_per_stack * slice_size
    else:
        rows_per_stack = rows_per_page
        cells_per_page = slots_per_page

    total_slices = len(all_slices)
    if total_slices == 0:
        print("No slices available for naive layout.")
        if stats is not None and stack_count > 1:
            stats["rows_per_stack"] = rows_per_stack
        return [], cells_per_page

    page_count = math.ceil(total_slices / slices_per_page)

    def make_placeholder_slice():
        return {
            "set": None,
            "items": [
                build_placeholder_card(placeholder, set_lookup=set_lookup)
                for _ in range(slice_size)
            ],
        }

    slice_index = 0

    def take_slice():
        nonlocal slice_index
        if slice_index < total_slices:
            slice_ = all_slices[slice_index]
            slice_index += 1
            return slice_
        return make_placeholder_slice()

    page_rows = [
        [make_placeholder_slice() for _ in range(slices_per_page)]
        for _ in range(page_count)
    ]

    for stack_idx in range(stack_count):
        for page_idx in range(page_count):
            for row_pos in range(rows_per_stack):
                row_index = stack_idx * rows_per_stack + row_pos
                if row_index >= slices_per_page:
                    continue
                page_rows[page_idx][row_index] = take_slice()

    if slice_index < total_slices:
        raise RuntimeError("Failed to allocate all slices into naive parity layout")

    page_plans = []
    for page_idx, rows in enumerate(page_rows):
        items = []
        space = []
        sets = [row.get("set") for row in rows]
        for row_idx, slice_ in enumerate(rows):
            slice_items = slice_["items"]
            row_set_name = slice_.get("set")
            for column_idx, item in enumerate(slice_items):
                slot_index = len(items)
                if stack_count > 1:
                    stack_index = row_idx // rows_per_stack
                    row_position = row_idx % rows_per_stack
                else:
                    stack_index = 0
                    row_position = row_idx
                cell_index = row_position * slice_size + column_idx
                items.append(item)
                space.append(
                    build_space_entry(
                        item,
                        slot_index,
                        stack_index=stack_index,
                        cell_index=cell_index,
                        extra={
                            "slice": row_idx,
                            "position_in_slice": column_idx,
                            "row_set": row_set_name,
                        },
                    )
                )
        page_plans.append(PagePlan(items=items, sets=sets, space=space))

    print(
        f"- {sum(len(slice_['items']) for slice_ in all_slices)} items arranged into "
        f"{len(all_slices)} slices, producing {len(page_plans)} pages"
    )
    if stats is not None:
        stats["slices"] = len(all_slices)
        stats["page_count"] = len(page_plans)
        if stack_count > 1:
            stats["rows_per_stack"] = rows_per_stack
    return page_plans, cells_per_page


def build_cell_stack_page_plans(
    processed_sets,
    slots_per_page,
    cell_stack,
    placeholder,
    set_lookup,
    stats=None,
):
    if cell_stack <= 1:
        raise ValueError("Cell stack layout requires cell_stack > 1")

    if slots_per_page % cell_stack != 0:
        print(
            f"Template with {slots_per_page} slots cannot be split into {cell_stack} cell stack "
            "segments."
        )
        if stats is not None:
            stats["status"] = "error"
            stats["error"] = (
                f"Slots per page ({slots_per_page}) must be divisible by cell stack ({cell_stack})."
            )
        return None

    cells_per_page = slots_per_page // cell_stack
    ordered_sets = list(processed_sets.items())
    total_cards = sum(len(images) for _, images in ordered_sets)
    page_plans = []
    cell_stack_groups = 0

    for group_index, group in enumerate(chunked(ordered_sets, cells_per_page)):
        cell_stack_groups += 1
        padded_group = list(group) + [(None, [])] * (cells_per_page - len(group))
        group_sets = [name for name, _ in group]
        max_len = max((len(images) for _, images in group), default=0)
        if max_len == 0:
            continue
        limit = math.ceil(max_len / cell_stack)
        if limit <= 0:
            continue
        for page_idx in range(limit):
            page_items = []
            page_space = []
            for stack_idx in range(cell_stack):
                card_offset = stack_idx * limit
                for cell_index, (set_name, images) in enumerate(padded_group):
                    card_index = page_idx + card_offset
                    if set_name is not None and card_index < len(images):
                        item = images[card_index]
                    else:
                        item = build_placeholder_card(placeholder, set_name=set_name, set_lookup=set_lookup)
                    slot_index = len(page_items)
                    page_items.append(item)
                    page_space.append(
                        build_space_entry(
                            item,
                            slot_index,
                            stack_index=stack_idx,
                            cell_index=cell_index,
                            extra={
                                "group_index": group_index,
                                "group_set": set_name,
                                "page_cycle": page_idx,
                            },
                        )
                    )
            page_plans.append(PagePlan(items=page_items, sets=group_sets, space=page_space))

    print(
        f"- {total_cards} items across {len(ordered_sets)} sets, producing "
        f"{len(page_plans)} cell stack pages"
    )
    if stats is not None:
        stats["cells_per_page"] = cells_per_page
        stats["cell_stack_groups"] = cell_stack_groups
        stats["page_count"] = len(page_plans)
    return page_plans

def create_svg_pages(page_plans, template_path, slots_per_page, onepixel, svg_dir, stats=None):
    svg_pdf_pairs = []
    page_counter = 1
    pages_meta = [] if stats is not None else None
    for page_idx, plan in enumerate(page_plans):
        tokenizer = bird.SVGTokenizer(template_path)
        tokenizer.parse_and_tokenize()
        groups = tokenizer.get_matched_groups()
        page_items = list(plan.items)
        if len(page_items) < slots_per_page:
            page_items += [{"label": "", "image": onepixel}] * (slots_per_page - len(page_items))
        set_names = plan.sets
        print(
            f"\nCreating page {page_idx + 1}/{len(page_plans)} with {len(page_items)} items "
            f"from sets: {set_names}"
        )
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
                "space": [dict(entry) for entry in getattr(plan, "space", [])],
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

def process_image_set(
    root_path,
    template_path,
    output_dir,
    parity=1,
    cell_stack_mode=False,
    copies=1,
    stats=None,
    testmode=None,
):
    stats = stats or {}
    stats["version"] = VERSION
    stats["parity"] = parity
    stats["cell_stack_mode"] = bool(cell_stack_mode)
    stats["copies"] = copies
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
    # Step 1: Discover and process images or synthesize test sets
    if copies < 1:
        stats["status"] = "error"
        stats["error"] = "Copies must be at least 1."
        return stats

    if testmode is not None:
        set_count, min_cards, max_cards = testmode
        stats["testmode"] = {
            "sets": set_count,
            "min_cards": min_cards,
            "max_cards": max_cards,
        }
        processed_sets = generate_test_sets(
            set_count,
            min_cards,
            max_cards,
            ONEPIXEL,
        )
        stats["sets"] = len(processed_sets)
        stats["images"] = sum(len(images) for images in processed_sets.values())
    else:
        processed_sets = discover_and_process_images(root_path, cache_path, ONEPIXEL, stats=stats)
    if not processed_sets:
        return stats

    if copies > 1:
        processed_sets = apply_copies(processed_sets, copies)
        stats["images"] = sum(len(images) for images in processed_sets.values())

    processed_sets, set_lookup = annotate_sets_with_meta(processed_sets, copies)
    stats["set_sequence"] = [
        name for name, _ in sorted(set_lookup.items(), key=lambda entry: entry[1]["set_index"])
    ]
    # Step 2: Load template info
    _, _, slots_per_page, slice_size = load_template_info(template_path, stats=stats)
    stats["status"] = "processing"
    # Step 3/4: Layout slices into pages
    rows_per_page = slots_per_page // slice_size if slice_size else 0
    stats["rows_per_page"] = rows_per_page

    summary_cells = None
    if cell_stack_mode:
        if parity <= 1:
            stats["status"] = "error"
            stats["error"] = "Cell stack mode requires --parity greater than 1."
            return stats
        page_plans = build_cell_stack_page_plans(
            processed_sets,
            slots_per_page,
            parity,
            ONEPIXEL,
            set_lookup,
            stats=stats,
        )
        summary_cells = stats.get("cells_per_page")
        if summary_cells is None and parity > 0:
            summary_cells = slots_per_page // parity
        layout_mode = "cell_stack"
    else:
        all_slices = collect_all_slices(processed_sets, slice_size, ONEPIXEL, set_lookup)
        page_plans, summary_cells = group_slices_into_pages(
            all_slices,
            slots_per_page,
            slice_size,
            ONEPIXEL,
            parity,
            set_lookup,
            stats=stats,
        )
        if page_plans is None:
            return stats
        if summary_cells is None:
            summary_cells = slots_per_page if parity <= 1 else math.ceil(slots_per_page / max(1, parity))
        stats["cells_per_page"] = summary_cells
        layout_mode = "naive_strip"
    stats["layout"] = layout_mode
    if stats.get("status") == "error":
        return stats
    if not page_plans:
        stats["status"] = "error"
        stats["error"] = "No pages produced."
        return stats
    stats["parity_space"] = build_parity_space_summary(
        page_plans,
        layout_mode,
        parity,
        slots_per_page,
        copies,
        set_lookup,
        cells_per_page=summary_cells,
        cell_stack_mode=cell_stack_mode,
    )

    # Step 5: Create SVG pages
    svg_pdf_pairs = create_svg_pages(page_plans, template_path, slots_per_page, ONEPIXEL, svg_dir, stats=stats)
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
    parser.add_argument(
        "--parity",
        type=int,
        default=1,
        help="Parity split value (applies to metadata and cell stack layout)",
    )
    parser.add_argument(
        "--cell-stack",
        action="store_true",
        help="Enable cell stack layout (requires parity > 1)",
    )
    parser.add_argument(
        "--copies",
        type=int,
        default=1,
        help="Number of copies to emit for each card",
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
    parser.add_argument(
        "--testmode",
        type=str,
        default=None,
        help="Generate synthetic card sets: <sets>:<min>,<max>",
    )
    args = parser.parse_args()

    testmode_spec = None
    if args.testmode:
        try:
            testmode_spec = parse_testmode_spec(args.testmode)
        except ValueError as exc:
            print(f"Invalid --testmode value: {exc}")
            return 1

    stats = process_image_set(
        args.root,
        args.template,
        args.output_dir,
        parity=args.parity,
        cell_stack_mode=args.cell_stack,
        copies=args.copies,
        testmode=testmode_spec,
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
