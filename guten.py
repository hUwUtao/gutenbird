import bird

# Data URL for an empty SVG image
EMPTY_SVG_DATAURL = (
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'></svg>"
)

def main():
    # Load and tokenize the SVG
    tokenizer = bird.SVGTokenizer("./test.svg")
    tokenizer.parse_and_tokenize()
    
    # Get all matched groups
    groups = tokenizer.get_matched_groups()
    
    # Process each group: replace image and label
    for idx, group in enumerate(groups, start=1):
        # Replace label with "Card 01", "Card 02", etc.
        label_text = f"Card {idx:02d}"
        tokenizer.modify_group_labels(idx, label_text)
        # elif token.type == "image":
        #     tokenizer.modify_token(token, EMPTY_SVG_DATAURL)
    
    # Save the modified SVG
    tokenizer.save_svg("./test_output.svg")

if __name__ == "__main__":
    main()