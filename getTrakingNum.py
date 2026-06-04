from pathlib import Path
from datetime import datetime
import subprocess

import pandas as pd


INPUT_FOLDER = Path("input")
OUTPUT_FILE = Path("output/query_list.txt")


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


all_numbers = []

excel_files = sorted(
    [
        *INPUT_FOLDER.glob("*.xls"),
        *INPUT_FOLDER.glob("*.xlsx"),
    ]
)

for file in excel_files:
    try:
        df = pd.read_excel(file, dtype=str)
    except Exception as exc:
        print(f"Error reading {file.name}: {exc}")
        continue

    tracking_col = find_column(df.columns, "trackingno")
    bill_col = find_column(df.columns, "billnumber")

    if tracking_col is None and bill_col is None:
        print(f"Skipped {file.name}: no TrackingNo or BillNumber column")
        continue

    file_rows = 0

    if tracking_col is not None:
        values = clean_series(df[tracking_col])
        all_numbers.extend(values)
        file_rows += len(values)

    if bill_col is not None:
        values = clean_series(df[bill_col])
        all_numbers.extend(values)
        file_rows += len(values)

    print(f"Found {file_rows} records in {file.name}")

result = pd.DataFrame({
    "TrakingNo&BillNumber": sorted(set(all_numbers))
})

copy_to_clipboard(result["TrakingNo&BillNumber"].tolist())

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

try:
    OUTPUT_FILE.write_text("\n".join(result["TrakingNo&BillNumber"]) + "\n", encoding="utf-8")
except PermissionError:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_FILE = OUTPUT_FILE.with_name(f"{OUTPUT_FILE.stem}_{timestamp}{OUTPUT_FILE.suffix}")
    OUTPUT_FILE.write_text("\n".join(result["TrakingNo&BillNumber"]) + "\n", encoding="utf-8")
    print("Default output file is open or locked; wrote a new file instead.")

print(f"Total unique records: {len(result)}")
print(f"Done: {OUTPUT_FILE}")
