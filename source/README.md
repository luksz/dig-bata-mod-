# Source Code Guide

This folder contains the implementation used to generate the scan results for the
semester project in a column-oriented style.

## Main file

- `scan_resale_prices.py`

## What the script does

- reads `ResalePricesSingapore.csv`
- derives the query year, month, and towns from a matriculation number
- stores the dataset as separate in-memory columns
- scans all `(x, y)` pairs for `1 <= x <= 8` and `80 <= y <= 150`
- writes `ScanResult_<MatricNum>.csv`
- accepts both the repository CSV format and the schema described in the project brief

## Basic usage

```bash
python3 source/scan_resale_prices.py U2221027H
```

This creates `ScanResult_U2221027H.csv` in the current directory.

## Optional arguments

```bash
python3 source/scan_resale_prices.py U2221027H \
  --input ResalePricesSingapore.csv \
  --output /tmp/ScanResult_U2221027H.csv \
  --include-no-result
```

`--include-no-result` is useful when you want every `(x, y)` pair listed explicitly,
including combinations with no qualifying record.

## Implementation notes

- The loader accepts both the real dataset header names in the repository and the
  alternate header wording shown in the project brief.
- Numeric fields are stored in compact primitive arrays and repeated text fields are
  dictionary-encoded into integer codes, so the scan remains column-oriented while
  applying compression to both numeric and string-heavy columns.
- The code precomputes `month_key` and `price_per_sqm` to avoid repeated parsing and
  repeated division during the scan.
- Fixed-size zones keep chunk metadata such as row count, month range, floor-area
  range, and participating towns so irrelevant chunks can be skipped before row-level
  checks.
- Rows are bucketed by month offset so longer `x` windows can reuse the rows already
  found for shorter windows.
- Ties are resolved deterministically using price per square meter, then month, town,
  block, flat model, lease commencement date, and finally original row order.

## Generated files

- `ScanResult_U2221027H.csv`
- `ScanResult_U2221027H_all_pairs.csv`
- validation artifacts and supporting figures can be generated with `tools/generate_project_artifacts.py`
