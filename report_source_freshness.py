from datetime import date, datetime
from pathlib import Path


def center_waybill_file_freshness_warning(source_file, current_date=None):
    source_file = Path(source_file)
    modified_at = datetime.fromtimestamp(source_file.stat().st_mtime)
    current_date = current_date or date.today()
    age_days = (current_date - modified_at.date()).days
    if age_days == 0:
        return None

    if age_days == 1:
        relative_date = "昨天"
    elif age_days > 1:
        relative_date = f"{age_days} 天前"
    else:
        relative_date = "未来日期"

    return (
        f"中心运单查询文件的最后修改时间是{relative_date}，可能还没有更新。\n\n"
        f"文件：{source_file.name}\n"
        f"最后修改：{modified_at:%Y-%m-%d %H:%M}\n"
        f"今天：{current_date:%Y-%m-%d}"
    )
