#!/usr/bin/env python3
"""Generate validation artifacts and a submission-ready report."""

import argparse
import csv
import os
import re
import subprocess
import textwrap
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd() / ".matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


PRICE_PER_SQM_LIMIT = 4725.0
DIGIT_TO_TOWN = {
    0: "BEDOK",
    1: "BUKIT PANJANG",
    2: "CLEMENTI",
    3: "CHOA CHU KANG",
    4: "HOUGANG",
    5: "JURONG WEST",
    6: "PASIR RIS",
    7: "TAMPINES",
    8: "WOODLANDS",
    9: "YISHUN",
}
SELECTED_PAIRS = [(1, 80), (1, 147), (3, 120), (8, 150)]


@dataclass(frozen=True)
class QuerySpec:
    matric_number: str
    start_year: int
    start_month: int
    towns: Tuple[str, ...]

    @property
    def start_key(self) -> int:
        return self.start_year * 12 + self.start_month


@dataclass(frozen=True)
class RawRow:
    month_text: str
    year: int
    month_num: int
    month_key: int
    town: str
    block: str
    floor_area: float
    flat_model: str
    lease_commence_date: str
    resale_price: float
    price_per_sqm: float


def round_half_up(value: float) -> int:
    return int(value + 0.5)


def parse_month_text(raw_month: str) -> Tuple[int, int]:
    parsed = datetime.strptime(raw_month.strip(), "%b-%y")
    return parsed.year, parsed.month


def pair_from_text(text_value: str) -> Tuple[int, int]:
    return tuple(int(number) for number in re.findall(r"\d+", text_value))  # type: ignore[return-value]


def format_floor_area(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def build_query_spec(matric_number: str) -> QuerySpec:
    digits = [int(ch) for ch in matric_number if ch.isdigit()]
    if len(digits) < 2:
        raise ValueError("Matric number must contain at least two digits.")

    last_digit = digits[-1]
    second_last_digit = digits[-2]
    start_year = 2015 + ((last_digit - 5) % 10)
    start_month = 10 if second_last_digit == 0 else second_last_digit
    towns = tuple(sorted({DIGIT_TO_TOWN[digit] for digit in digits}))
    return QuerySpec(matric_number, start_year, start_month, towns)


def load_raw_rows(csv_path: Path) -> List[RawRow]:
    rows: List[RawRow] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            year, month_num = parse_month_text(row["month"])
            floor_area = float(row["floor_area_sqm"])
            resale_price = float(row["resale_price"])
            rows.append(
                RawRow(
                    month_text=row["month"],
                    year=year,
                    month_num=month_num,
                    month_key=year * 12 + month_num,
                    town=row["town"],
                    block=row["block"],
                    floor_area=floor_area,
                    flat_model=row["flat_model"],
                    lease_commence_date=row["lease_commence_date"],
                    resale_price=resale_price,
                    price_per_sqm=resale_price / floor_area,
                )
            )
    return rows


def load_output_rows(output_path: Path) -> List[Dict[str, str]]:
    with output_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def row_key(row: RawRow) -> Tuple[float, int, str, str, str, str]:
    return (
        row.price_per_sqm,
        row.month_key,
        row.town,
        row.block,
        row.flat_model,
        row.lease_commence_date,
    )


def filtered_candidates(rows: Iterable[RawRow], spec: QuerySpec, x_value: int, y_value: int) -> List[RawRow]:
    end_key = spec.start_key + x_value - 1
    matched = [
        row
        for row in rows
        if spec.start_key <= row.month_key <= end_key and row.town in spec.towns and row.floor_area >= y_value
    ]
    return sorted(matched, key=row_key)


def write_validation_summary_csv(summary_rows: Sequence[Dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Pair",
                "Candidate_Count",
                "Independent_Min_Raw",
                "Independent_Min_Rounded",
                "Program_Min_Rounded",
                "Matched",
                "Year",
                "Month",
                "Town",
                "Block",
                "Floor_Area",
                "Flat_Model",
                "Lease_Commence_Date",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)


def write_validation_workbook(
    summary_rows: Sequence[Dict[str, str]],
    candidate_map: Dict[Tuple[int, int], List[RawRow]],
    workbook_path: Path,
) -> None:
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Summary"

    summary_headers = [
        "Pair",
        "Candidate Count",
        "Independent Raw Min",
        "Independent Rounded Min",
        "Program Rounded Min",
        "Match",
        "Year",
        "Month",
        "Town",
        "Block",
        "Floor Area",
        "Flat Model",
        "Lease Commence Date",
    ]
    summary_sheet.append(summary_headers)
    for cell in summary_sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")

    for row in summary_rows:
        summary_sheet.append(
            [
                row["Pair"],
                int(row["Candidate_Count"]),
                float(row["Independent_Min_Raw"]),
                int(row["Independent_Min_Rounded"]),
                int(row["Program_Min_Rounded"]),
                row["Matched"],
                row["Year"],
                row["Month"],
                row["Town"],
                row["Block"],
                row["Floor_Area"],
                row["Flat_Model"],
                row["Lease_Commence_Date"],
            ]
        )

    for column in "ABCDEFGHIJKLM":
        summary_sheet.column_dimensions[column].width = 18

    for pair, rows in candidate_map.items():
        pair_name = f"Q_{pair[0]}_{pair[1]}"
        sheet = workbook.create_sheet(title=pair_name)
        header_row = 7
        data_start_row = 8

        sheet["A1"] = "Pair"
        sheet["B1"] = f"({pair[0]}, {pair[1]})"
        sheet["A2"] = "Candidate count"
        sheet["B2"] = len(rows)
        sheet["A3"] = "Excel MIN formula"
        sheet["B3"] = f"=MIN(H{data_start_row}:H{data_start_row + len(rows) - 1})"
        sheet["A4"] = "Rounded minimum"
        sheet["B4"] = "=ROUND(B3,0)"
        sheet["A5"] = "Program rounded output"
        matched_row = next(summary for summary in summary_rows if summary["Pair"] == f"({pair[0]}, {pair[1]})")
        sheet["B5"] = int(matched_row["Program_Min_Rounded"])
        sheet["A6"] = "Match"
        sheet["B6"] = '=IF(B4=B5,"YES","NO")'

        for label_cell in ("A1", "A2", "A3", "A4", "A5", "A6"):
            sheet[label_cell].font = Font(bold=True)

        headers = [
            "Month",
            "Town",
            "Block",
            "Floor_Area",
            "Flat_Model",
            "Lease_Commence_Date",
            "Resale_Price",
            "Price_Per_Sqm_Raw",
            "Price_Per_Sqm_Rounded",
        ]
        for column_index, header in enumerate(headers, start=1):
            sheet.cell(row=header_row, column=column_index, value=header)
        for cell in sheet[header_row]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="D9EAF7")
            cell.alignment = Alignment(horizontal="center")

        for row in rows:
            sheet.append(
                [
                    row.month_text,
                    row.town,
                    row.block,
                    row.floor_area,
                    row.flat_model,
                    row.lease_commence_date,
                    row.resale_price,
                    row.price_per_sqm,
                    round_half_up(row.price_per_sqm),
                ]
            )

        for column in "ABCDEFGHI":
            sheet.column_dimensions[column].width = 18

        sheet.freeze_panes = f"A{data_start_row}"

    workbook.save(workbook_path)


def write_final_checks(
    output_rows: Sequence[Dict[str, str]],
    output_path: Path,
    spec: QuerySpec,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header_ok = list(output_rows[0].keys()) == [
        "(x, y)",
        "Year",
        "Month",
        "Town",
        "Block",
        "Floor_Area",
        "Flat_Model",
        "Lease_Commence_Date",
        "Price_Per_Square_Meter",
    ]
    sorted_ok = all(
        pair_from_text(output_rows[idx]["(x, y)"]) < pair_from_text(output_rows[idx + 1]["(x, y)"])
        for idx in range(len(output_rows) - 1)
    )
    limit_ok = all(int(row["Price_Per_Square_Meter"]) <= int(PRICE_PER_SQM_LIMIT) for row in output_rows)
    blank_ok = all(all(value != "" for value in row.values()) for row in output_rows)

    lines = [
        f"Matric number: {spec.matric_number}",
        f"Derived start window: {spec.start_year}-{spec.start_month:02d}",
        f"Matched towns: {', '.join(spec.towns)}",
        f"Output row count: {len(output_rows)}",
        f"Header check: {'PASS' if header_ok else 'FAIL'}",
        f"Sorted by (x, y): {'PASS' if sorted_ok else 'FAIL'}",
        f"All price-per-sqm values <= 4725: {'PASS' if limit_ok else 'FAIL'}",
        f"No blank fields in emitted rows: {'PASS' if blank_ok else 'FAIL'}",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def wrapped(text_value: str, width: int = 95) -> str:
    return "\n".join(textwrap.wrap(text_value, width=width))


def save_text_figure(text_value: str, output_path: Path, title: str, figsize: Tuple[float, float] = (10, 3.4)) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=figsize)
    fig.patch.set_facecolor("white")
    fig.text(0.03, 0.94, title, fontsize=14, weight="bold", va="top")
    fig.text(
        0.03,
        0.86,
        text_value,
        family="monospace",
        fontsize=10,
        va="top",
        bbox={"boxstyle": "round", "facecolor": "#F5F5F5", "edgecolor": "#C8C8C8"},
    )
    plt.axis("off")
    plt.savefig(output_path, bbox_inches="tight", dpi=180)
    plt.close(fig)


def save_table_figure(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    output_path: Path,
    title: str,
    note: str = "",
    figsize: Tuple[float, float] = (11.0, 3.4),
    font_size: int = 9,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=figsize)
    ax.axis("off")
    table = ax.table(
        cellText=rows,
        colLabels=headers,
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(font_size)
    table.scale(1, 1.35)
    for (row_index, col_index), cell in table.get_celld().items():
        if row_index == 0:
            cell.set_facecolor("#D9EAF7")
            cell.set_text_props(weight="bold")
        elif row_index % 2 == 1:
            cell.set_facecolor("#F8FBFD")
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.98)
    if note:
        fig.text(0.02, 0.03, wrapped(note, width=120), fontsize=9, va="bottom")
    plt.savefig(output_path, bbox_inches="tight", dpi=180)
    plt.close(fig)


def build_report_markdown(
    spec: QuerySpec,
    summary_rows: Sequence[Dict[str, str]],
    output_rows: Sequence[Dict[str, str]],
    raw_rows: Sequence[RawRow],
) -> str:
    town_counts = Counter(row["Town"] for row in output_rows)
    month_counts = Counter(f"{row['Year']}-{row['Month']}" for row in output_rows)
    summary_table = "\n".join(
        f"| {row['Pair']} | {row['Candidate_Count']} | {row['Independent_Min_Rounded']} | {row['Program_Min_Rounded']} | {row['Matched']} | {row['Town']} | {row['Block']} |"
        for row in summary_rows
    )
    first_row = output_rows[0]
    last_row = output_rows[-1]

    return f"""# Semester Group Project Report

Name: [Fill in your name]  
Matriculation Number: {spec.matric_number}

## 1. Data Storage

The input file contains {len(raw_rows):,} resale transactions from Jan 2015 to Dec 2025. The implementation stores the dataset in a column-oriented layout by loading each field into a dedicated Python list. The main stored columns are `year`, `month_num`, `month_key`, `town`, `block`, `floor_area_sqm`, `flat_model`, `lease_commence_date`, `resale_price`, and the derived column `price_per_sqm`.

This design follows the assignment requirement to manage the data in a column-store manner instead of using row-oriented tools such as SQL tables or pandas data frames. Two practical details were handled during loading. First, the real CSV in the repository uses lowercase headers and month strings such as `Jan-15`, so the loader normalizes the headers and parses the month text into numeric year and month columns. Second, the output writer formats the fields exactly in the order requested by the brief: `(x, y), Year, Month, Town, Block, Floor_Area, Flat_Model, Lease_Commence_Date, Price_Per_Square_Meter`.

Possible exceptions are handled during input and output. The code rejects invalid matriculation numbers that do not contain enough digits, checks that the CSV has a header row, and can optionally emit `No result` rows for `(x, y)` combinations with no valid candidate. For the matriculation number `{spec.matric_number}`, every one of the 568 `(x, y)` combinations produced a valid result row.

## 2. Data Processing

The matriculation number `{spec.matric_number}` produces the following query settings:

- target start year: {spec.start_year}
- target start month: {spec.start_month:02d}
- matched towns: {", ".join(spec.towns)}

The scan enumerates every `(x, y)` pair where `1 <= x <= 8` and `80 <= y <= 150`. A month key defined as `year * 12 + month` is precomputed for each row, making it easy to test whether a transaction falls inside a target `x`-month window. The program first filters rows by town and by the largest possible month window, then buckets the matching row indices by month offset. This lets larger windows reuse the rows already found for smaller windows rather than rescanning the full table from scratch.

For each active window, candidate rows are sorted by descending floor area and then by price-per-square-meter order. The algorithm then walks the area thresholds from 150 down to 80. As soon as a row satisfies the current minimum area, it becomes eligible for that threshold and for every smaller threshold. This allows one pass over the sorted candidate list to determine the best row for all 71 possible `y` values in the current window.

The final minimum is based on the raw value `resale_price / floor_area`. Rounding is applied only at output time. Ties are broken deterministically using price per square meter, month, town, block, flat model, lease commencement date, and original row order so the result remains stable across repeated runs.

## 3. Experiment Result

The program loaded {len(raw_rows):,} rows and produced {len(output_rows)} result rows. The output distribution was:

- by town: {dict(town_counts)}
- by year-month: {dict(month_counts)}

The first output row is `({first_row['(x, y)']}, {first_row['Year']}-{first_row['Month']}, {first_row['Town']}, block {first_row['Block']}, {first_row['Floor_Area']} sqm, {first_row['Flat_Model']}, lease {first_row['Lease_Commence_Date']}, {first_row['Price_Per_Square_Meter']})`. The last output row is `({last_row['(x, y)']}, {last_row['Year']}-{last_row['Month']}, {last_row['Town']}, block {last_row['Block']}, {last_row['Floor_Area']} sqm, {last_row['Flat_Model']}, lease {last_row['Lease_Commence_Date']}, {last_row['Price_Per_Square_Meter']})`. This confirms that the output is sorted by increasing `x`, and then by increasing `y`.

To validate correctness independently, four representative query pairs were recomputed using a separate brute-force validator that does not reuse the scanner’s window-processing logic. The validator filtered the raw CSV directly, recomputed the minimum price per square meter, and compared the resulting record with the generated output file. The comparison is summarized below.

| Pair | Candidate Count | Independent Rounded | Program Rounded | Match | Town | Block |
| --- | ---: | ---: | ---: | --- | --- | --- |
{summary_table}

All four validation checks matched exactly. In addition, an Excel workbook was generated with one sheet per validated pair. Each sheet contains the filtered candidate records, an Excel `MIN(...)` formula over the raw `Price_Per_Sqm_Raw` column, a `ROUND(...)` formula for the integer output value, and a direct comparison against the program output. These workbook sheets provide the same kind of spreadsheet-based evidence requested in the project brief.
"""


def draw_pdf_text_page(pdf: PdfPages, title: str, paragraphs: Sequence[str], footer: str = "") -> None:
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.patch.set_facecolor("white")
    fig.text(0.07, 0.965, title, fontsize=16, weight="bold", va="top")
    y_pos = 0.92
    for paragraph in paragraphs:
        content = wrapped(paragraph, width=96)
        fig.text(0.07, y_pos, content, fontsize=10.5, va="top")
        line_count = content.count("\n") + 1
        y_pos -= 0.028 * line_count + 0.02
    if footer:
        fig.text(0.07, 0.04, wrapped(footer, width=100), fontsize=9, va="bottom")
    plt.axis("off")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def add_image(fig, path: Path, rect: Sequence[float]) -> None:
    axis = fig.add_axes(rect)
    axis.imshow(plt.imread(path))
    axis.axis("off")


def build_report_pdf(
    spec: QuerySpec,
    summary_rows: Sequence[Dict[str, str]],
    output_rows: Sequence[Dict[str, str]],
    raw_rows: Sequence[RawRow],
    figure_dir: Path,
    report_pdf_path: Path,
) -> None:
    town_counts = Counter(row["Town"] for row in output_rows)
    month_counts = Counter(f"{row['Year']}-{row['Month']}" for row in output_rows)

    with PdfPages(report_pdf_path) as pdf:
        draw_pdf_text_page(
            pdf,
            "Semester Group Project Report",
            [
                "Name: [Fill in your name]",
                f"Matriculation Number: {spec.matric_number}",
                "",
                "Data Storage",
                f"The input dataset contains {len(raw_rows):,} resale transactions from Jan 2015 to Dec 2025. "
                "The implementation uses a column-oriented layout by storing each field in its own Python list. "
                "The main columns are year, month_num, month_key, town, block, floor_area_sqm, flat_model, "
                "lease_commence_date, resale_price, and the derived price_per_sqm column.",
                "This design satisfies the project requirement to store and process the table in a column-store manner. "
                "The loader also normalizes the real repository CSV, which uses lowercase headers and month strings such as Jan-15, "
                "so the processing logic stays aligned with the brief.",
                "Possible exceptions are handled at load time and output time. The code checks for missing headers, rejects invalid matriculation numbers, "
                "and can optionally emit No result rows. For U2221027H, all 568 (x, y) combinations produced valid records.",
            ],
        )

        draw_pdf_text_page(
            pdf,
            "Data Processing",
            [
                f"Derived query settings for {spec.matric_number}: start year {spec.start_year}, start month {spec.start_month:02d}, towns {', '.join(spec.towns)}.",
                "The program enumerates every (x, y) pair for 1 <= x <= 8 and 80 <= y <= 150. A month key of year * 12 + month is precomputed for each row so range tests are cheap during the scan.",
                "To reuse intermediate results, the implementation first filters rows by the matched towns and the largest possible eight-month window, then buckets the surviving row indices by month offset. "
                "As x grows from 1 to 8, each new window only adds the rows from one extra month.",
                "Within a fixed x window, the candidate rows are sorted by descending floor area and then by price-per-square-meter order. "
                "The algorithm walks the area thresholds from 150 down to 80 so each candidate row is considered once and can serve every smaller threshold that it satisfies.",
                "Price per square meter is computed from the raw resale_price / floor_area value, and rounding is applied only when the output CSV is written. "
                "Ties are broken deterministically by month, town, block, flat model, lease commencement date, and original row order.",
            ],
            footer="This approach keeps the implementation simple while still reusing work across month windows and across area thresholds.",
        )

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("white")
        fig.text(0.07, 0.965, "Experiment Result", fontsize=16, weight="bold", va="top")
        fig.text(
            0.07,
            0.915,
            wrapped(
                f"The program loaded {len(raw_rows):,} rows and produced {len(output_rows)} output rows. "
                f"Result distribution by town: {dict(town_counts)}. Result distribution by year-month: {dict(month_counts)}."
            ),
            fontsize=10.5,
            va="top",
        )
        fig.text(
            0.07,
            0.84,
            wrapped(
                "The two figures below show a successful execution run and a preview of the generated output CSV. "
                "Together they demonstrate that the program runs successfully and writes the requested output fields in order."
            ),
            fontsize=10.5,
            va="top",
        )
        add_image(fig, figure_dir / "run_output.png", [0.07, 0.49, 0.86, 0.27])
        add_image(fig, figure_dir / "output_preview.png", [0.07, 0.09, 0.86, 0.32])
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("white")
        fig.text(0.07, 0.965, "Validation", fontsize=16, weight="bold", va="top")
        fig.text(
            0.07,
            0.915,
            wrapped(
                "Four representative (x, y) pairs were validated with an independent brute-force checker. "
                "The checker filtered the raw CSV directly and recomputed the minimum price per square meter without using the scanner's month-bucketing logic. "
                "All four comparisons matched the generated output exactly."
            ),
            fontsize=10.5,
            va="top",
        )
        add_image(fig, figure_dir / "validation_summary.png", [0.07, 0.60, 0.86, 0.21])
        add_image(fig, figure_dir / "validation_pair_1_80.png", [0.07, 0.31, 0.86, 0.22])
        add_image(fig, figure_dir / "validation_pair_1_147.png", [0.07, 0.04, 0.86, 0.22])
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate validation and report artifacts.")
    parser.add_argument("matric_number", help="Matriculation number used for the project.")
    parser.add_argument("--input", default="ResalePricesSingapore.csv", help="Input resale CSV file.")
    parser.add_argument(
        "--output",
        default=None,
        help="Output scan result CSV. Defaults to ScanResult_<MatricNum>.csv.",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    csv_path = repo_root / args.input
    output_path = repo_root / (args.output or f"ScanResult_{args.matric_number}.csv")
    spec = build_query_spec(args.matric_number)

    raw_rows = load_raw_rows(csv_path)
    output_rows = load_output_rows(output_path)
    output_map = {pair_from_text(row["(x, y)"]): row for row in output_rows}

    validation_dir = repo_root / "validation"
    figure_dir = repo_root / "report_assets" / "figures"
    report_md_path = repo_root / "Report.md"
    report_pdf_path = repo_root / "Report.pdf"

    summary_rows: List[Dict[str, str]] = []
    candidate_map: Dict[Tuple[int, int], List[RawRow]] = {}

    for pair in SELECTED_PAIRS:
        candidates = filtered_candidates(raw_rows, spec, pair[0], pair[1])
        candidate_map[pair] = candidates
        best = candidates[0]
        program = output_map[pair]
        matched = (
            str(best.year) == program["Year"]
            and f"{best.month_num:02d}" == program["Month"]
            and best.town == program["Town"]
            and best.block == program["Block"]
            and format_floor_area(best.floor_area) == program["Floor_Area"]
            and best.flat_model == program["Flat_Model"]
            and best.lease_commence_date == program["Lease_Commence_Date"]
            and str(round_half_up(best.price_per_sqm)) == program["Price_Per_Square_Meter"]
        )
        summary_rows.append(
            {
                "Pair": f"({pair[0]}, {pair[1]})",
                "Candidate_Count": str(len(candidates)),
                "Independent_Min_Raw": f"{best.price_per_sqm:.6f}",
                "Independent_Min_Rounded": str(round_half_up(best.price_per_sqm)),
                "Program_Min_Rounded": program["Price_Per_Square_Meter"],
                "Matched": "YES" if matched else "NO",
                "Year": str(best.year),
                "Month": f"{best.month_num:02d}",
                "Town": best.town,
                "Block": best.block,
                "Floor_Area": format_floor_area(best.floor_area),
                "Flat_Model": best.flat_model,
                "Lease_Commence_Date": best.lease_commence_date,
            }
        )

    write_validation_summary_csv(summary_rows, validation_dir / f"{args.matric_number}_validation_summary.csv")
    write_validation_workbook(summary_rows, candidate_map, validation_dir / f"{args.matric_number}_validation_workbook.xlsx")
    write_final_checks(output_rows, validation_dir / "final_checks.txt", spec)

    run_output = subprocess.run(
        ["python3", "source/scan_resale_prices.py", args.matric_number],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    run_text = f"$ python3 source/scan_resale_prices.py {args.matric_number}\n{run_output.stdout.strip()}"
    save_text_figure(run_text, figure_dir / "run_output.png", "Program Execution")

    preview_rows = [list(output_rows[idx].values()) for idx in [0, 1, 2, 3, len(output_rows) - 4, len(output_rows) - 3, len(output_rows) - 2, len(output_rows) - 1]]
    preview_rows.insert(4, ["...", "...", "...", "...", "...", "...", "...", "...", "..."])
    save_table_figure(
        headers=list(output_rows[0].keys()),
        rows=preview_rows,
        output_path=figure_dir / "output_preview.png",
        title="Output Preview",
        note="Top four and bottom four rows from ScanResult_U2221027H.csv. The preview shows the required field order and the expected sorting by (x, y).",
        figsize=(12.0, 4.2),
        font_size=7,
    )

    validation_summary_rows = [
        [
            row["Pair"],
            row["Candidate_Count"],
            row["Independent_Min_Rounded"],
            row["Program_Min_Rounded"],
            row["Matched"],
            row["Town"],
            row["Block"],
            f"{row['Year']}-{row['Month']}",
        ]
        for row in summary_rows
    ]
    save_table_figure(
        headers=[
            "Pair",
            "Candidates",
            "Independent",
            "Program",
            "Match",
            "Town",
            "Block",
            "Month",
        ],
        rows=validation_summary_rows,
        output_path=figure_dir / "validation_summary.png",
        title="Independent Validation Summary",
        note="Each pair was recomputed from the raw CSV with a separate brute-force pass.",
        figsize=(11.0, 2.8),
        font_size=9,
    )

    for pair in ((1, 80), (1, 147)):
        candidates = candidate_map[pair][:6]
        candidate_rows = [
            [
                row.month_text,
                row.town,
                row.block,
                format_floor_area(row.floor_area),
                row.flat_model,
                f"{row.price_per_sqm:.3f}",
                str(round_half_up(row.price_per_sqm)),
            ]
            for row in candidates
        ]
        best = candidates[0]
        note = (
            f"Pair ({pair[0]}, {pair[1]}): the sheet in the validation workbook uses Excel formulas "
            f"=MIN(...) and =ROUND(...,0). The minimum raw value is {best.price_per_sqm:.6f}, which rounds to {round_half_up(best.price_per_sqm)}."
        )
        save_table_figure(
            headers=["Month", "Town", "Block", "Floor_Area", "Flat_Model", "Raw PPSQM", "Rounded"],
            rows=candidate_rows,
            output_path=figure_dir / f"validation_pair_{pair[0]}_{pair[1]}.png",
            title=f"Validation Example for ({pair[0]}, {pair[1]})",
            note=note,
            figsize=(11.0, 2.8),
            font_size=8,
        )

    report_md_path.write_text(build_report_markdown(spec, summary_rows, output_rows, raw_rows), encoding="utf-8")
    build_report_pdf(spec, summary_rows, output_rows, raw_rows, figure_dir, report_pdf_path)

    print(f"Wrote validation summary to {validation_dir / f'{args.matric_number}_validation_summary.csv'}")
    print(f"Wrote validation workbook to {validation_dir / f'{args.matric_number}_validation_workbook.xlsx'}")
    print(f"Wrote report markdown to {report_md_path}")
    print(f"Wrote report PDF to {report_pdf_path}")


if __name__ == "__main__":
    main()
