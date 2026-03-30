# HDB Resale Scan Project

This repository contains a complete working solution for the semester project based on
the provided HDB resale dataset and the matriculation number `U2221027H`.

## Deliverables

- `ScanResult_U2221027H.csv`: final scan result file
- `source/scan_resale_prices.py`: main implementation
- `source/README.md`: source-level documentation
- `validation/`: validation summary, workbook, and final checks
- `Report.md`: editable report source
- `Report.pdf`: generated report

## Query settings for `U2221027H`

- start year: `2017`
- start month: `02`
- towns: `BEDOK`, `BUKIT PANJANG`, `CLEMENTI`, `TAMPINES`

## Generate the result file

```bash
python3 source/scan_resale_prices.py U2221027H
```

## Regenerate validation and report artifacts

```bash
python3 tools/generate_project_artifacts.py U2221027H
```

## Notes

- The real dataset in this repository uses lowercase headers and month values such as
  `Jan-15`. The implementation normalizes this to match the assignment requirements.
- The generated result file contains `568` valid `(x, y)` pairs for `U2221027H`.
- Validation artifacts include an independent brute-force cross-check on selected query
  pairs and an Excel workbook with formulas for manual verification.
