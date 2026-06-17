from collections import Counter
from datetime import datetime
from pathlib import Path
import warnings
import re
import zipfile
import xml.etree.ElementTree as ET
from copy import copy

import pandas as pd
from openpyxl import load_workbook


SOURCE_PATTERN = "*中心运单查询*.xlsx"
TEMPLATE_PATTERN = "当日数据统计*.xlsx"
OUTPUT_FILE = Path("当日数据统计.xlsx")
today = datetime.now()
REPORT_DATE = f"{today.month}月{today.day:02d}日"

SOURCE_SHEET = "数据源1-预测"
BASE_COLUMNS = ["运单号", "路由码", "派件网点简码"]
MERCHANT_COLUMN = "商家编号"
REQUIRED_COLUMNS = [*BASE_COLUMNS, MERCHANT_COLUMN]
TEMPLATE_REQUIRED_COLUMNS = BASE_COLUMNS

MERCHANT_CODES = {
    "TEMU": "C2103951401",
    "CAINIAO": "C2103960401",
    "SUNYOU": "C2104258001",
}
CAINIAO_MERCHANT_CODE = MERCHANT_CODES["CAINIAO"]
SUNYOU_MERCHANT_CODE = MERCHANT_CODES["SUNYOU"]


def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def load_source_data():
    source_file, df = find_latest_source_file()
    print(f"Using source file: {source_file}")
    df = df[df["运单号"] != ""].drop_duplicates(subset=["运单号"], keep="first")
    return df.reset_index(drop=True)


def find_latest_source_file():
    files = [
        path
        for path in Path(".").glob(SOURCE_PATTERN)
        if not path.name.startswith("~$")
    ]
    if not files:
        raise FileNotFoundError(f"No source file found matching {SOURCE_PATTERN}")

    skipped = []
    for path in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True):
        df = read_source_xlsx(path)
        missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
        if not missing:
            if skipped:
                print("Skipped source files missing required columns:")
                for skipped_path, skipped_missing in skipped:
                    print(f"- {skipped_path}: missing {skipped_missing}")
            return path, df
        skipped.append((path, missing))

    details = "; ".join(f"{path}: missing {missing}" for path, missing in skipped)
    raise ValueError(f"No valid source file found matching {SOURCE_PATTERN}. {details}")


def find_latest_template_file():
    files = [
        path
        for path in Path(".").glob(TEMPLATE_PATTERN)
        if not path.name.startswith("~$")
    ]
    if not files:
        raise FileNotFoundError(f"No template file found matching {TEMPLATE_PATTERN}")
    return max(files, key=lambda path: path.stat().st_mtime)


def read_source_xlsx(path):
    shared_strings = []
    with zipfile.ZipFile(path) as archive:
        if "xl/sharedStrings.xml" in archive.namelist():
            for event, element in ET.iterparse(archive.open("xl/sharedStrings.xml"), events=("end",)):
                if element.tag.endswith("}si"):
                    shared_strings.append("".join(text.text or "" for text in element.iter() if text.tag.endswith("}t")))
                    element.clear()

        sheet_name = get_first_sheet_path(archive)
        required_indexes = None
        rows = []

        for event, row_element in ET.iterparse(archive.open(sheet_name), events=("end",)):
            if not row_element.tag.endswith("}row"):
                continue

            row_number = int(row_element.attrib.get("r", "0"))
            values_by_col = {}
            for cell in row_element:
                if not cell.tag.endswith("}c"):
                    continue
                col_index = column_index_from_cell_ref(cell.attrib.get("r", ""))
                values_by_col[col_index] = read_cell_value(cell, shared_strings)

            if row_number == 1:
                header_to_index = {clean_text(value): col for col, value in values_by_col.items()}
                required_indexes = {column: header_to_index[column] for column in REQUIRED_COLUMNS if column in header_to_index}
            elif required_indexes:
                row = {
                    column: clean_text(values_by_col.get(col_index, ""))
                    for column, col_index in required_indexes.items()
                }
                if row.get("运单号"):
                    rows.append(row)

            row_element.clear()

    return pd.DataFrame(rows, columns=[column for column in REQUIRED_COLUMNS if rows and column in rows[0]] or REQUIRED_COLUMNS)


def get_first_sheet_path(archive):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_by_id = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    first_sheet = next(element for element in workbook.iter() if element.tag.endswith("}sheet"))
    relationship_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    target = relationship_by_id[relationship_id]
    if target.startswith("/"):
        return target.lstrip("/")
    return f"xl/{target.lstrip('/')}"


def column_index_from_cell_ref(cell_ref):
    letters = re.match(r"[A-Z]+", cell_ref).group(0)
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter) - ord("A") + 1
    return number


def read_cell_value(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.iter() if text.tag.endswith("}t"))

    value_element = next((child for child in cell if child.tag.endswith("}v")), None)
    if value_element is None or value_element.text is None:
        return ""

    if cell_type == "s":
        index = int(value_element.text)
        return shared_strings[index] if index < len(shared_strings) else ""

    return value_element.text


def clear_range(ws, min_row, max_row, min_col, max_col):
    for row in ws.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col):
        for cell in row:
            cell.value = None


def ensure_data_source_column_order(ws):
    desired_first_columns = TEMPLATE_REQUIRED_COLUMNS
    headers = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
    if headers[: len(desired_first_columns)] == desired_first_columns:
        return

    header_to_col = {header: col for col, header in enumerate(headers, start=1) if header}
    missing = [column for column in desired_first_columns if column not in header_to_col]
    if missing:
        raise ValueError(f"{SOURCE_SHEET} is missing columns: {missing}")

    ordered_columns = [header_to_col[column] for column in desired_first_columns]
    ordered_columns.extend(
        col
        for col, header in enumerate(headers, start=1)
        if header not in desired_first_columns
    )

    max_row = ws.max_row
    max_col = ws.max_column
    rows = []
    for row_index in range(1, max_row + 1):
        row_snapshot = []
        for source_col in ordered_columns:
            source_cell = ws.cell(row_index, source_col)
            row_snapshot.append(
                {
                    "value": source_cell.value,
                    "fill": copy(source_cell.fill),
                    "font": copy(source_cell.font),
                    "border": copy(source_cell.border),
                    "alignment": copy(source_cell.alignment),
                    "number_format": source_cell.number_format,
                    "protection": copy(source_cell.protection),
                }
            )
        rows.append(row_snapshot)

    column_widths = {
        target_col: ws.column_dimensions[ws.cell(1, source_col).column_letter].width
        for target_col, source_col in enumerate(ordered_columns, start=1)
    }

    clear_range(ws, 1, max_row, 1, max_col)
    for row_index, row_snapshot in enumerate(rows, start=1):
        for col_index, cell_snapshot in enumerate(row_snapshot, start=1):
            target_cell = ws.cell(row_index, col_index)
            target_cell.value = cell_snapshot["value"]
            target_cell.fill = copy(cell_snapshot["fill"])
            target_cell.font = copy(cell_snapshot["font"])
            target_cell.border = copy(cell_snapshot["border"])
            target_cell.alignment = copy(cell_snapshot["alignment"])
            target_cell.number_format = cell_snapshot["number_format"]
            target_cell.protection = copy(cell_snapshot["protection"])

    for col_index, width in column_widths.items():
        ws.column_dimensions[ws.cell(1, col_index).column_letter].width = width


def write_data_source(wb, df):
    ws = wb[SOURCE_SHEET]
    ensure_data_source_column_order(ws)

    header_to_col = {ws.cell(1, col).value: col for col in range(1, ws.max_column + 1)}
    missing = [column for column in TEMPLATE_REQUIRED_COLUMNS if column not in header_to_col]
    if missing:
        raise ValueError(f"{SOURCE_SHEET} is missing columns: {missing}")

    old_max_row = ws.max_row
    if old_max_row > 1:
        clear_range(ws, 2, old_max_row, 1, ws.max_column)

    for index, row in df.iterrows():
        excel_row = index + 2
        ws.cell(excel_row, header_to_col["运单号"]).value = row["运单号"]
        ws.cell(excel_row, header_to_col["派件网点简码"]).value = row["派件网点简码"]
        ws.cell(excel_row, header_to_col["路由码"]).value = row["路由码"]
        if MERCHANT_COLUMN in header_to_col:
            ws.cell(excel_row, header_to_col[MERCHANT_COLUMN]).value = row[MERCHANT_COLUMN]

    first_extra_row = len(df) + 2
    if old_max_row >= first_extra_row:
        ws.delete_rows(first_extra_row, old_max_row - first_extra_row + 1)


def find_total_row(ws, column=1, label="总计"):
    for row in range(1, ws.max_row + 1):
        value = clean_text(ws.cell(row, column).value)
        if value == label:
            return row
    raise ValueError(f"Could not find {label} in {ws.title}")


def rebuild_non_auckland_pivot(wb, station_counts):
    ws = wb["非奥克兰透视"]
    clear_range(ws, 1, max(ws.max_row, len(station_counts) + 4), 1, 2)

    ws.cell(3, 1).value = "派件网点简码"
    ws.cell(3, 2).value = "计数项:运单号"

    row = 4
    for station, count in sorted(station_counts.items()):
        ws.cell(row, 1).value = station
        ws.cell(row, 2).value = count
        row += 1

    ws.cell(row, 1).value = "总计"
    ws.cell(row, 2).value = sum(station_counts.values())


def rebuild_auckland_pivot(wb, route_counts):
    ws = wb["奥克兰透视"]
    clear_range(ws, 4, max(ws.max_row, len(route_counts) + 5), 1, 2)

    ws.cell(3, 1).value = "路由码"
    ws.cell(3, 2).value = "计数项:运单号"

    row = 4
    for route_code, count in sorted(route_counts.items(), key=lambda item: str(item[0])):
        ws.cell(row, 1).value = route_code
        ws.cell(row, 2).value = count
        row += 1

    ws.cell(row, 1).value = "总计"
    ws.cell(row, 2).value = sum(route_counts.values())

    # Refresh only the fixed side-summary tables. Scanning the whole sheet can
    # overwrite helper cells that happen to contain route-like values.
    route_table_ranges = [
        (8, 9, 6, 7),     # WGR
        (9, 24, 10, 11),  # HMT
        (30, 31, 7, 8),   # RTR
        (29, 34, 10, 11), # TRG
        (40, 47, 10, 11), # NPL/HST
        (9, 19, 13, 14),  # WLT
    ]
    for start_row, end_row, route_col, qty_col in route_table_ranges:
        for row in range(start_row, end_row + 1):
            route_code = clean_text(ws.cell(row, route_col).value)
            if route_code:
                ws.cell(row, qty_col).value = route_counts.get(route_code, 0)


def update_auckland_sheet(wb, route_counts):
    ws = wb["奥克兰"]
    ws.cell(1, 1).value = f"{REPORT_DATE}奥克兰分单"
    ws.cell(2, 12).value = REPORT_DATE
    total_row = find_total_row(ws, column=1)

    for row in range(3, total_row):
        route_code = clean_text(ws.cell(row, 1).value)
        if route_code:
            ws.cell(row, 3).value = route_counts.get(route_code, 0)

    total = sum(ws.cell(row, 3).value or 0 for row in range(3, total_row))
    ws.cell(total_row, 3).value = total
    return total


def update_non_auckland_sheet(wb, station_counts, cainiao_counts, sunyou_counts, aliexpress_count, sunyou_count, auckland_total):
    ws = wb["非奥克兰"]
    ws.cell(1, 1).value = f"{REPORT_DATE}非奥克兰到件货量"
    ws.cell(1, 9).value = REPORT_DATE
    total_row = find_total_row(ws, column=1)

    for row in range(3, total_row):
        station = clean_text(ws.cell(row, 1).value)
        alias = clean_text(ws.cell(row, 2).value)

        arrival = station_counts.get(station, 0) + station_counts.get(alias, 0)
        if station == "RTR":
            arrival = sum(count for key, count in station_counts.items() if key.startswith("RTR"))

        ws.cell(row, 3).value = arrival
        ws.cell(row, 6).value = cainiao_counts.get(station, 0)
        ws.cell(row, 7).value = sunyou_counts.get(station, 0)

    non_auckland_total = sum(ws.cell(row, 3).value or 0 for row in range(3, total_row))
    cainiao_total = sum(ws.cell(row, 6).value or 0 for row in range(3, total_row))
    sunyou_total = sum(ws.cell(row, 7).value or 0 for row in range(3, total_row))

    ws.cell(total_row, 3).value = non_auckland_total
    ws.cell(total_row, 6).value = cainiao_total
    ws.cell(total_row, 7).value = sunyou_total
    ws.cell(14, 1).value = aliexpress_count
    ws.cell(13, 3).value = "顺友单量"
    ws.cell(14, 3).value = sunyou_count

    write_total_breakdown(ws, auckland_total, non_auckland_total)

    write_board_forecast_values(ws)

    return non_auckland_total


def write_total_breakdown(ws, auckland_total, non_auckland_total):
    total = auckland_total + non_auckland_total

    source_header = ws.cell(13, 6)
    source_value = ws.cell(14, 6)
    header_style = {
        attr: copy(getattr(source_header, attr))
        for attr in ["fill", "font", "border", "alignment", "number_format", "protection"]
    }
    value_style = {
        attr: copy(getattr(source_value, attr))
        for attr in ["fill", "font", "border", "alignment", "number_format", "protection"]
    }

    for merged_range in list(ws.merged_cells.ranges):
        if (
            merged_range.min_row <= 14
            and merged_range.max_row >= 13
            and merged_range.min_col <= 7
            and merged_range.max_col >= 4
        ):
            ws.unmerge_cells(str(merged_range))

    ws.cell(13, 4).value = None
    ws.cell(14, 4).value = None
    ws.cell(13, 5).value = None
    ws.cell(14, 5).value = None
    ws.cell(13, 7).value = None
    ws.cell(14, 7).value = None

    ws.merge_cells(start_row=13, start_column=6, end_row=13, end_column=7)
    ws.merge_cells(start_row=14, start_column=6, end_row=14, end_column=7)

    header_cell = ws.cell(13, 6)
    value_cell = ws.cell(14, 6)
    header_cell.value = "当天总量（奥克兰 + 外省）"
    value_cell.value = f"{total}({auckland_total}+{non_auckland_total})"

    for attr, style in header_style.items():
        setattr(header_cell, attr, copy(style))
    for attr, style in value_style.items():
        setattr(value_cell, attr, copy(style))

    ws.column_dimensions["D"].width = 20.8181818181818
    ws.column_dimensions["E"].width = 12.8181818181818
    ws.column_dimensions["F"].width = 24.9
    ws.column_dimensions["G"].width = 24.9


def round_excel(value, digits=2):
    return round(float(value), digits)


def write_board_forecast_values(ws):
    base_3l = ws.cell(2, 8).value or 135
    base_5l = ws.cell(13, 8).value or 350

    arrival_by_station = {
        clean_text(ws.cell(row, 1).value): ws.cell(row, 3).value or 0
        for row in range(3, 11)
    }

    rows_3l = {
        3: "RTR",
        4: "HMT",
        5: "TRG",
        6: "HST",
        7: "NPL",
        8: "WGR",
        9: "WLT",
    }
    rows_5l = {
        14: "RTR",
        15: "HMT",
        16: "TRG",
        17: "HST",
        18: "NPL",
        19: "WGR",
        20: "WLT",
    }

    for row, station in rows_3l.items():
        ws.cell(row, 9).value = round_excel(arrival_by_station.get(station, 0) / base_3l)

    ws.cell(10, 9).value = sum(ws.cell(row, 9).value or 0 for row in [5, 7, 6, 4])
    ws.cell(10, 9).value = round_excel(ws.cell(10, 9).value)

    for row, station in rows_5l.items():
        ws.cell(row, 9).value = round_excel(arrival_by_station.get(station, 0) / base_5l)

    ws.cell(21, 9).value = sum(ws.cell(row, 9).value or 0 for row in [16, 18, 17, 15])
    ws.cell(21, 9).value = round_excel(ws.cell(21, 9).value)


def main():
    df = load_source_data()

    station_counts = Counter(df["派件网点简码"])
    route_counts = Counter(df["路由码"])
    cainiao_mask = df[MERCHANT_COLUMN].eq(CAINIAO_MERCHANT_CODE)
    sunyou_mask = df[MERCHANT_COLUMN].eq(SUNYOU_MERCHANT_CODE)
    cainiao_counts = Counter(df.loc[cainiao_mask, "派件网点简码"])
    sunyou_counts = Counter(df.loc[sunyou_mask, "派件网点简码"])
    aliexpress_count = int(cainiao_mask.sum())
    sunyou_count = int(sunyou_mask.sum())

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        template_file = find_latest_template_file()
        print(f"Using template file: {template_file}")
        wb = load_workbook(template_file, keep_links=False)

    write_data_source(wb, df)
    rebuild_non_auckland_pivot(wb, station_counts)
    rebuild_auckland_pivot(wb, route_counts)

    auckland_total = update_auckland_sheet(wb, route_counts)
    non_auckland_total = update_non_auckland_sheet(
        wb,
        station_counts,
        cainiao_counts,
        sunyou_counts,
        aliexpress_count,
        sunyou_count,
        auckland_total,
    )

    overlap = df[(df["派件网点简码"] != "AKL") & df["路由码"].isin(get_auckland_route_codes(wb))]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_FILE
    try:
        wb.save(output_file)
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = OUTPUT_FILE.with_name(f"{OUTPUT_FILE.stem}_{timestamp}{OUTPUT_FILE.suffix}")
        wb.save(output_file)
        print("Default updated report is open or locked; wrote a new file instead.")

    print(f"Source rows: {len(df)}")
    print(f"Auckland route total: {auckland_total}")
    print(f"Non-Auckland station total: {non_auckland_total}")
    print(f"Workbook total logic: {auckland_total + non_auckland_total}")
    print(f"Unique waybill total: {df['运单号'].nunique()}")
    merchant_counts = Counter(df[MERCHANT_COLUMN])
    print(
        "Merchant totals: "
        f"TEMU={merchant_counts.get(MERCHANT_CODES['TEMU'], 0)}, "
        f"Cainiao={merchant_counts.get(MERCHANT_CODES['CAINIAO'], 0)}, "
        f"Sunyou={merchant_counts.get(MERCHANT_CODES['SUNYOU'], 0)}"
    )
    if not overlap.empty:
        print("Potential double-count rows:")
        print(overlap[REQUIRED_COLUMNS].to_string(index=False))
    print(f"Done: {output_file}")


def get_auckland_route_codes(wb):
    ws = wb["奥克兰"]
    total_row = find_total_row(ws, column=1)
    return {
        clean_text(ws.cell(row, 1).value)
        for row in range(3, total_row)
        if clean_text(ws.cell(row, 1).value)
    }


if __name__ == "__main__":
    main()
