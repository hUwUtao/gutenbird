import os
import argparse
from PIL import Image
import io
import json

def process_image(image_path):
    """Convert an image to a square ratio with a white background and return its JPEG bytes."""
    with Image.open(image_path) as img:
        # Create a square canvas with a white background
        max_dim = max(img.size)
        square_img = Image.new("RGB", (max_dim, max_dim), (255, 255, 255))
        square_img.paste(img, ((max_dim - img.width) // 2, (max_dim - img.height) // 2))
        
        # Save the image as JPEG bytes
        img_bytes = io.BytesIO()
        square_img.save(img_bytes, format="JPEG")
        return img_bytes.getvalue()

def parse_directory_structure(root_path):
    """Parse the directory structure and process images."""
    result = {}
    for dirpath, dirnames, filenames in os.walk(root_path):
        set_name = os.path.basename(dirpath)
        result[set_name] = []
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            label, ext = os.path.splitext(filename)
            ext = ext.lstrip(".").lower()
            if ext in ["jpg", "jpeg", "png", "bmp", "gif"]:
                image_bytes = process_image(file_path)
                result[set_name].append({"label": label, "image": image_bytes})
    return result

def main():
    parser = argparse.ArgumentParser(description="Search folder structure and process images.")
    parser.add_argument("root", type=str, help="Root directory to search")
    parser.add_argument("output", type=str, help="Output JSON file to store results")
    args = parser.parse_args()

    # Parse the directory structure and process images
    data = parse_directory_structure(args.root)

    # Save the results to a JSON file
    with open(args.output, "w") as f:
        json.dump(data, f, indent=4, default=lambda x: x.decode("latin1"))  # Encode bytes as latin1 for JSON

if __name__ == "__main__":
    main()