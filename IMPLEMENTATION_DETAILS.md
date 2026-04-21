# Implementation Details

This document explains how the repository works at a practical level. It is meant
to help a reviewer or teammate understand the main scan pipeline, the storage
choices, and how each generated output is produced, without having to read the
entire codebase first.

## 1. Repository Structure

The project is centered around one main scanner and one helper script:

- `source/scan_resale_prices.py`
  - the main implementation
  - reads the resale dataset
  - derives the query from the matriculation number
  - scans all required `(x, y)` pairs
  - writes the final CSV output
- `tools/generate_project_artifacts.py`
  - post-processing and validation helper
  - reads the raw dataset and the generated output CSV
  - produces validation tables and supporting figures
- `ResalePricesSingapore.csv`
  - raw input dataset
- `ScanResult_U2221027H.csv`
  - checked-in output for the matriculation number used in this repository
- `ScanResult_U2221027H_all_pairs.csv`
  - alternate output that explicitly lists every `(x, y)` pair
- `validation/`
  - validation summary, workbook, and structural checks
- `report_assets/figures/`
  - rendered PNG figures used to inspect output and validation results

## 2. End-to-End Flow

At a high level, the main scan works like this:

1. Read the matriculation number and derive the query parameters.
2. Load the CSV into a column-oriented in-memory structure.
3. Normalize and precompute fields that will be used repeatedly during scanning.
4. Build fixed-size zones with metadata so chunks can be skipped early.
5. Gather candidate rows for the maximum 8-month search horizon and bucket them by
   month offset.
6. Reuse those buckets while scanning every `x` from `1` to `8`.
7. For each fixed `x`, sweep `y` from `150` down to `80` so one pass answers all
   area thresholds.
8. Pick the best qualifying row using deterministic tie-breaking.
9. Write the final CSV in the required order and format.

The helper script does not change the scan result. It validates and visualizes the
output that the main scanner already generated.

## 3. Query Derivation

The function `build_query_spec()` derives the query from the matriculation number.

It extracts all digits from the matric number, then computes:

- `start_year = 2015 + ((last_digit - 5) % 10)`
- `start_month = second_last_digit`, except `0` is mapped to `10`
- `towns = sorted(unique towns mapped from all digits)`

The digit-to-town mapping is hard-coded in `DIGIT_TO_TOWN`.

For `U2221027H`, the derived query is:

- `start_year = 2017`
- `start_month = 02`
- `towns = BEDOK, BUKIT PANJANG, CLEMENTI, TAMPINES`

The scanner then considers:

- `x` from `1` to `8`
- `y` from `80` to `150`
- only rows in the derived towns
- only rows within the month window from the start month to `start + 7 months`

## 4. Input Handling and Normalization

The scanner reads the dataset with `csv.DictReader`.

The function `resolve_headers()` lets the code accept both:

- the repository's actual CSV column names
- the alternate header wording shown in the project brief

Month parsing is also flexible. `parse_month_text()` supports:

- `%b-%y` such as `Jan-15`
- `%Y-%m` such as `2015-01`

That means the scanner can run against the repository dataset and the brief-style
dataset format without changing the core logic.

## 5. Column-Oriented Storage

The dataset is loaded into a `ColumnStore`. Instead of storing each CSV row as one
Python object, the code stores each field in its own aligned column.

Examples:

- `year`
- `month_num`
- `month_key`
- `town`
- `block`
- `floor_area_sqm`
- `flat_model`
- `lease_commence_date`
- `resale_price`
- `price_per_sqm`

This matters because later stages only touch the columns they need. The scan can
compare months, towns, floor area, and price-per-square-meter directly from the
relevant columns without rebuilding row dictionaries or full row objects.

## 6. Compression and Compact Storage

The implementation applies two lightweight compression ideas.

### 6.1 Dictionary encoding for repeated text

String-heavy columns are stored using `DictionaryColumn`.

Each dictionary column contains:

- `dictionary`
  - the list of distinct string values
- `codes`
  - an integer array where each row stores the code of the corresponding string
- `index_by_value`
  - a reverse map used while loading

This is used for columns such as:

- `month_text`
- `town`
- `flat_type`
- `block`
- `street_name`
- `storey_range`
- `flat_model`
- `lease_commence_date`

Repeated strings are stored once in the dictionary, while rows store compact codes.
The scan can work with codes when filtering, then decode back to strings only when
writing the final output.

### 6.2 Primitive arrays for numeric columns

Numeric columns are stored using `array(...)` rather than ordinary Python lists.

Current storage choices are:

- `year`: `array("H")`
- `month_num`: `array("B")`
- `month_key`: `array("I")`
- `floor_area_sqm`: `array("d")`
- `resale_price`: `array("d")`
- `price_per_sqm`: `array("d")`

This keeps numeric data more compact and makes the in-memory layout more
column-store-like than a list of Python row objects.

## 7. Precomputed Fields

The loader computes some values once so the scan does not repeat the same work.

### 7.1 `month_key`

`month_key = year * 12 + month_num`

This turns month comparisons into cheap integer comparisons and makes it easy to:

- test whether a row is inside the search window
- compute a row's month offset from the start month
- bucket rows by offset for reuse across `x`

### 7.2 `price_per_sqm`

`price_per_sqm = resale_price / floor_area`

This value is used repeatedly when ranking candidates and checking whether a pair is
valid. Precomputing it avoids repeated division during the main scan.

## 8. Zone Maps and Chunk Metadata

After loading the dataset, the code builds fixed-size zones using `build_zones()`.
Each zone is summarized by a `Zone` object.

Each zone stores:

- `start_index`
- `end_index`
- `row_count`
- `min_month_key`
- `max_month_key`
- `min_floor_area`
- `max_floor_area`
- `town_mask`

The town mask is a bitmask built from encoded town IDs. It lets the code quickly
test whether a zone contains any of the towns relevant to the current query.

### Why zones help

Before examining individual rows, `compute_window_buckets()` checks each zone and
skips it entirely when:

- `zone.max_floor_area < 80`
- the zone month range does not overlap the 8-month search horizon
- the zone contains none of the requested towns

This does not change correctness. It only prevents the code from scanning row by
row inside chunks that are guaranteed not to contribute any answer.

## 9. Candidate Bucketing and Reuse Across `x`

Once a zone passes the metadata checks, the scanner examines the rows inside that
zone and keeps only rows that:

- belong to one of the derived towns
- fall within the full 8-month search horizon

Those rows are placed into `buckets[month_offset]`, where:

- `month_offset = month_key - start_key`
- offset `0` means the first month in the search
- offset `7` means the eighth month in the search

This is the main reuse strategy across `x`.

When the code builds results:

- `x = 1` uses only bucket `0`
- `x = 2` uses bucket `0` and bucket `1`
- `x = 3` uses the earlier buckets plus bucket `2`
- and so on until `x = 8`

Instead of recomputing the candidate set from scratch for each `x`, the code grows
`active_indices` incrementally by extending it with one more month bucket each time.

## 10. Reuse Across `y`

For a fixed `x`, the scanner calls `compute_results_for_window()`.

The active candidates are first sorted by:

1. descending `floor_area_sqm`
2. ascending tie-break key from `row_ordering_key()`

Then the code sweeps `y` downward from `150` to `80`.

This works because a row that satisfies a larger minimum floor area will also
satisfy all smaller minimum floor areas.

The algorithm keeps:

- `cursor`
  - where it is in the descending floor-area list
- `best_index`
  - the best qualifying row seen so far

For each `min_area`:

- move the cursor forward while rows still satisfy the current area threshold
- update `best_index` if a newly included row is better
- store the current best answer for that `y`

This means one sorted pass can answer all `71` area thresholds for a fixed month
window.

## 11. Best-Row Selection and Tie-Breaking

Candidate comparison is centralized in `row_ordering_key()` and `better_row()`.

Rows are ordered by:

1. raw `price_per_sqm`
2. `month_key`
3. `town`
4. `block`
5. `flat_model`
6. `lease_commence_date`
7. original row index

This gives the scanner deterministic results even when multiple rows have the same
price-per-square-meter.

### Important detail about rounding

The scan compares rows using the raw floating-point `price_per_sqm`, not the rounded
integer displayed in the output.

Rounding happens only at the output stage with `round_half_up()`.

That distinction is important because:

- correctness is based on the real ratio
- the output format still matches the project requirement of an integer

## 12. How Final Output Rows Are Built

`build_output_rows()` is responsible for constructing the CSV rows.

For each `x` from `1` to `8`:

1. extend the active candidate set with one more month bucket
2. compute the best row for every `y`
3. emit output rows in ascending `y` order

For a successful match, each row contains:

- `(x, y)`
- `Year`
- `Month`
- `Town`
- `Block`
- `Floor_Area`
- `Flat_Model`
- `Lease_Commence_Date`
- `Price_Per_Square_Meter`

`format_floor_area()` removes unnecessary trailing zeros so floor area appears clean
in the final CSV.

## 13. How `No result` Works

The main result file normally includes only successful pairs.

If `--include-no-result` is passed, `build_output_rows()` emits a row like:

- `(x, y)`
- `No result`
- remaining columns left blank

This is what produces `ScanResult_U2221027H_all_pairs.csv`.

In the current checked-in repository, every `(x, y)` pair already has a valid match,
so:

- `ScanResult_U2221027H.csv`
- `ScanResult_U2221027H_all_pairs.csv`

end up identical.

## 14. Output Writing

`write_output()` writes the CSV using the required header order in `OUTPUT_HEADERS`.

Rows are already produced in the correct sequence:

- increasing `x`
- for each `x`, increasing `y`

The default output path is:

- `ScanResult_<MatricNum>.csv`

but the caller can override it with `--output`.

## 15. Helper Script and Derived Artifacts

`tools/generate_project_artifacts.py` reads:

- the raw dataset
- the main generated output CSV

It then produces supporting files.

### 15.1 `validation/U2221027H_validation_summary.csv`

This file is a compact correctness check.

The helper script:

- selects a small set of representative `(x, y)` pairs
- recomputes candidates directly from the raw CSV
- finds the independent best answer using a brute-force validation path
- compares that answer with the row already written by the scanner

### 15.2 `validation/U2221027H_validation_workbook.xlsx`

This workbook makes the validation easier to inspect manually.

It contains:

- a summary sheet
- one sheet per selected `(x, y)` pair
- candidate rows for those pairs
- formulas that show minimum raw PPSQM, rounded PPSQM, and whether the result
  matches the scanner output

### 15.3 `validation/final_checks.txt`

This is a structural sanity check over the generated CSV.

It checks:

- header order
- `(x, y)` sort order
- price-per-square-meter limit
- blank-field issues in emitted rows

### 15.4 `report_assets/figures/*.png`

These figures are visual renderings of:

- the scanner's terminal output
- a preview of the output CSV
- the validation summary
- worked examples for selected `(x, y)` pairs

They are generated for inspection and presentation only. They do not affect the
scanner logic or the final CSV contents.

## 16. Why the Optimizations Do Not Change Results

The current implementation includes several optimizations:

- dictionary encoding
- primitive-array storage
- precomputed `month_key`
- precomputed `price_per_sqm`
- zone-map pruning
- reuse across `x`
- reuse across `y`

These change how the scanner stores and reaches the answer, but not what answer is
chosen.

The result stays the same because:

- filtering logic is unchanged
- ranking logic is unchanged
- tie-breaking logic is unchanged
- rounding logic is unchanged
- output formatting logic is unchanged

In other words, the optimizations improve the storage layout and scan path, not the
definition of the query result.

## 17. Practical Summary

If you want the shortest accurate description of the implementation, it is this:

- the scanner derives a town-and-time query from the matric number
- it loads the raw CSV into a compressed column-oriented in-memory structure
- it builds zone metadata to skip irrelevant chunks early
- it buckets rows by month so larger `x` windows reuse earlier work
- it sweeps `y` downward so one pass answers all area thresholds for a fixed `x`
- it applies deterministic tie-breaking on raw price-per-square-meter
- it writes the final CSV in the required order

That is the core implementation story of this repository.
