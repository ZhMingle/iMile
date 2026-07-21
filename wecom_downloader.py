import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path
import re
import shutil
import sys
import time


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "wecom_download_config.json"
EXAMPLE_CONFIG_PATH = APP_DIR / "wecom_download_config.example.json"
_OCR_ENGINE = None


def _load_config(config_path=CONFIG_PATH):
    config_path = Path(config_path)
    if not config_path.exists():
        if EXAMPLE_CONFIG_PATH.exists():
            shutil.copy2(EXAMPLE_CONFIG_PATH, config_path)
        raise RuntimeError(
            "已创建 wecom_download_config.json。请先填写企业微信 TEMU 会话名称，再重新开始。"
        )
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    chat_name = str(config.get("chat_name", "")).strip()
    if not chat_name or chat_name == "TEMU 文件群":
        raise RuntimeError("请在 wecom_download_config.json 中填写真实的 TEMU 会话名称。")
    archive_dir = Path(os.path.expandvars(str(config.get("archive_dir", "input/TEMU")))).expanduser()
    if not archive_dir.is_absolute():
        archive_dir = APP_DIR / archive_dir
    return config, chat_name, archive_dir


def _find_wecom_window():
    try:
        import win32gui
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("缺少 Windows 自动化组件 pywinauto/pywin32，请重新构建或安装 requirements.txt。") from exc

    candidates = []

    def collect(handle, _):
        try:
            title = win32gui.GetWindowText(handle).strip()
            class_name = win32gui.GetClassName(handle)
            if not win32gui.IsWindowVisible(handle):
                return
            if class_name == "WeWorkWindow" or re.search(r"企业微信|WeCom", title, re.IGNORECASE):
                left, top, right, bottom = win32gui.GetWindowRect(handle)
                candidates.append(((right - left) * (bottom - top), handle))
        except Exception:
            return

    win32gui.EnumWindows(collect, None)
    if not candidates:
        raise RuntimeError("没有找到企业微信窗口。请先登录并打开企业微信桌面端。")
    handle = max(candidates)[1]
    return Desktop(backend="win32").window(handle=handle)


def _ocr_items(image):
    global _OCR_ENGINE
    first_load = _OCR_ENGINE is None
    if first_load:
        print("正在加载 RapidOCR 组件…")
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError("缺少消息识别组件 RapidOCR，请重新构建或安装 requirements.txt。") from exc

    if _OCR_ENGINE is None:
        print("正在初始化 OCR 引擎，首次运行可能需要几秒…")
        _OCR_ENGINE = RapidOCR()
        print("OCR 引擎初始化完成。")
    if first_load:
        print(f"正在识别企业微信截图（{image.width}x{image.height}）…")
    result = _OCR_ENGINE(image)
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or texts is None or scores is None:
        return []
    if first_load:
        print(f"企业微信截图识别完成：{len(texts)} 个文本区域。")
    return [
        {"box": box, "text": str(text).strip(), "score": float(score)}
        for box, text, score in zip(boxes, texts, scores)
    ]


def _normalize_text(text):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text).lower())


def _chat_name_visible(items, chat_name):
    expected = _normalize_text(chat_name)
    if not expected:
        return False
    token = expected[: min(8, len(expected))]
    return any(token in _normalize_text(item["text"]) for item in items)


def _login_state(items):
    texts = [_normalize_text(item["text"]) for item in items if item.get("text")]
    combined = " ".join(texts)
    logged_out_markers = (
        "扫码登录",
        "手机号登录",
        "登录企业微信",
        "使用微信扫码",
        "切换账号",
        "注册企业",
    )
    if any(marker in combined for marker in logged_out_markers):
        return "logged_out"

    logged_in_markers = ("消息", "邮件", "文档", "待办", "工作台", "通讯录")
    marker_count = sum(any(marker in text for text in texts) for marker in logged_in_markers)
    if marker_count >= 2:
        return "logged_in"
    if "登录" in combined and "注册" in combined:
        return "logged_out"
    return "unknown"


def _ensure_wecom_logged_in(window):
    print("正在准备企业微信窗口…")
    window.restore()
    window.maximize()
    window.set_focus()
    time.sleep(0.8)
    print("正在截取企业微信当前画面…")
    image = window.capture_as_image()
    print("企业微信截图完成，准备识别登录状态和群消息。")
    items = _ocr_items(image)
    state = _login_state(items)
    if state == "logged_out":
        raise RuntimeError("企业微信尚未登录。请先完成登录并进入消息页面，然后重新读取 TEMU 群消息。")
    if state == "unknown":
        raise RuntimeError("无法确认企业微信登录状态。请打开企业微信消息页面并确认已登录后重试。")
    return image, items


def _item_center(item):
    box = item.get("box")
    if box is None or len(box) == 0:
        return 0.0, 0.0
    return (
        sum(float(point[0]) for point in box) / len(box),
        sum(float(point[1]) for point in box) / len(box),
    )


def _item_bounds(item):
    box = item.get("box")
    if box is None or len(box) == 0:
        return 0.0, 0.0, 0.0, 0.0
    xs = [float(point[0]) for point in box]
    ys = [float(point[1]) for point in box]
    return min(xs), min(ys), max(xs), max(ys)


def _header_date_from_text(text, target_date, header_like):
    if not header_like:
        return None
    value = str(text or "").strip().lower()
    if "今天" in value or "today" in value:
        return target_date
    if "昨天" in value or "yesterday" in value:
        return target_date - timedelta(days=1)

    match = re.search(r"(?<!\d)(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?!\d)", value)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    match = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", value)
    if match:
        try:
            return date(target_date.year, int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None

    match = re.search(
        r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?(?!\d)",
        value,
    )
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        year = int(match.group(3) or target_date.year)
        month, day = (second, first) if first > 12 >= second else (first, second)
        try:
            return date(year, month, day)
        except ValueError:
            return None

    if re.search(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)", value):
        return target_date
    return None


def _standalone_timestamp(text):
    value = str(text or "").strip().lower()
    pattern = (
        r"(?:今天|昨天|today|yesterday|"
        r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
        r"\d{1,2}月\d{1,2}日|"
        r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{4})?)"
        r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"
    )
    return re.fullmatch(pattern, value) is not None


def _message_items_for_date(items, target_date, min_score=0.70):
    eligible = [item for item in items if float(item.get("score", 1.0)) >= min_score]
    number_pattern = re.compile(r"(?<!\d)\d{3}[-\s]?\d{8}(?!\d)")
    anchors = [
        item
        for item in eligible
        if number_pattern.search(str(item.get("text", "")))
        or any(
            marker in _normalize_text(item.get("text", ""))
            for marker in ("temu", "cainiao", "菜鸟")
        )
    ]
    content_left = min((_item_center(item)[0] for item in anchors), default=0.0) - 280

    markers = []
    for item in eligible:
        center_x, center_y = _item_center(item)
        if center_x < content_left:
            continue
        same_line = " ".join(
            str(candidate.get("text", ""))
            for candidate in eligible
            if abs(_item_center(candidate)[1] - center_y) <= 22
            and _item_center(candidate)[0] >= content_left
        )
        sender_line = "微信" in same_line or "wechat" in same_line.lower()
        parsed = _header_date_from_text(
            item.get("text", ""),
            target_date,
            sender_line or _standalone_timestamp(item.get("text", "")),
        )
        if parsed is not None:
            markers.append((center_y, parsed))

    markers.sort(key=lambda value: value[0])
    deduplicated = []
    for marker in markers:
        if (
            deduplicated
            and abs(deduplicated[-1][0] - marker[0]) <= 8
            and deduplicated[-1][1] == marker[1]
        ):
            continue
        deduplicated.append(marker)

    selected = []
    for item in items:
        item_y = _item_center(item)[1]
        preceding = [marker for marker in deduplicated if marker[0] <= item_y + 25]
        if preceding and preceding[-1][1] == target_date:
            selected.append(item)
    return selected, {marker[1] for marker in deduplicated}


def _require_today_message_items(items, min_score=0.70):
    today = date.today()
    selected, visible_dates = _message_items_for_date(items, today, min_score)
    if today not in visible_dates:
        if visible_dates:
            dates = "、".join(sorted(value.strftime("%Y-%m-%d") for value in visible_dates))
            raise RuntimeError(
                f"当前画面识别到的数据消息日期为 {dates}，不是今天 {today:%Y-%m-%d}。"
                "请滚动到今天发送的完整数据消息后重试。"
            )
        raise RuntimeError(
            f"无法确认当前数据消息是今天 {today:%Y-%m-%d} 发送的。"
            "请让发送者、发送时间和完整数据消息同时显示在画面中后重试。"
        )
    print(f"已确认只处理今天 {today:%Y-%m-%d} 发送的群消息。")
    return selected


def _shipment_search_keys_from_items(items, image_size=None, min_score=0.70):
    ordered = sorted(items, key=lambda item: (_item_center(item)[1], _item_center(item)[0]))
    number_pattern = re.compile(r"(?<!\d)(\d{3})[-\s]?(\d{8})(?!\d)")
    search_keys = {"temu": [], "cainiao": []}
    section = None
    section_x = None

    for item in ordered:
        if float(item.get("score", 1.0)) < min_score:
            continue
        center_x, _ = _item_center(item)

        text = str(item.get("text", "")).strip()
        normalized = _normalize_text(text)
        if "temu" in normalized:
            section = "temu"
            section_x = center_x
        if "cainiao" in normalized or "菜鸟" in normalized:
            section = "cainiao"
            section_x = center_x
        if section is None:
            continue
        if section_x is not None and center_x < section_x - 140:
            continue

        for match in number_pattern.finditer(text):
            search_key = match.group(2)
            if search_key not in search_keys[section]:
                search_keys[section].append(search_key)
    return search_keys


def _temu_search_keys_from_items(items, image_size=None, min_score=0.70):
    return _shipment_search_keys_from_items(items, image_size, min_score)["temu"]


def _shunyou_search_keys_from_items(items, min_score=0.70):
    number_pattern = re.compile(r"(?<!\d)(\d{3})[-\s]?(\d{8})(?!\d)")
    search_keys = []
    for item in sorted(items, key=lambda value: (_item_center(value)[1], _item_center(value)[0])):
        if float(item.get("score", 1.0)) < min_score:
            continue
        for match in number_pattern.finditer(str(item.get("text", ""))):
            search_key = match.group(2)
            if search_key not in search_keys:
                search_keys.append(search_key)
    return search_keys


def _history_view_visible(items):
    texts = [_normalize_text(item.get("text", "")) for item in items]
    tab_markers = ("全部", "文件", "图片与视频", "链接", "小程序")
    filter_markers = ("发送人", "日期")
    tabs = sum(any(marker in text for text in texts) for marker in tab_markers)
    filters = sum(any(marker in text for text in texts) for marker in filter_markers)
    return tabs >= 3 and filters >= 1


def _history_search_point(items):
    candidates = [
        item
        for item in items
        if _normalize_text(item.get("text", "")) == "全部"
    ]
    if not candidates:
        return None
    tab = min(candidates, key=lambda item: _item_center(item)[1])
    center_x, center_y = _item_center(tab)
    return center_x + 150, center_y + 76


def _file_result_click_point(items, search_key, extensions):
    if not re.fullmatch(r"\d{8}", search_key):
        return None
    extension_lines = [
        item
        for item in items
        if any(extension in str(item.get("text", "")).lower() for extension in extensions)
    ]
    candidates = []
    for item in items:
        text = str(item.get("text", ""))
        digits = re.sub(r"\D", "", text)
        if search_key not in digits:
            continue
        center_x, center_y = _item_center(item)
        nearby_extension = any(
            abs(_item_center(line)[1] - center_y) <= 85
            and abs(_item_center(line)[0] - center_x) <= 240
            for line in extension_lines
        )
        if any(extension in text.lower() for extension in extensions) or nearby_extension:
            candidates.append(item)
    if not candidates:
        return None
    return _item_center(min(candidates, key=lambda item: _item_center(item)[1]))


def _capture_visible_window(window):
    from PIL import ImageGrab

    rectangle = window.rectangle()
    bbox = (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom)
    return ImageGrab.grab(bbox=bbox, all_screens=True), rectangle


def _history_tooltip_visible(items):
    return any("聊天记录" in _normalize_text(item.get("text", "")) for item in items)


def _locate_history_button(window, image, items, chat_name):
    from PIL import ImageGrab
    from pywinauto import mouse

    expected = _normalize_text(chat_name)
    title_items = [
        item
        for item in items
        if expected and expected[: min(8, len(expected))] in _normalize_text(item.get("text", ""))
    ]
    if not title_items:
        return None
    title_item = min(title_items, key=lambda item: _item_center(item)[1])
    left, top, right, bottom = _item_bounds(title_item)
    scale = max(0.8, min(1.8, (bottom - top) / 24 if bottom > top else 1.0))
    pane_left = max(image.width * 0.25, left - 24 * scale)
    predicted_x = pane_left + 486 * scale
    predicted_y = image.height - 136 * scale
    rectangle = window.rectangle()

    x_offsets = (0, -24, 24, -48, 48, -72, 72, -96, 96, -144, 144)
    y_offsets = (0, -24, 24, -48, 48, -72)
    for y_offset in y_offsets:
        for x_offset in x_offsets:
            local_x = int(predicted_x + x_offset * scale)
            local_y = int(predicted_y + y_offset * scale)
            if not (0 < local_x < image.width and 0 < local_y < image.height):
                continue
            screen_x = rectangle.left + local_x
            screen_y = rectangle.top + local_y
            mouse.move(coords=(screen_x, screen_y))
            time.sleep(0.38)
            tooltip_image = ImageGrab.grab(
                bbox=(
                    max(0, screen_x - int(180 * scale)),
                    max(0, screen_y - int(120 * scale)),
                    screen_x + int(180 * scale),
                    screen_y + int(70 * scale),
                ),
                all_screens=True,
            )
            if _history_tooltip_visible(_ocr_items(tooltip_image)):
                return screen_x, screen_y
    # WeCom 5.x sometimes suppresses tooltips. This point is the fixed last icon
    # in the compose toolbar; no keyboard input is allowed until the next OCR
    # pass confirms that the chat-history page actually opened.
    return rectangle.left + int(predicted_x), rectangle.top + int(predicted_y)


def _open_history_view(window, chat_name, image=None, items=None):
    from pywinauto import mouse

    if image is None or items is None:
        image, _ = _capture_visible_window(window)
        items = _ocr_items(image)
    if _history_view_visible(items):
        return image, items
    if not _chat_name_visible(items, chat_name):
        raise RuntimeError(f"自动下载已停止：当前窗口无法确认是群“{chat_name}”。")

    point = _locate_history_button(window, image, items, chat_name)
    if point is None:
        raise RuntimeError(
            "没有安全识别到“聊天记录”按钮，因此未执行任何点击。"
            "请确认聊天输入区工具栏可见后重试。"
        )
    mouse.click(coords=point)
    time.sleep(1.4)
    history_image, _ = _capture_visible_window(window)
    history_items = _ocr_items(history_image)
    if not _history_view_visible(history_items):
        raise RuntimeError("点击后未识别到聊天记录页面，自动下载已停止。")
    return history_image, history_items


def _search_history(window, items, search_key):
    from pywinauto import mouse
    from pywinauto.keyboard import send_keys

    if not re.fullmatch(r"\d{8}", search_key):
        raise RuntimeError(f"拒绝搜索非 8 位数字内容：{search_key}")
    if not _history_view_visible(items):
        raise RuntimeError("搜索前未确认聊天记录页面，已停止输入。")
    point = _history_search_point(items)
    if point is None:
        raise RuntimeError("没有识别到聊天记录搜索框，已停止输入。")

    rectangle = window.rectangle()
    window.set_focus()
    mouse.click(coords=(rectangle.left + int(point[0]), rectangle.top + int(point[1])))
    time.sleep(0.25)
    send_keys("^a{BACKSPACE}")
    send_keys(search_key)
    time.sleep(1.3)

    result_image, _ = _capture_visible_window(window)
    result_items = _ocr_items(result_image)
    if not _history_view_visible(result_items):
        raise RuntimeError("输入搜索号后聊天记录页面校验失败，已停止自动下载。")
    if not any(
        search_key in re.sub(r"\D", "", str(item.get("text", "")))
        for item in result_items
    ):
        raise RuntimeError(f"聊天记录页面没有显示搜索号 {search_key}，已停止附件点击。")
    return result_image, result_items


def _wait_for_cached_key(cache_roots, search_key, extensions, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = _cached_files_for_keys(cache_roots, [search_key], extensions)
        if search_key in matches:
            path = matches[search_key]
            try:
                first_size = path.stat().st_size
                time.sleep(0.8)
                if first_size > 0 and path.stat().st_size == first_size:
                    return path
            except OSError:
                pass
        time.sleep(0.7)
    return None


def _download_missing_from_history(
    window,
    chat_name,
    missing_keys,
    cache_roots,
    extensions,
    timeout,
    initial_image,
    initial_items,
):
    from pywinauto import mouse

    downloaded = {}
    failures = []
    image, items = _open_history_view(window, chat_name, initial_image, initial_items)
    for search_key in missing_keys:
        if not _history_view_visible(items):
            image, items = _open_history_view(window, chat_name)
        print(f"正在聊天记录中搜索 TEMU 文件：{search_key}")
        image, items = _search_history(window, items, search_key)
        click_point = _file_result_click_point(items, search_key, extensions)
        if click_point is None:
            failures.append(search_key)
            print(f"未找到 {search_key} 对应的 Excel/CSV 文件卡片。")
            continue
        if not _history_view_visible(items):
            raise RuntimeError("点击附件前聊天记录页面校验失败，已停止自动下载。")

        rectangle = window.rectangle()
        mouse.click(
            coords=(rectangle.left + int(click_point[0]), rectangle.top + int(click_point[1]))
        )
        path = _wait_for_cached_key(cache_roots, search_key, extensions, timeout)
        if path is None:
            failures.append(search_key)
            print(f"已点击 {search_key} 的文件卡片，但等待下载超时。")
        else:
            downloaded[search_key] = path
            print(f"已下载并缓存：{path.name}")
        window.restore()
        window.set_focus()
        time.sleep(0.6)
        image, _ = _capture_visible_window(window)
        items = _ocr_items(image)
    return downloaded, failures


def _cache_roots(config):
    configured = str(config.get("wecom_cache_dir", "")).strip()
    base = Path(os.path.expandvars(configured)).expanduser() if configured else Path.home() / "Documents" / "WXWork"
    if not base.is_dir():
        return []
    if base.name.lower() == "file" and base.parent.name.lower() == "cache":
        return [base]
    direct = base / "Cache" / "File"
    if direct.is_dir():
        return [direct]
    return sorted(path for path in base.glob("*/Cache/File") if path.is_dir())


def _cached_files_for_keys(cache_roots, search_keys, extensions):
    matches = {}
    for root in cache_roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            for search_key in search_keys:
                if search_key not in path.stem:
                    continue
                current = matches.get(search_key)
                if current is None or path.stat().st_mtime_ns > current.stat().st_mtime_ns:
                    matches[search_key] = path.resolve()
    return matches


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(archive_root):
    path = Path(archive_root) / ".downloaded_files.json"
    if not path.exists():
        return path, {}
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path, {}


def _unique_destination(folder, name):
    destination = folder / name
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    counter = 2
    while True:
        candidate = folder / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _archive_cached_files(files_by_key, archive_root):
    archive_root = Path(archive_root)
    day_folder = archive_root / time.strftime("%Y-%m-%d")
    day_folder.mkdir(parents=True, exist_ok=True)
    manifest_path, manifest = _load_manifest(archive_root)
    archived = []
    duplicates = []

    for search_key, source in files_by_key.items():
        digest = _sha256(source)
        if digest in manifest:
            duplicates.append(source)
            continue
        destination = _unique_destination(day_folder, source.name)
        shutil.copy2(source, destination)
        manifest[digest] = {
            "search_key": search_key,
            "source": str(source),
            "archived": str(destination),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        archived.append(destination)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return archived, duplicates


def _archive_root(config, key, default):
    path = Path(os.path.expandvars(str(config.get(key, default)))).expanduser()
    return path if path.is_absolute() else APP_DIR / path


def _confirm_tracking_continuation(message, config):
    if not config.get("confirm_before_tracking", True) or sys.platform != "win32":
        return True
    import ctypes

    yes_no_question = (
        f"{message}\n\n"
        "请确认票数和单号是否正确。\n"
        "选择“是”继续生成查询单号；选择“否”保留已下载文件并暂停。"
    )
    result = ctypes.windll.user32.MessageBoxW(
        None,
        yes_no_question,
        "确认自动收件结果",
        0x00000004 | 0x00000020 | 0x00040000,
    )
    return result == 6


def _extract_tracking_and_download_center_query(summary, config):
    from getTrakingNum import main as extract_tracking

    query_output = extract_tracking()
    summary += f"\n已更新 {query_output.name}。"
    if not config.get("auto_download_center_query", True):
        return summary

    from imile_dc_downloader import download_center_waybill_query

    try:
        export_path = download_center_waybill_query(query_output, config)
    except RuntimeError as exc:
        raise RuntimeError(
            f"{summary}\n收件与查询单号已保留，但中心运单查询下载未完成：{exc}"
        ) from exc
    return f"{summary}\n中心运单查询已下载：{export_path.name}。"


def _read_shunyou_chat(config, chat_name, items):
    from lark_mail_downloader import download_shunyou_files

    print(f"识别到备用群“{chat_name}”，开始执行偶发顺友收件流程。")
    items = _require_today_message_items(
        items,
        float(config.get("ocr_min_confidence", 0.70)),
    )
    search_keys = _shunyou_search_keys_from_items(
        items,
        float(config.get("ocr_min_confidence", 0.70)),
    )
    if not search_keys:
        raise RuntimeError(
            "当前顺友群画面没有识别到主单号。请让包含 3位-8位 主单号的消息显示后重试。"
        )

    print(f"开始从 Lark 邮箱收取 {len(search_keys)} 个顺友附件。")
    files_by_key, missing = download_shunyou_files(search_keys, config)
    archive_root = _archive_root(config, "shunyou_archive_dir", "input/SHUNYOU")
    archived, duplicates = _archive_cached_files(files_by_key, archive_root)
    key_text = "、".join(search_keys)
    if missing:
        raise RuntimeError(
            f"顺友邮件收件未完整完成：当前群识别 {len(search_keys)} 票，"
            f"邮箱匹配 {len(files_by_key)} 票，新增归档 {len(archived)} 票；"
            f"仍缺少：{'、'.join(missing)}。识别单号：{key_text}"
        )

    summary = (
        f"顺友收件完成（{chat_name}）：当前群识别 {len(search_keys)} 票，"
        f"邮箱匹配 {len(files_by_key)} 票，"
        f"新增归档 {len(archived)} 票，跳过 {len(duplicates)} 个重复文件。\n"
        f"单号：{key_text}"
    )
    if config.get("auto_extract_tracking", True):
        if not _confirm_tracking_continuation(summary, config):
            return f"{summary}\n已按你的选择暂停，尚未生成查询单号。"
        summary = _extract_tracking_and_download_center_query(summary, config)
    return summary


def read_temu_chat(config_path=CONFIG_PATH):
    if sys.platform != "win32":
        raise RuntimeError("企业微信 TEMU 群消息读取只能在 Windows 电脑上运行。")
    print("正在读取自动收件配置…")
    config, chat_name, archive_root = _load_config(config_path)
    print("正在查找企业微信窗口…")
    window = _find_wecom_window()
    print("已找到企业微信窗口，正在确认登录状态。")
    image, items = _ensure_wecom_logged_in(window)
    if not _chat_name_visible(items, chat_name):
        shunyou_chat_name = str(config.get("shunyou_chat_name", "")).strip()
        if shunyou_chat_name and _chat_name_visible(items, shunyou_chat_name):
            return _read_shunyou_chat(config, shunyou_chat_name, items)
        raise RuntimeError(
            f"日常收件请手动打开主群“{chat_name}”"
            + (f"；仅有顺友货时打开备用群“{shunyou_chat_name}”" if shunyou_chat_name else "")
            + "，并让待收件的数据消息显示在画面中。"
            "程序不会自动切换群聊，也不会向群里发送消息。"
        )

    message_items = _require_today_message_items(
        items,
        float(config.get("ocr_min_confidence", 0.70)),
    )
    shipment_keys = _shipment_search_keys_from_items(
        message_items,
        image.size,
        float(config.get("ocr_min_confidence", 0.70)),
    )
    search_keys = shipment_keys["temu"]
    cainiao_keys = shipment_keys["cainiao"]
    if not search_keys:
        raise RuntimeError(
            "当前画面没有识别到 Temu: 区段中的单号。请把包含 Temu 数据的完整消息滚动到可见位置后重试。"
        )

    extensions = {
        str(extension).lower() if str(extension).startswith(".") else "." + str(extension).lower()
        for extension in config.get("allowed_extensions", [".xls", ".xlsx", ".csv"])
    }
    cache_roots = _cache_roots(config)
    if not cache_roots:
        raise RuntimeError(
            "没有找到企业微信本地文件缓存目录。请检查 wecom_cache_dir 配置和企业微信安装状态。"
        )
    files_by_key = _cached_files_for_keys(cache_roots, search_keys, extensions)
    missing = [search_key for search_key in search_keys if search_key not in files_by_key]
    auto_downloaded = 0
    if missing and config.get("auto_download_missing", True):
        print(f"本地缓存缺少 {len(missing)} 个文件，开始安全打开聊天记录自动下载。")
        downloaded, _ = _download_missing_from_history(
            window,
            chat_name,
            missing,
            cache_roots,
            extensions,
            max(10, int(config.get("download_timeout_seconds", 90))),
            image,
            items,
        )
        files_by_key.update(downloaded)
        auto_downloaded = len(downloaded)
        missing = [search_key for search_key in search_keys if search_key not in files_by_key]

    if not files_by_key:
        keys = "、".join(missing or search_keys)
        raise RuntimeError(f"聊天记录中未能自动下载这些 TEMU 文件：{keys}。")

    archived, duplicates = _archive_cached_files(files_by_key, archive_root)
    cainiao_files = {}
    cainiao_archived = []
    cainiao_duplicates = []
    cainiao_missing = []
    if cainiao_keys and config.get("auto_download_cainiao", True):
        from lark_mail_downloader import download_cainiao_files

        print(f"开始从 Lark 邮箱收取 {len(cainiao_keys)} 个 Cainiao 附件。")
        cainiao_files, cainiao_missing = download_cainiao_files(cainiao_keys, config)
        cainiao_archive_root = _archive_root(
            config,
            "cainiao_archive_dir",
            "input/CAINIAO",
        )
        cainiao_archived, cainiao_duplicates = _archive_cached_files(
            cainiao_files,
            cainiao_archive_root,
        )

    if missing:
        raise RuntimeError(
            f"TEMU 收件未完整完成：识别 {len(search_keys)} 个搜索号，共匹配 {len(files_by_key)} 个文件，"
            f"新增归档 {len(archived)} 个；仍缺少：{'、'.join(missing)}。"
        )
    if cainiao_missing:
        raise RuntimeError(
            f"Cainiao 邮件收件未完整完成：识别 {len(cainiao_keys)} 个搜索号，"
            f"共匹配 {len(cainiao_files)} 个附件，新增归档 {len(cainiao_archived)} 个；"
            f"仍缺少：{'、'.join(cainiao_missing)}。"
        )
    auto_message = f"，聊天记录自动下载 {auto_downloaded} 个" if auto_downloaded else ""
    cainiao_message = (
        f"；Cainiao 邮箱匹配 {len(cainiao_files)} 个附件，新增归档 {len(cainiao_archived)} 个，"
        f"跳过 {len(cainiao_duplicates)} 个重复文件"
        if cainiao_keys
        else ""
    )
    summary = (
        f"TEMU 收件完成：识别 {len(search_keys)} 个 8 位搜索号，共匹配 {len(files_by_key)} 个文件，"
        f"新增归档 {len(archived)} 个，跳过 {len(duplicates)} 个重复文件"
        f"{auto_message}{cainiao_message}。\n"
        f"TEMU 单号：{'、'.join(search_keys)}"
    )
    if cainiao_keys:
        summary += f"\nCainiao 单号：{'、'.join(cainiao_keys)}"
    if config.get("auto_extract_tracking", True):
        if not _confirm_tracking_continuation(summary, config):
            return f"{summary}\n已按你的选择暂停，尚未生成查询单号。"
        summary = _extract_tracking_and_download_center_query(summary, config)
    return summary


def download_temu_files(config_path=CONFIG_PATH):
    return read_temu_chat(config_path)


if __name__ == "__main__":
    print(read_temu_chat())
