# Naive mode parity space

Naive mode keeps the original row-by-row layout while annotating every slot with
parity metadata. Let `n` denote the requested parity value and let the template
contribute `R` rows (`slice_size` cards per row) to each page.

When `n > 1`:

1. Ensure `R` divides evenly by `n`, then compute `rows_per_stack = R / n`.
2. For each page and for every row index `r (0 ≤ r < R)`:
   - Assign the row to stack `stack = floor(r / rows_per_stack)`.
   - Determine the row position within that stack as `row_pos = r % rows_per_stack`.
   - For every column `c (0 ≤ c < slice_size)`, emit the card already positioned
     at row `r`, column `c` in the naive layout and record its parity cell as
     `cell = row_pos * slice_size + c`.

This yields `rows_per_stack * slice_size` cells per stack. After printing, cut
the sheet into `n` row bands, stack band `0` on top of band `1`, and continue up
to band `n-1`; cards will remain in the same relative order as the naive layout.

When `n ≤ 1`, parity falls back to a single stack where `cell == slot`.
