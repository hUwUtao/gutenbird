import bird

# Data URL for an empty SVG image
EMPTY_SVG_DATAURL = (
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'></svg>"
)

def main():
    # Load and tokenize the SVG
    tokenizer = bird.SVGTokenizer()
    a = tokenizer.process_svg_file("./test.svg")
    
    # Get all matched groups
    def modifier(index: int):
        tokenizer.modify_group_content(a["parser_instance"], index, f"Card {index}", EMPTY_SVG_DATAURL)

    # Process each group: replace image and label
    for i in range(6*9):
        modifier(i)
    
    # Save the modified SVG
    tokenizer.parser.save_svg("modified_test.svg")
if __name__ == "__main__":
    main()
