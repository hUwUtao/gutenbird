# Cell stack layout specification

`cardmaker.py` can render pages in two distinct layouts:

- **Naive strip** – the default behaviour. Cards are consumed row-by-row using
  the slice size defined by the template (see `(slice=<value>)`).
- **Cell stack** – enabled by pairing `--cell-stack` with `--parity N` for `N > 1`.
  The virtual print stack is split into `N` equal-height segments so cards align
  after you cut and restack the sheets.

Use `--parity N` to describe the split you plan to make; the value is honoured in
both layouts’ parity space metadata. Add `--cell-stack` when you want the layout
itself to follow the cell stack slicing.

## Terminology

- **Slots per page (S)** – total number of eligible card groups discovered in
  the SVG template.
- **Slice size** – number of cards per row. When the template lacks a
  `(slice=…)` marker we fall back to `S`, meaning a single-row template.
- **Rows per page (R)** – `S / slice_size`. In well-formed templates this equals
  the number of grid rows.
- **Cell stack (N)** – how many horizontal stacks you plan to create after
  printing.
- **Cell** – a position inside one stack. Cutting a template into `N` stacks
  yields `S / N` cells per page.

## Preconditions

Cell stack layout requires that the template’s eligible slot count divides evenly
across the stack segments: `S % N == 0`. No other structural markers (such as
rows or slice hints) are required.

## Algorithm

Given the ordered sets produced from the album folders:

1. Compute the number of cells per page: `cells = S / N`.
2. Chunk the discovered sets into groups of `cells`. Missing members are padded
   with dummy entries so every group is full.
3. For each group determine `M = max(len(set))` and calculate
   `limit = ceil(M / N)`. This is the number of pages the group will emit.
4. For every page index `p` in `[0, limit)` and every slot position `i` in
   `[0, S)`:
   - `set_idx = i % cells`
   - `stack_idx = i // cells`
   - `card_idx = p + stack_idx * limit`
   - Emit `sets[set_idx][card_idx]` if it exists; otherwise place the one-pixel
     placeholder.
5. Append the `S` generated items to the page in slot order `i = 0…S-1` and
   continue until all groups are processed.

This process guarantees that when the printed stack is cut into `N` segments and
restacked, cards from the same set appear in a single “cell” position across
successive pages. Sorting by hand becomes a matter of flipping through each
stack without cross-referencing strip positions.

## Example

A template with 40 slots arranged as 5 columns × 8 rows typically advertises a
slice size of 5. With `--parity 2 --cell-stack`:

- `cells = 40 / 2 = 20`
- Each group of 20 sets produces `limit = ceil(max_cards / 2)` pages.
- Slot indices `0…19` map to stack 0, while `20…39` map to stack 1.
- On page `p`, stack 0 consumes card indices `p + 0·limit`; stack 1 consumes
  `p + 1·limit`, so the second stack starts exactly where the first stack stops.

After printing, cut the pages into two four-row stacks, place stack 0 on top of
stack 1, and each cell now forms a perfectly ordered pile of cards.

## CLI usage

```bash
# Split template rows into three cell stacks
uv run python cardmaker.py albums template.svg --parity 3 --cell-stack --output-dir dist

# Emit two copies of every card while maintaining stack alignment
uv run python cardmaker.py albums template.svg --parity 2 --cell-stack --copies 2

When `--copies` is paired with `--cell-stack`, duplicates stay collated per set.
Each stack cycles through the original set order (`1,2,3`) before moving on to
the next copy, yielding output in the pattern `1,2,3,1,2,3,…` within each cell
instead of grouping copies as `1,1,1,2,2,2,3,3,3`.

# Record parity space metadata without enabling cell stack layout
uv run python cardmaker.py albums template.svg --parity 4 --emit-metadata
```

Metadata emitted via `--metadata-json` or `--emit-metadata` includes
`cell_stack_groups`, `cells_per_page`, and the full `parity_space` description of
each page, making it easy to verify the plan against the physical cutting
layout.

## Test mode helper

Pass `--testmode <sets>:<min>,<max>` to skip album discovery and generate
synthetic card data. Each set receives a random size between `min` and `max`, an
all-white placeholder image, and labels in the form `s<set>c<index>`. This is
useful for validating new template layouts or cell stack values without
preparing real artwork.
