#!/usr/bin/env python3
"""Column-store scanner for the resale flat semester project."""

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PRICE_PER_SQM_LIMIT = 4725.0
MIN_X = 1
MAX_X = 8
MIN_Y = 80
MAX_Y = 150

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

OUTPUT_HEADERS = [
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


def canonicalize(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


def parse_month_text(raw_month: str) -> Tuple[int, int]:
    for fmt in ("%b-%y", "%Y-%m"):
        try:
            parsed = datetime.strptime(raw_month.strip(), fmt)
            return parsed.year, parsed.month
        except ValueError:
            continue
    raise ValueError(f"Unsupported month format: {raw_month!r}")


def round_half_up(value: float) -> int:
    return int(value + 0.5)


def format_floor_area(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class QuerySpec:
    matric_number: str
    start_year: int
    start_month: int
    towns: Tuple[str, ...]

    @property
    def start_key(self) -> int:
        return self.start_year * 12 + self.start_month


@dataclass
class ColumnStore:
    month_text: List[str]
    year: List[int]
    month_num: List[int]
    month_key: List[int]
    town: List[str]
    flat_type: List[str]
    block: List[str]
    street_name: List[str]
    storey_range: List[str]
    floor_area_sqm: List[float]
    flat_model: List[str]
    lease_commence_date: List[str]
    resale_price: List[float]
    price_per_sqm: List[float]

    def __len__(self) -> int:
        return len(self.year)


def resolve_headers(fieldnames: Sequence[str]) -> Dict[str, str]:
    aliases = {
        "month": ("month",),
        "town": ("town",),
        "flat_type": ("flattype", "flattype"),
        "block": ("block",),
        "street_name": ("streetname",),
        "storey_range": ("storeyrange",),
        "floor_area_sqm": ("floorareasqm", "floorarea"),
        "flat_model": ("flatmodel",),
        "lease_commence_date": ("leasecommencedate",),
        "resale_price": ("resaleprice",),
    }

    available = {canonicalize(name): name for name in fieldnames}
    resolved: Dict[str, str] = {}

    for logical_name, accepted_names in aliases.items():
        for accepted in accepted_names:
            if accepted in available:
                resolved[logical_name] = available[accepted]
                break
        else:
            raise KeyError(f"Missing required column for {logical_name!r}")

    return resolved


def load_column_store(csv_path: Path) -> ColumnStore:
    # Each CSV field is loaded into its own list so the dataset stays in a
    # column-oriented layout throughout the scan.
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is missing a header row.")

        headers = resolve_headers(reader.fieldnames)
        store = ColumnStore(
            month_text=[],
            year=[],
            month_num=[],
            month_key=[],
            town=[],
            flat_type=[],
            block=[],
            street_name=[],
            storey_range=[],
            floor_area_sqm=[],
            flat_model=[],
            lease_commence_date=[],
            resale_price=[],
            price_per_sqm=[],
        )

        for row in reader:
            year, month_num = parse_month_text(row[headers["month"]])
            floor_area = float(row[headers["floor_area_sqm"]])
            resale_price = float(row[headers["resale_price"]])

            store.month_text.append(row[headers["month"]].strip())
            store.year.append(year)
            store.month_num.append(month_num)
            store.month_key.append(year * 12 + month_num)
            store.town.append(row[headers["town"]].strip())
            store.flat_type.append(row[headers["flat_type"]].strip())
            store.block.append(row[headers["block"]].strip())
            store.street_name.append(row[headers["street_name"]].strip())
            store.storey_range.append(row[headers["storey_range"]].strip())
            store.floor_area_sqm.append(floor_area)
            store.flat_model.append(row[headers["flat_model"]].strip())
            store.lease_commence_date.append(row[headers["lease_commence_date"]].strip())
            store.resale_price.append(resale_price)
            store.price_per_sqm.append(resale_price / floor_area)

    return store


def build_query_spec(matric_number: str) -> QuerySpec:
    digits = [int(ch) for ch in matric_number if ch.isdigit()]
    if len(digits) < 2:
        raise ValueError("Matric number must contain at least two digits.")

    last_digit = digits[-1]
    second_last_digit = digits[-2]

    start_year = 2015 + ((last_digit - 5) % 10)
    start_month = 10 if second_last_digit == 0 else second_last_digit
    towns = tuple(sorted({DIGIT_TO_TOWN[digit] for digit in digits}))

    return QuerySpec(
        matric_number=matric_number,
        start_year=start_year,
        start_month=start_month,
        towns=towns,
    )


def row_ordering_key(store: ColumnStore, index: int) -> Tuple[float, int, str, str, str, str, int]:
    return (
        store.price_per_sqm[index],
        store.month_key[index],
        store.town[index],
        store.block[index],
        store.flat_model[index],
        store.lease_commence_date[index],
        index,
    )


def better_row(store: ColumnStore, candidate: int, current: Optional[int]) -> int:
    if current is None:
        return candidate
    if row_ordering_key(store, candidate) < row_ordering_key(store, current):
        return candidate
    return current


def compute_window_buckets(store: ColumnStore, spec: QuerySpec) -> List[List[int]]:
    buckets: List[List[int]] = [[] for _ in range(MAX_X)]
    matched_towns = set(spec.towns)
    start_key = spec.start_key
    end_key = start_key + MAX_X - 1

    # Bucket qualifying row indices by month offset so larger x-windows can
    # reuse the rows already collected for smaller windows.
    for index in range(len(store)):
        if store.town[index] not in matched_towns:
            continue
        month_key = store.month_key[index]
        if not (start_key <= month_key <= end_key):
            continue
        buckets[month_key - start_key].append(index)

    return buckets


def compute_results_for_window(store: ColumnStore, active_indices: Iterable[int]) -> Dict[int, Optional[int]]:
    by_area = sorted(
        active_indices,
        key=lambda idx: (-store.floor_area_sqm[idx], row_ordering_key(store, idx)),
    )

    results: Dict[int, Optional[int]] = {}
    best_index: Optional[int] = None
    cursor = 0

    for min_area in range(MAX_Y, MIN_Y - 1, -1):
        while cursor < len(by_area) and store.floor_area_sqm[by_area[cursor]] >= min_area:
            best_index = better_row(store, by_area[cursor], best_index)
            cursor += 1

        if best_index is not None and store.price_per_sqm[best_index] <= PRICE_PER_SQM_LIMIT:
            results[min_area] = best_index
        else:
            results[min_area] = None

    return results


def build_output_rows(
    store: ColumnStore,
    spec: QuerySpec,
    include_no_result: bool,
) -> List[List[str]]:
    rows: List[List[str]] = []
    buckets = compute_window_buckets(store, spec)
    active_indices: List[int] = []

    for months in range(MIN_X, MAX_X + 1):
        active_indices.extend(buckets[months - 1])
        best_rows_by_area = compute_results_for_window(store, active_indices)

        for min_area in range(MIN_Y, MAX_Y + 1):
            best_index = best_rows_by_area[min_area]
            if best_index is None:
                if include_no_result:
                    rows.append(
                        [
                            f"({months}, {min_area})",
                            "No result",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                        ]
                    )
                continue

            rows.append(
                [
                    f"({months}, {min_area})",
                    f"{store.year[best_index]:04d}",
                    f"{store.month_num[best_index]:02d}",
                    store.town[best_index],
                    store.block[best_index],
                    format_floor_area(store.floor_area_sqm[best_index]),
                    store.flat_model[best_index],
                    store.lease_commence_date[best_index],
                    str(round_half_up(store.price_per_sqm[best_index])),
                ]
            )

    return rows


def write_output(output_path: Path, rows: Sequence[Sequence[str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUTPUT_HEADERS)
        writer.writerows(rows)


def build_output_path(output_arg: Optional[str], matric_number: str) -> Path:
    if output_arg:
        return Path(output_arg)
    return Path(f"ScanResult_{matric_number}.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan HDB resale data using a column-oriented in-memory layout.",
    )
    parser.add_argument("matric_number", help="Matriculation number used to derive the query.")
    parser.add_argument(
        "--input",
        default="ResalePricesSingapore.csv",
        help="Path to the resale price CSV file.",
    )
    parser.add_argument(
        "--output",
        help="Path for the output CSV file. Defaults to ScanResult_<MatricNum>.csv.",
    )
    parser.add_argument(
        "--include-no-result",
        action="store_true",
        help="Emit all (x, y) pairs and write 'No result' rows when no valid match exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = build_output_path(args.output, args.matric_number)

    spec = build_query_spec(args.matric_number)
    store = load_column_store(input_path)
    output_rows = build_output_rows(store, spec, include_no_result=args.include_no_result)
    write_output(output_path, output_rows)

    print(f"Loaded {len(store)} rows from {input_path}.")
    print(
        "Query settings:",
        f"start={spec.start_year}-{spec.start_month:02d},",
        f"towns={', '.join(spec.towns)}",
    )
    print(f"Wrote {len(output_rows)} result rows to {output_path}.")


if __name__ == "__main__":
    main()
