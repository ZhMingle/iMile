from pathlib import Path
from datetime import datetime
import subprocess

import pandas as pd


INPUT_FOLDER = Path("input")
OUTPUT_FILE = Path("output/query_list.txt")
OUTPUT_COLUMN = "TrakingNo&BillNumber"
TRACKING_COLUMN_KEYWORDS = [
    "trackingno",
    "billnumber",
    "imile单号",
]


def find_column(columns, keyword):
    """Return the first column whose normalized name contains keyword."""
    keyword = keyword.lower()
    for column in columns:
        name = str(column).strip().lower()
        if keyword in name:
            return column
    return None


def clean_series(series):
    return (
        series.dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: s.ne("")]
    )


def copy_to_clipboard(values):
    text = "\r\n".join(values)
    try:
        subprocess.run(
            ["clip"],
            input=text,
            text=True,
            encoding="utf-8",
            check=True,
        )
        print(f"Copied {len(values)} records to clipboard.")
    except Exception as exc:
        print(f"Could not copy to clipboard: {exc}")


def main(excel_files=None):
    all_numbers = []
    if excel_files is None:
        excel_files = sorted(
            [
                *(file for file in INPUT_FOLDER.glob("*.xls") if not file.name.startswith("~$")),
                *(file for file in INPUT_FOLDER.glob("*.xlsx") if not file.name.startswith("~$")),
            ]
        )
    else:
        excel_files = [Path(file) for file in excel_files if not Path(file).name.startswith("~$")]

    if not excel_files:
        raise RuntimeError(f"No Excel files found in {INPUT_FOLDER.resolve()}")

    for file in excel_files:
        try:
            df = pd.read_excel(file, dtype=str)
        except Exception as exc:
            print(f"Error reading {file.name}: {exc}")
            continue

        matched_columns = [
            column
            for keyword in TRACKING_COLUMN_KEYWORDS
            if (column := find_column(df.columns, keyword)) is not None
        ]

        if not matched_columns:
            print(f"Skipped {file.name}: no TrackingNo, BillNumber, or IMILE单号 column")
            continue

        file_rows = 0
        for column in dict.fromkeys(matched_columns):
            values = clean_series(df[column])
            all_numbers.extend(values)
            file_rows += len(values)

        print(f"Found {file_rows} records in {file.name}")

    result = pd.DataFrame({OUTPUT_COLUMN: sorted(set(all_numbers))})
    copy_to_clipboard(result[OUTPUT_COLUMN].tolist())

    output_file = OUTPUT_FILE
    output_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_file.write_text("\n".join(result[OUTPUT_COLUMN]) + "\n", encoding="utf-8")
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_file.with_name(f"{output_file.stem}_{timestamp}{output_file.suffix}")
        output_file.write_text("\n".join(result[OUTPUT_COLUMN]) + "\n", encoding="utf-8")
        print("Default output file is open or locked; wrote a new file instead.")

    print(f"Total unique records: {len(result)}")
    print(f"Done: {output_file}")
    return output_file


if __name__ == "__main__":
    main()
