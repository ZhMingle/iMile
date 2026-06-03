from datetime import datetime
from pathlib import Path
import re

import pandas as pd
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont


REPORT_FILES = sorted(
    [
        path
        for path in Path(".").glob("06-03*.xlsx")
        if not path.name.startswith("~$")
    ],
    key=lambda path: path.stat().st_mtime,
)
UPDATED_REPORT_FILES = sorted(
    [
        path
        for path in Path("output").glob("05-26版本_自动更新*.xlsx")
        if not path.name.startswith("~$")
    ],
    key=lambda path: path.stat().st_mtime,
)
REPORT_FILE = REPORT_FILES[-1] if REPORT_FILES else (UPDATED_REPORT_FILES[-1] if UPDATED_REPORT_FILES else Path("05-26版本.xlsx"))
OUTPUT_DIR = Path("output")
SUPPLIER_DIR = OUTPUT_DIR / "supplier"
PROVINCE_DIR = OUTPUT_DIR / "province"
IMAGE_DIR = OUTPUT_DIR / "images"
SCALE = 2
today = datetime.now()
REPORT_DATE = f"{today.month}月{today.day:02d}日"

BLUE = "#8EAADB"
LIGHT_BLUE = "#BDD7EE"
YELLOW = "#FFF200"
TOTAL_BLUE = "#DDEBF7"
WHITE = "#FFFFFF"
BLACK = "#000000"


def load_font(size, bold=False):
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf" if bold else "C:/Windows/Fonts/simsun.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size * SCALE)
    return ImageFont.load_default()


FONT_TITLE = load_font(28, bold=True)
FONT_HEADER = load_font(20, bold=True)
FONT_BODY = load_font(18)
FONT_BODY_BOLD = load_font(18, bold=True)
FONT_TOTAL_NUMBER = load_font(24, bold=True)


def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def clean_number(value):
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0
    if float(number).is_integer():
        return int(number)
    return round(float(number), 2)


def parse_total_breakdown(value, province_count):
    text = clean_text(value)
    numbers = [clean_number(match) for match in re.findall(r"-?\d+(?:\.\d+)?", text)]
    if len(numbers) >= 3:
        return numbers[0], numbers[1], numbers[2]
    if len(numbers) == 1:
        return numbers[0], numbers[0] - province_count, province_count
    return 0, 0, province_count


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def text_size(draw, text, font):
    text = format_display(text)
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def format_display(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def draw_centered_text(draw, box, text, font, fill=BLACK):
    text = format_display(text)
    x1, y1, x2, y2 = [value * SCALE for value in box]
    width, height = text_size(draw, text, font)
    draw.text((x1 + (x2 - x1 - width) / 2, y1 + (y2 - y1 - height) / 2 - 1), text, font=font, fill=fill)


def draw_left_text(draw, box, text, font, fill=BLACK, padding=8):
    text = format_display(text)
    x1, y1, x2, y2 = [value * SCALE for value in box]
    _, height = text_size(draw, text, font)
    draw.text((x1 + padding * SCALE, y1 + (y2 - y1 - height) / 2 - 1), text, font=font, fill=fill)


def rect(draw, coords, **kwargs):
    draw.rectangle([value * SCALE for value in coords], **kwargs)


def render_table_image(path, title, headers, rows, widths, title_fill=BLUE, header_fill=LIGHT_BLUE):
    row_h = 36
    title_h = 58
    header_h = 64
    margin = 0
    width = sum(widths) + margin * 2
    height = title_h + header_h + row_h * len(rows) + margin * 2

    image = Image.new("RGB", (width * SCALE, height * SCALE), WHITE)
    draw = ImageDraw.Draw(image)

    y = margin
    rect(draw, [margin, y, width - margin - 1, y + title_h], fill=title_fill, outline=BLACK, width=SCALE)
    draw_centered_text(draw, (margin, y, width - margin, y + title_h), title, FONT_TITLE)
    y += title_h

    x = margin
    for header, col_w in zip(headers, widths):
        rect(draw, [x, y, x + col_w, y + header_h], fill=header_fill, outline=BLACK, width=SCALE)
        draw_centered_text(draw, (x, y, x + col_w, y + header_h), header, FONT_HEADER)
        x += col_w
    y += header_h

    for row in rows:
        is_total = clean_text(row[0]) in {"总计", "Total"}
        x = margin
        for idx, (value, col_w) in enumerate(zip(row, widths)):
            fill = TOTAL_BLUE if is_total else WHITE
            rect(draw, [x, y, x + col_w, y + row_h], fill=fill, outline=BLACK, width=SCALE)
            font = FONT_BODY_BOLD if is_total else FONT_BODY
            if idx == 0:
                draw_centered_text(draw, (x, y, x + col_w, y + row_h), value, font)
            else:
                draw_centered_text(draw, (x, y, x + col_w, y + row_h), value, font)
            x += col_w
        y += row_h

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def render_supplier_image(path, supplier, group):
    rows = [
        [row.route_code, row.quantity, supplier]
        for row in group.itertuples(index=False)
    ]
    rows.append(["总计", int(group["quantity"].sum()), supplier])
    render_table_image(
        path=path,
        title=f"{REPORT_DATE}奥克兰分单 - {supplier}",
        headers=["路由码\nroute code", "到件货量（预估）\nVolume of goods", "供应商\nsupplier"],
        rows=rows,
        widths=[170, 260, 260],
    )


def render_route_image(path, title, detail):
    rows = [[row.route_code, row.quantity] for row in detail.itertuples(index=False)]
    rows.append(["总计", int(detail["quantity"].sum())])
    render_table_image(
        path=path,
        title=title,
        headers=["Route Code", "Quantity"],
        rows=rows,
        widths=[170, 170],
        title_fill=YELLOW,
        header_fill=WHITE,
    )


def render_side_by_side_route_image(path, tables):
    title_h = 42
    row_h = 28
    gap = 96
    table_w = 340
    widths = [170, 170]
    max_rows = max(len(detail) + 1 for _, detail in tables)
    height = title_h + row_h * max_rows
    width = table_w * len(tables) + gap * (len(tables) - 1)

    image = Image.new("RGB", (width * SCALE, height * SCALE), WHITE)
    draw = ImageDraw.Draw(image)

    for table_index, (title, detail) in enumerate(tables):
        x0 = table_index * (table_w + gap)
        rect(draw, [x0, 0, x0 + table_w, title_h], fill=YELLOW, outline=BLACK, width=SCALE)
        draw_centered_text(draw, (x0, 0, x0 + table_w, title_h), title, FONT_HEADER)

        y = title_h
        rows = [[row.route_code, row.quantity] for row in detail.itertuples(index=False)]
        rows.append(["总计", int(detail["quantity"].sum())])

        for route_code, quantity in rows:
            is_total = route_code == "总计"
            fill = TOTAL_BLUE if is_total else WHITE
            rect(draw, [x0, y, x0 + widths[0], y + row_h], fill=fill if is_total else WHITE, outline=BLACK, width=SCALE)
            rect(draw, [x0 + widths[0], y, x0 + table_w, y + row_h], fill=fill, outline=BLACK, width=SCALE)
            font = FONT_BODY_BOLD if is_total else FONT_BODY
            draw_centered_text(draw, (x0, y, x0 + widths[0], y + row_h), route_code, font)
            draw_centered_text(draw, (x0 + widths[0], y, x0 + table_w, y + row_h), quantity, font)
            y += row_h

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def render_non_auckland_overview(path, overview, board_3l, board_5l, aliexpress_count, total_count, auckland_count, province_count):
    cell_h = 36
    title_h = 60
    header_h = 48
    gap = 28
    main_widths = [210, 210, 360]
    side_widths = [100, 190]
    width = sum(main_widths) + gap + sum(side_widths)
    height = 840
    image = Image.new("RGB", (width * SCALE, height * SCALE), WHITE)
    draw = ImageDraw.Draw(image)

    x0, y0 = 0, 0
    main_w = sum(main_widths)
    rect(draw, [x0, y0, x0 + main_w, y0 + title_h], fill=BLUE, outline=BLACK, width=SCALE)
    draw_centered_text(draw, (x0, y0, x0 + main_w, y0 + title_h), f"{REPORT_DATE}非奥克兰到件货量", FONT_TITLE)
    y = y0 + title_h
    x = x0
    for header, col_w in zip(["派件网点", "到件货量", "外省菜鸟到货量"], main_widths):
        rect(draw, [x, y, x + col_w, y + header_h], fill=LIGHT_BLUE, outline=BLACK, width=SCALE)
        draw_centered_text(draw, (x, y, x + col_w, y + header_h), header, FONT_HEADER)
        x += col_w
    y += header_h

    for row in overview.itertuples(index=False):
        values = [row.station, row.arrival_volume, row.cainiao_volume]
        is_total = row.station == "总计"
        x = x0
        for value, col_w in zip(values, main_widths):
            rect(draw, [x, y, x + col_w, y + cell_h], fill=TOTAL_BLUE if is_total else WHITE, outline=BLACK, width=SCALE)
            draw_centered_text(draw, (x, y, x + col_w, y + cell_h), value, FONT_BODY_BOLD if is_total else FONT_BODY)
            x += col_w
        y += cell_h

    y += 28
    total_value_h = 52
    rect(draw, [x0, y, x0 + main_widths[0], y + header_h], fill=LIGHT_BLUE, outline=BLACK, width=SCALE)
    draw_centered_text(draw, (x0, y, x0 + main_widths[0], y + header_h), "Aliexpress 单量", FONT_HEADER)
    rect(draw, [x0, y + header_h, x0 + main_widths[0], y + header_h + cell_h], fill=WHITE, outline=BLACK, width=SCALE)
    draw_centered_text(draw, (x0, y + header_h, x0 + main_widths[0], y + header_h + cell_h), aliexpress_count, FONT_BODY)

    total_x = x0 + main_widths[0] + main_widths[1]
    total_width = main_widths[2]
    total_display = f"{total_count}（{auckland_count} + {province_count}）"
    rect(draw, [total_x, y, total_x + total_width, y + header_h], fill="#FFC000", outline=BLACK, width=SCALE)
    draw_centered_text(draw, (total_x, y, total_x + total_width, y + header_h), "当天总量（奥克兰 + 外省）", FONT_HEADER)
    rect(draw, [total_x, y + header_h, total_x + total_width, y + header_h + total_value_h], fill="#FFC000", outline=BLACK, width=SCALE)
    draw_centered_text(draw, (total_x, y + header_h, total_x + total_width, y + header_h + total_value_h), total_display, FONT_TOTAL_NUMBER)

    def draw_board_table(x, y, title, data):
        rect(draw, [x, y, x + side_widths[0], y + header_h], fill=WHITE, outline=BLACK, width=SCALE)
        draw_centered_text(draw, (x, y, x + side_widths[0], y + header_h), data.iloc[0]["base"], FONT_HEADER)
        rect(draw, [x + side_widths[0], y, x + sum(side_widths), y + header_h], fill=WHITE, outline=BLACK, width=SCALE)
        draw_centered_text(draw, (x + side_widths[0], y, x + sum(side_widths), y + header_h), title, FONT_HEADER)
        y += header_h
        for row in data.itertuples(index=False):
            rect(draw, [x, y, x + side_widths[0], y + cell_h], fill=WHITE, outline=BLACK, width=SCALE)
            draw_left_text(draw, (x, y, x + side_widths[0], y + cell_h), row.station, FONT_BODY, padding=6)
            rect(draw, [x + side_widths[0], y, x + sum(side_widths), y + cell_h], fill=WHITE, outline=BLACK, width=SCALE)
            draw_centered_text(draw, (x + side_widths[0], y, x + sum(side_widths), y + cell_h), row.boards, FONT_BODY_BOLD if row.station == "总计" else FONT_BODY)
            y += cell_h

    side_x = main_w + gap
    board_3l_img = board_3l.copy()
    board_3l_img["base"] = 135
    draw_board_table(side_x, 60, "3L预测板数", board_3l_img)

    board_5l_img = board_5l.copy()
    board_5l_img["base"] = 350
    draw_board_table(side_x, 460, "5L预测板数", board_5l_img)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def build_supplier_messages():
    df = pd.read_excel(REPORT_FILE, sheet_name="奥克兰", header=None, dtype=str).fillna("")
    rows = df.iloc[2:101, [0, 2, 6]].copy()
    rows.columns = ["route_code", "quantity", "supplier"]
    rows["route_code"] = rows["route_code"].map(clean_text)
    rows["supplier"] = rows["supplier"].map(clean_text)
    rows["quantity"] = rows["quantity"].map(clean_number)
    rows = rows[(rows["route_code"] != "") & (rows["supplier"] != "")]

    summary = []

    for supplier, group in rows.groupby("supplier", sort=True):
        total = int(group["quantity"].sum())

        lines = [f"{REPORT_DATE}奥克兰分单 - {supplier}", "", "Route Code | Quantity"]
        lines.extend(f"{row.route_code} | {row.quantity}" for row in group.itertuples(index=False))
        lines.extend(["", f"总计 | {total}"])

        safe_name = supplier.replace("/", "_").replace("\\", "_").replace(":", "_")
        write_text(SUPPLIER_DIR / f"{safe_name}.txt", "\n".join(lines))

        group.to_csv(SUPPLIER_DIR / f"{safe_name}.csv", index=False, encoding="utf-8-sig")
        render_supplier_image(IMAGE_DIR / "supplier" / f"{safe_name}.png", supplier, group)
        summary.append({"supplier": supplier, "routes": len(group), "total": total})

    return pd.DataFrame(summary)


def build_non_auckland_messages():
    df = pd.read_excel(REPORT_FILE, sheet_name="非奥克兰", header=None, dtype=str).fillna("")

    overview = df.iloc[2:11, [0, 2, 5]].copy()
    overview.columns = ["station", "arrival_volume", "cainiao_volume"]
    overview["station"] = overview["station"].map(clean_text)
    overview["arrival_volume"] = overview["arrival_volume"].map(clean_number)
    overview["cainiao_volume"] = overview["cainiao_volume"].map(clean_number)

    board_3l = df.iloc[2:10, [7, 8]].copy()
    board_3l.columns = ["station", "boards"]
    board_3l["station"] = board_3l["station"].map(clean_text)
    board_3l["boards"] = board_3l["boards"].map(clean_number)

    board_5l = df.iloc[13:21, [7, 8]].copy()
    board_5l.columns = ["station", "boards"]
    board_5l["station"] = board_5l["station"].map(clean_text)
    board_5l["boards"] = board_5l["boards"].map(clean_number)

    aliexpress_count = clean_number(df.iloc[13, 0])
    province_total = overview.loc[overview["station"].eq("总计"), "arrival_volume"]
    province_count = clean_number(province_total.iloc[0]) if not province_total.empty else 0
    total_count, auckland_count, province_count = parse_total_breakdown(df.iloc[13, 5], province_count)
    if not total_count:
        total_count = clean_number(df.iloc[13, 3]) or clean_number(df.iloc[13, 5])
        auckland_count = clean_number(df.iloc[13, 4]) or total_count - province_count

    lines = [
        f"{REPORT_DATE}非奥克兰到件货量",
        "",
        "派件网点 | 到件货量 | 外省菜鸟到货量",
    ]
    lines.extend(
        f"{row.station} | {row.arrival_volume} | {row.cainiao_volume}"
        for row in overview.itertuples(index=False)
        if row.station
    )
    lines.extend(
        [
            "",
            f"Aliexpress 单量 | {aliexpress_count}",
            f"当天总量（奥克兰 + 外省） | {total_count}（{auckland_count} + {province_count}）",
            "",
            "3L预测板数",
        ]
    )
    lines.extend(
        f"{row.station} | {row.boards}"
        for row in board_3l.itertuples(index=False)
        if row.station
    )
    lines.extend(["", "5L预测板数"])
    lines.extend(
        f"{row.station} | {row.boards}"
        for row in board_5l.itertuples(index=False)
        if row.station
    )

    write_text(PROVINCE_DIR / "非奥克兰总览.txt", "\n".join(lines))
    overview.to_csv(PROVINCE_DIR / "非奥克兰到件货量.csv", index=False, encoding="utf-8-sig")
    board_3l.to_csv(PROVINCE_DIR / "3L预测板数.csv", index=False, encoding="utf-8-sig")
    board_5l.to_csv(PROVINCE_DIR / "5L预测板数.csv", index=False, encoding="utf-8-sig")
    render_non_auckland_overview(
        IMAGE_DIR / "province" / "非奥克兰总览.png",
        overview,
        board_3l,
        board_5l,
        aliexpress_count,
        total_count,
        auckland_count,
        province_count,
    )


def build_route_detail_messages():
    wb = load_workbook(REPORT_FILE, data_only=True, read_only=True)
    ws = wb["奥克兰透视"]

    ranges = {
        "WGR": (8, 9, 6, 7),
        "HMT": (9, 23, 10, 11),
        "RTR": (30, 31, 7, 8),
        "TRG": (29, 34, 10, 11),
        "NPL_HST": (40, 47, 10, 11),
        "WLT": (9, 19, 13, 14),
    }

    details_by_name = {}

    for name, (start, end, route_col, qty_col) in ranges.items():
        rows = []
        for row in range(start, end + 1):
            route_code = clean_text(ws.cell(row, route_col).value)
            quantity = clean_number(ws.cell(row, qty_col).value)
            if route_code and route_code not in {"Route Code", "总计"}:
                rows.append({"route_code": route_code, "quantity": quantity})

        detail = pd.DataFrame(rows, columns=["route_code", "quantity"])
        details_by_name[name] = detail

        total = int(detail["quantity"].sum())
        lines = [f"{REPORT_DATE}{name}各线路预测", "", "Route Code | Quantity"]
        lines.extend(f"{row.route_code} | {row.quantity}" for row in detail.itertuples(index=False))
        lines.extend(["", f"总计 | {total}"])

        write_text(PROVINCE_DIR / f"{name}各线路预测.txt", "\n".join(lines))
        detail.to_csv(PROVINCE_DIR / f"{name}各线路预测.csv", index=False, encoding="utf-8-sig")
        render_route_image(IMAGE_DIR / "province" / f"{name}各线路预测.png", f"{REPORT_DATE}{name}各线路预测", detail)

    render_side_by_side_route_image(
        IMAGE_DIR / "province" / "RTR_TRG各线路预测.png",
        [
            (f"{REPORT_DATE}RTR各线路预测", details_by_name["RTR"]),
            (f"{REPORT_DATE}TRG各线路预测", details_by_name["TRG"]),
        ],
    )


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    supplier_summary = build_supplier_messages()
    build_non_auckland_messages()
    build_route_detail_messages()

    supplier_summary.to_csv(OUTPUT_DIR / "供应商汇总.csv", index=False, encoding="utf-8-sig")

    print(f"Generated supplier messages: {len(supplier_summary)}")
    print(f"Done: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
