# Semester Group Project Report

Name: [Fill in your name]  
Matriculation Number: U2221027H

## 1. Data Storage

The input file contains 259,237 resale transactions from Jan 2015 to Dec 2025. The implementation stores the dataset in a column-oriented layout by loading each field into a dedicated Python list. The main stored columns are `year`, `month_num`, `month_key`, `town`, `block`, `floor_area_sqm`, `flat_model`, `lease_commence_date`, `resale_price`, and the derived column `price_per_sqm`.

This design follows the assignment requirement to manage the data in a column-store manner instead of using row-oriented tools such as SQL tables or pandas data frames. Two practical details were handled during loading. First, the real CSV in the repository uses lowercase headers and month strings such as `Jan-15`, so the loader normalizes the headers and parses the month text into numeric year and month columns. Second, the output writer formats the fields exactly in the order requested by the brief: `(x, y), Year, Month, Town, Block, Floor_Area, Flat_Model, Lease_Commence_Date, Price_Per_Square_Meter`.

Possible exceptions are handled during input and output. The code rejects invalid matriculation numbers that do not contain enough digits, checks that the CSV has a header row, and can optionally emit `No result` rows for `(x, y)` combinations with no valid candidate. For the matriculation number `U2221027H`, every one of the 568 `(x, y)` combinations produced a valid result row.

## 2. Data Processing

The matriculation number `U2221027H` produces the following query settings:

- target start year: 2017
- target start month: 02
- matched towns: BEDOK, BUKIT PANJANG, CLEMENTI, TAMPINES

The scan enumerates every `(x, y)` pair where `1 <= x <= 8` and `80 <= y <= 150`. A month key defined as `year * 12 + month` is precomputed for each row, making it easy to test whether a transaction falls inside a target `x`-month window. The program first filters rows by town and by the largest possible month window, then buckets the matching row indices by month offset. This lets larger windows reuse the rows already found for smaller windows rather than rescanning the full table from scratch.

For each active window, candidate rows are sorted by descending floor area and then by price-per-square-meter order. The algorithm then walks the area thresholds from 150 down to 80. As soon as a row satisfies the current minimum area, it becomes eligible for that threshold and for every smaller threshold. This allows one pass over the sorted candidate list to determine the best row for all 71 possible `y` values in the current window.

The final minimum is based on the raw value `resale_price / floor_area`. Rounding is applied only at output time. Ties are broken deterministically using price per square meter, month, town, block, flat model, lease commencement date, and original row order so the result remains stable across repeated runs.

## 3. Experiment Result

The program loaded 259,237 rows and produced 568 result rows. The output distribution was:

- by town: {'BUKIT PANJANG': 470, 'TAMPINES': 98}
- by year-month: {'2017-02': 126, '2017-03': 161, '2017-04': 18, '2017-05': 165, '2017-06': 14, '2017-07': 84}

The first output row is `((1, 80), 2017-02, BUKIT PANJANG, block 149, 103 sqm, Model A, lease 1988, 2913)`. The last output row is `((8, 150), 2017-07, BUKIT PANJANG, block 133, 150 sqm, Maisonette, lease 1988, 3300)`. This confirms that the output is sorted by increasing `x`, and then by increasing `y`.

To validate correctness independently, four representative query pairs were recomputed using a separate brute-force validator that does not reuse the scanner’s window-processing logic. The validator filtered the raw CSV directly, recomputed the minimum price per square meter, and compared the resulting record with the generated output file. The comparison is summarized below.

| Pair | Candidate Count | Independent Rounded | Program Rounded | Match | Town | Block |
| --- | ---: | ---: | ---: | --- | --- | --- |
| (1, 80) | 145 | 2913 | 2913 | YES | BUKIT PANJANG | 149 |
| (1, 147) | 3 | 4295 | 4295 | YES | TAMPINES | 874A |
| (3, 120) | 190 | 3156 | 3156 | YES | BUKIT PANJANG | 204 |
| (8, 150) | 19 | 3300 | 3300 | YES | BUKIT PANJANG | 133 |

All four validation checks matched exactly. In addition, an Excel workbook was generated with one sheet per validated pair. Each sheet contains the filtered candidate records, an Excel `MIN(...)` formula over the raw `Price_Per_Sqm_Raw` column, a `ROUND(...)` formula for the integer output value, and a direct comparison against the program output. These workbook sheets provide the same kind of spreadsheet-based evidence requested in the project brief.
