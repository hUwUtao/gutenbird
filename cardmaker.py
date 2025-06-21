import os
import argparse
import base64
from PIL import Image
import io
import bird

def process_image(image_path):
    """Convert an image to a square ratio with a white background and return its data URL."""
    with Image.open(image_path) as img:
        # Create a square canvas with a white background
        max_dim = max(img.size)
        square_img = Image.new("RGB", (max_dim, max_dim), (255, 255, 255))
        square_img.paste(img, ((max_dim - img.width) // 2, (max_dim - img.height) // 2))
        
        # Save the image as JPEG bytes
        img_bytes = io.BytesIO()
        square_img.save(img_bytes, format="PNG")
        img_bytes = img_bytes.getvalue()
        
        # Convert to data URL
        b64_img = base64.b64encode(img_bytes).decode('utf-8')
        return f"data:image/png;base64,{b64_img}"

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
            
        print(f"\nDiscovered set '{set_name}':")
        print(f"- Contains {len(image_files)} image files")
        for f in image_files:
            print(f"  └─ {f}")
            
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

def process_image_sets(image_sets):
    """Process all images in all sets."""
    print("\n=== Processing Images ===")
    processed_sets = {}
    
    for set_name, images in image_sets.items():
        print(f"\nProcessing set '{set_name}':")
        processed_sets[set_name] = []
        
        for idx, img_info in enumerate(images, 1):
            print(f"[{idx}/{len(images)}] Processing {img_info['original_name']}...")
            data_url = process_image(img_info['file_path'])
            processed_sets[set_name].append({
                "label": img_info['label'],
                "image": data_url,
                "original_name": img_info['original_name']
            })
    
    return processed_sets

def process_image_set(root_path, template_path, output_dir):
    """Process a directory of images and create SVG cards."""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Step 1: Discover all image sets
    image_sets = discover_image_sets(root_path)
    if not image_sets:
        print("\nNo image sets found!")
        return
        
    # Step 2: Process all images
    processed_sets = process_image_sets(image_sets)    # Step 3: Create SVG pages for each set
    print("\n=== Creating SVG Pages ===")
    page_counter = 1
    
    # Load template once to get number of slots
    tokenizer = bird.SVGTokenizer(template_path)
    tokenizer.parse_and_tokenize()
    groups = tokenizer.get_matched_groups()
    slots_per_page = len(groups)
    print(f"\nTemplate info:")
    print(f"- Cards per page: {slots_per_page}")
    
    for set_name, images in processed_sets.items():
        print(f"\nProcessing pages for set '{set_name}':")
        num_pages = (len(images) + slots_per_page - 1) // slots_per_page
        print(f"- {len(images)} images will be split into {num_pages} pages")
        
        for i in range(0, len(images), slots_per_page):
            # Load fresh template for each page
            tokenizer = bird.SVGTokenizer(template_path)
            tokenizer.parse_and_tokenize()
            groups = tokenizer.get_matched_groups()
            
            batch = images[i:i + slots_per_page]
            current_page = (i // slots_per_page) + 1
            print(f"\nCreating page {current_page}/{num_pages} with {len(batch)} cards:")
            
            # Process each card in the batch
            for idx, image_data in enumerate(batch):
                if idx >= len(groups):
                    break
                    
                print(f"  └─ Adding {image_data['original_name']}")
                # Set the label and image
                tokenizer.modify_group_labels(idx, image_data["label"])
                tokenizer.modify_group_images(idx, image_data["image"])
            
            # Save this page
            output_path = os.path.join(output_dir, f"page_{page_counter:03d}.svg")
            tokenizer.save_svg(output_path)
            print(f"Saved as {os.path.basename(output_path)}")
            page_counter += 1

def main():
    parser = argparse.ArgumentParser(description="Create SVG card pages from image directories.")
    parser.add_argument("root", type=str, help="Root directory to search for images")
    parser.add_argument("template", type=str, help="SVG template file to use")
    parser.add_argument("--output-dir", type=str, default="dist", help="Output directory for SVG files (default: dist)")
    args = parser.parse_args()

    process_image_set(args.root, args.template, args.output_dir)

if __name__ == "__main__":
    main()
