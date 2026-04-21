# HDB Resale Scan Project

This repository contains a complete submission-ready solution for the HDB resale semester project based on the matriculation number `U2221027H`. It includes the source code used to generate the scan results, the generated output files, and validation artifacts.

## Overview

The project reads the resale transaction dataset, derives the required query settings from the matriculation number, scans all required `(x, y)` combinations, and produces the final output CSV in the format expected by the project brief.

For `U2221027H`, the derived query settings are:

- Start year: `2017`
- Start month: `02`
- Towns: `BEDOK`, `BUKIT PANJANG`, `CLEMENTI`, `TAMPINES`

## Repository Contents

- `Semester_Group_Project.pdf`: original project brief
- `source/scan_resale_prices.py`: main program that generates the scan result CSV
- `tools/generate_project_artifacts.py`: helper script for validation artifacts and figures
- `ResalePricesSingapore.csv`: input dataset used by the scanner
- `ScanResult_U2221027H.csv`: generated result file for the required query
- `ScanResult_U2221027H_all_pairs.csv`: optional all-pairs output
- `validation/`: validation summary, workbook, and final checks
- `report_assets/figures/`: supporting figures generated during validation
- `source/README.md`: source-level usage notes
- `IMPLEMENTATION_DETAILS.md`: high-level implementation notes

## Requirements

- Python 3
- No third-party packages are required to generate the main scan result
- To regenerate the validation artifacts and supporting figures, install `matplotlib` and `openpyxl`

## Quick Start

Generate the main scan result:

```bash
python3 source/scan_resale_prices.py U2221027H
```

This writes `ScanResult_U2221027H.csv` to the repository root.

Generate the all-pairs version:

```bash
python3 source/scan_resale_prices.py U2221027H \
  --include-no-result \
  --output ScanResult_U2221027H_all_pairs.csv
```

Regenerate validation artifacts and supporting figures:

```bash
python3 tools/generate_project_artifacts.py U2221027H
```

## Output

The main output file is `ScanResult_U2221027H.csv`, which contains one row for each valid `(x, y)` query pair and includes the following fields:

- `(x, y)`
- `Year`
- `Month`
- `Town`
- `Block`
- `Floor_Area`
- `Flat_Model`
- `Lease_Commence_Date`
- `Price_Per_Square_Meter`

In this repository, the generated result contains `568` valid rows.

## Validation

The repository includes supporting validation materials in the `validation/` folder:

- `U2221027H_validation_summary.csv`: summary of independent spot checks
- `U2221027H_validation_workbook.xlsx`: workbook with candidate rows and spreadsheet formulas
- `final_checks.txt`: structural checks for the generated CSV

These files provide evidence that the generated output is correctly formatted and consistent with an independent validation pass.

## Verification Summary

The current codebase has been checked against the requirements in `Semester_Group_Project.pdf`.

- The generated `ScanResult_U2221027H.csv` matches an independent full brute-force validator across all `568` `(x, y)` pairs
- The output header order, row ordering, and field formatting match the project brief
- The scanner accepts both the repository dataset format and the input schema described in the project brief
- The validation helper script runs successfully and generates the expected validation files and supporting figures

## Additional Documentation

- [source/README.md](source/README.md) for source usage details
- [IMPLEMENTATION_DETAILS.md](IMPLEMENTATION_DETAILS.md) for a high-level explanation of how the scanner and outputs are produced
