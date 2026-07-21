import os
from pathlib import Path
import re
import time


def _normalize_text(text):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text).lower())


def _item_center(item):
    box = item.get("box")
    if box is None or len(box) == 0:
        return 0.0, 0.0
    return (
        sum(float(point[0]) for point in box) / len(box),
        sum(float(point[1]) for point in box) / len(box),
    )


def _screen_point(point, image_size, rectangle):
    """Map an OCR point from the captured image to the current screen rectangle."""
    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        raise ValueError("截图尺寸无效，无法计算点击位置。")
    window_width = rectangle.right - rectangle.left
    window_height = rectangle.bottom - rectangle.top
    return (
        rectangle.left + int(round(float(point[0]) * window_width / image_width)),
        rectangle.top + int(round(float(point[1]) * window_height / image_height)),
    )


def _ocr_items(image):
    from wecom_downloader import _ocr_items as recognize

    return recognize(image)


def _find_lark_window():
    try:
        import win32api
        import win32con
        import win32gui
        import win32process
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("缺少 Lark 邮箱自动化所需的 pywinauto/pywin32。") from exc

    candidates = []

    def collect(handle, _):
        try:
            if not win32gui.IsWindowVisible(handle):
                return
            title = win32gui.GetWindowText(handle).strip()
            class_name = win32gui.GetClassName(handle)
            is_lark = re.search(r"飞书|lark", title, re.IGNORECASE)
            if not is_lark:
                _, process_id = win32process.GetWindowThreadProcessId(handle)
                process = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                    False,
                    process_id,
                )
                try:
                    executable = win32process.GetModuleFileNameEx(process, 0)
                finally:
                    process.Close()
                is_lark = re.search(r"feishu|lark", executable, re.IGNORECASE)
            if not is_lark:
                return
            if class_name != "Chrome_WidgetWin_1":
                return
            left, top, right, bottom = win32gui.GetWindowRect(handle)
            area = max(0, right - left) * max(0, bottom - top)
            if area:
                candidates.append((area, handle))
        except Exception:
            return

    win32gui.EnumWindows(collect, None)
    if not candidates:
        raise RuntimeError("没有找到 Lark/飞书窗口。请先登录并打开桌面客户端。")
    return Desktop(backend="win32").window(handle=max(candidates)[1])


def _capture_visible_window(window):
    import ctypes
    from PIL import Image
    from PIL import ImageGrab

    rectangle = window.rectangle()
    width = rectangle.right - rectangle.left
    height = rectangle.bottom - rectangle.top
    try:
        import win32gui
        import win32ui

        window_dc = win32gui.GetWindowDC(window.handle)
        source_dc = win32ui.CreateDCFromHandle(window_dc)
        target_dc = source_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source_dc, width, height)
        target_dc.SelectObject(bitmap)
        rendered = ctypes.windll.user32.PrintWindow(
            window.handle,
            target_dc.GetSafeHdc(),
            2,
        )
        if not rendered:
            raise RuntimeError("PrintWindow failed")
        image = Image.frombuffer(
            "RGB",
            (width, height),
            bitmap.GetBitmapBits(True),
            "raw",
            "BGRX",
            0,
            1,
        ).copy()
        win32gui.DeleteObject(bitmap.GetHandle())
        target_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(window.handle, window_dc)
    except Exception:
        image = ImageGrab.grab(
            bbox=(rectangle.left, rectangle.top, rectangle.right, rectangle.bottom),
            all_screens=True,
        )
    return image, rectangle


def _capture_screen_window(window):
    from PIL import ImageGrab

    rectangle = window.rectangle()
    image = ImageGrab.grab(
        bbox=(rectangle.left, rectangle.top, rectangle.right, rectangle.bottom),
        all_screens=True,
    )
    return image, rectangle


def _mail_view_visible(items):
    texts = [_normalize_text(item.get("text", "")) for item in items]
    has_mail = any(text == "邮箱" or "邮箱" in text for text in texts)
    has_inbox = any("收件箱" in text for text in texts)
    has_search = any("搜索邮件" in text for text in texts)
    return has_mail and has_inbox and has_search


def _mail_search_results_visible(items, search_key):
    texts = [str(item.get("text", "")) for item in items]
    normalized = [_normalize_text(text) for text in texts]
    has_mail = any("邮箱" in text for text in normalized)
    has_results = any("搜索结果" in text for text in normalized)
    has_key = any(search_key in re.sub(r"\D", "", text) for text in texts)
    return has_mail and has_results and has_key


def _mail_results_page_visible(items):
    normalized = [_normalize_text(item.get("text", "")) for item in items]
    return any("邮箱" in text for text in normalized) and any(
        "搜索结果" in text for text in normalized
    )


def _mail_results_back_point(items, image_size):
    width, height = image_size
    candidates = [
        item
        for item in items
        if _normalize_text(item.get("text", "")) == "返回"
        and _item_center(item)[1] < height * 0.16
        and _item_center(item)[0] < width * 0.55
    ]
    if not candidates:
        return None
    return _item_center(min(candidates, key=lambda item: _item_center(item)[1]))


def _mail_search_point(items):
    candidates = [
        item
        for item in items
        if "搜索邮件" in _normalize_text(item.get("text", ""))
    ]
    if not candidates:
        return None
    return _item_center(min(candidates, key=lambda item: _item_center(item)[1]))


def _mail_navigation_point(items, image_size):
    width, _ = image_size
    candidates = [
        item
        for item in items
        if _normalize_text(item.get("text", "")) == "邮箱"
        and _item_center(item)[0] < width * 0.15
    ]
    if not candidates:
        return None
    return _item_center(min(candidates, key=lambda item: _item_center(item)[1]))


def _mail_result_click_point(items, search_key, image_size):
    if not re.fullmatch(r"\d{8}", search_key):
        return None
    width, height = image_size
    candidates = []
    for item in items:
        digits = re.sub(r"\D", "", str(item.get("text", "")))
        center_x, center_y = _item_center(item)
        if (
            search_key in digits
            and width * 0.24 < center_x < width * 0.50
            and center_y > height * 0.12
        ):
            candidates.append(item)
    if not candidates:
        return None
    return _item_center(min(candidates, key=lambda item: _item_center(item)[1]))


def _mail_detail_visible(items, search_key, image_size):
    width, _ = image_size
    return any(
        search_key in re.sub(r"\D", "", str(item.get("text", "")))
        and _item_center(item)[0] > width * 0.50
        for item in items
    )


def _open_mail_result(window, image, items, result_point, search_key):
    from pywinauto import mouse

    for _ in range(3):
        rectangle = window.rectangle()
        mouse.click(coords=_screen_point(result_point, image.size, rectangle))
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            time.sleep(0.6)
            detail_image, _ = _capture_visible_window(window)
            detail_items = _ocr_items(detail_image)
            if _mail_detail_visible(detail_items, search_key, detail_image.size):
                return detail_image, detail_items
        image = detail_image
        items = detail_items
        result_point = _mail_result_click_point(items, search_key, image.size)
        if result_point is None:
            break
    raise RuntimeError(f"搜索到 {search_key}，但未能打开对应邮件详情，已停止附件操作。")


def _attachment_click_point(
    items,
    extensions,
    image_size,
    search_key=None,
    name_markers=(),
):
    width, height = image_size
    normalized_markers = [
        _normalize_text(marker) for marker in name_markers if _normalize_text(marker)
    ]
    extension_items = [
        item
        for item in items
        if any(
            extension in str(item.get("text", "")).lower()
            for extension in extensions
        )
    ]
    candidates = []
    for item in items:
        text = str(item.get("text", "")).lower()
        center_x, center_y = _item_center(item)
        digits = re.sub(r"\D", "", text)
        extension_matches = any(extension in text for extension in extensions)
        truncated_excel_name = text.endswith(".x")
        nearby_extension = any(
            abs(_item_center(extension_item)[1] - center_y) <= height * 0.04
            and abs(_item_center(extension_item)[0] - center_x) <= width * 0.22
            for extension_item in extension_items
        )
        if normalized_markers:
            same_line_text = "".join(
                _normalize_text(other.get("text", ""))
                for other in sorted(items, key=lambda value: _item_center(value)[0])
                if _item_center(other)[0] > width * 0.43
                and abs(_item_center(other)[1] - center_y) <= height * 0.04
            )
            identity_matches = any(
                marker in same_line_text for marker in normalized_markers
            )
            file_matches = extension_matches or truncated_excel_name
        else:
            identity_matches = search_key is None or search_key in digits
            file_matches = extension_matches or truncated_excel_name or nearby_extension
        if (
            center_x > width * 0.43
            and identity_matches
            and file_matches
        ):
            candidates.append(item)
    if not candidates:
        return None
    return _item_center(max(candidates, key=lambda item: _item_center(item)[1]))


def _context_download_point(items, image_size, attachment_point):
    width, height = image_size
    normalized_items = [
        (item, _normalize_text(item.get("text", ""))) for item in items
    ]
    menu_markers = ("预览", "本地应用打开", "复制")
    menu_items = [
        item
        for item, text in normalized_items
        if any(marker in text for marker in menu_markers)
    ]
    if not menu_items:
        return None

    attachment_x, attachment_y = attachment_point
    max_x_distance = width * 0.30
    max_y_distance = height * 0.40
    candidates = []
    for item, text in normalized_items:
        center_x, center_y = _item_center(item)
        if not text.endswith("下载"):
            continue
        if center_x <= width * 0.43:
            continue
        if (
            abs(center_x - attachment_x) <= max_x_distance
            and abs(center_y - attachment_y) <= max_y_distance
        ):
            candidates.append(item)
    if not candidates:
        return None
    return _item_center(
        min(
            candidates,
            key=lambda item: (
                (_item_center(item)[0] - attachment_x) ** 2
                + (_item_center(item)[1] - attachment_y) ** 2
            ),
        )
    )


def _hover_scan_points(attachment_point, image_size):
    width, height = image_size
    attachment_x, attachment_y = attachment_point
    step = max(width * 0.012, 12)
    max_distance = width * 0.18
    points = []
    distance = 0.0
    while distance <= max_distance:
        offsets = (distance,) if distance == 0 else (distance, -distance)
        for offset in offsets:
            point_x = attachment_x + offset
            if width * 0.48 <= point_x <= width * 0.97:
                points.append((point_x, attachment_y))
        distance += step
    return points


def _hover_download_icon(window, attachment_point, image_size, rectangle):
    from PIL import ImageGrab
    from pywinauto import mouse

    window_width = rectangle.right - rectangle.left
    window_height = rectangle.bottom - rectangle.top
    crop_half_width = max(int(window_width * 0.065), 100)
    crop_above = max(int(window_height * 0.11), 90)
    crop_below = max(int(window_height * 0.035), 35)

    for point in _hover_scan_points(attachment_point, image_size):
        screen_x, screen_y = _screen_point(point, image_size, rectangle)
        mouse.move(coords=(screen_x, screen_y))
        time.sleep(0.28)
        tooltip_image = ImageGrab.grab(
            bbox=(
                screen_x - crop_half_width,
                screen_y - crop_above,
                screen_x + crop_half_width,
                screen_y + crop_below,
            ),
            all_screens=True,
        )
        tooltip_items = _ocr_items(tooltip_image)
        if any(
            _normalize_text(item.get("text", "")) == "下载"
            for item in tooltip_items
        ):
            print(f"Lark 悬停识别到下载图标：{point}")
            return screen_x, screen_y
    return None


def _download_snapshot(folder, extensions):
    result = {}
    folder = Path(folder)
    if not folder.is_dir():
        return result
    for path in folder.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        try:
            result[path.resolve()] = (path.stat().st_size, path.stat().st_mtime_ns)
        except OSError:
            continue
    return result


def _existing_download_for_key(folder, search_key, extensions):
    matches = [
        path
        for path in _download_snapshot(folder, extensions)
        if search_key in re.sub(r"\D", "", path.stem)
    ]
    return max(matches, key=lambda path: path.stat().st_mtime_ns) if matches else None


def _wait_for_download(
    folder,
    search_key,
    extensions,
    before,
    timeout,
    require_key=True,
):
    deadline = time.monotonic() + timeout
    stable = {}
    while time.monotonic() < deadline:
        current = _download_snapshot(folder, extensions)
        completed = []
        for path, state in current.items():
            if before.get(path) == state:
                continue
            if require_key and search_key not in re.sub(r"\D", "", path.stem):
                continue
            previous_size, count = stable.get(path, (-1, 0))
            size = state[0]
            stable[path] = (size, count + 1 if size == previous_size else 0)
            if size > 0 and stable[path][1] >= 2:
                completed.append(path)
        if completed:
            return max(
                completed,
                key=lambda path: (
                    search_key in re.sub(r"\D", "", path.stem),
                    path.stat().st_mtime_ns,
                ),
            )
        time.sleep(0.8)
    return None


def _confirm_save_dialog(download_dir, timeout=4):
    import win32gui
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        handles = []
        win32gui.EnumWindows(lambda handle, target: target.append(handle), handles)
        for handle in handles:
            if not win32gui.IsWindowVisible(handle):
                continue
            if win32gui.GetClassName(handle) != "#32770":
                continue
            title = _normalize_text(win32gui.GetWindowText(handle))
            if not any(marker in title for marker in ("另存为", "保存", "saveas", "save")):
                continue
            dialog = Desktop(backend="win32").window(handle=handle)
            try:
                dialog.set_focus()
            except Exception:
                pass
            send_keys("^l")
            send_keys(str(Path(download_dir)), with_spaces=True)
            send_keys("{ENTER}")
            time.sleep(0.8)
            buttons = []
            for control in dialog.descendants():
                try:
                    text = _normalize_text(control.window_text())
                    if control.class_name() == "Button" and (
                        "保存" in text or text.startswith("save")
                    ):
                        buttons.append(control)
                except Exception:
                    continue
            if buttons:
                buttons[-1].click_input()
            else:
                send_keys("%s")
            print(f"已确认系统保存对话框，目标目录：{download_dir}")
            return True
        time.sleep(0.25)
    return False


def _ensure_mail_view(window):
    from pywinauto import mouse
    from pywinauto.keyboard import send_keys

    if window.is_minimized():
        window.restore()
    try:
        window.set_focus()
    except Exception:
        pass
    time.sleep(1.0)
    for _ in range(3):
        image, rectangle = _capture_visible_window(window)
        items = _ocr_items(image)
        if _mail_view_visible(items):
            return image, items
        if not _mail_results_page_visible(items):
            break
        back_point = _mail_results_back_point(items, image.size)
        if back_point is not None:
            mouse.click(coords=_screen_point(back_point, image.size, rectangle))
        else:
            send_keys("{ESC}")
        time.sleep(0.8)
    if not _mail_view_visible(items):
        navigation_point = _mail_navigation_point(items, image.size)
        if navigation_point is not None:
            rectangle = window.rectangle()
            mouse.click(coords=_screen_point(navigation_point, image.size, rectangle))
            time.sleep(1.2)
            image, _ = _capture_visible_window(window)
            items = _ocr_items(image)
    if not _mail_view_visible(items):
        send_keys("^+f")
        time.sleep(1.2)
        image, _ = _capture_visible_window(window)
        items = _ocr_items(image)
    if not _mail_view_visible(items):
        raise RuntimeError(
            "Lark 当前不是邮箱收件箱页面，Ctrl+Shift+F 也未能打开邮件搜索。"
            "请手动打开“邮箱”后重试。"
        )
    return image, items


def _search_mail(window, image, items, search_key):
    from pywinauto import mouse
    from pywinauto.keyboard import send_keys

    if not re.fullmatch(r"\d{8}", search_key):
        raise RuntimeError(f"拒绝搜索非 8 位主单号：{search_key}")
    if not _mail_view_visible(items):
        raise RuntimeError("搜索前未确认 Lark 邮箱页面，已停止输入。")
    point = _mail_search_point(items)
    if point is None:
        raise RuntimeError("没有识别到 Lark 邮件搜索框，已停止输入。")

    rectangle = window.rectangle()
    mouse.click(coords=_screen_point(point, image.size, rectangle))
    time.sleep(0.2)
    send_keys("^a{BACKSPACE}")
    send_keys(search_key)
    send_keys("{ENTER}")
    deadline = time.monotonic() + 8
    last_mail_state = False
    while time.monotonic() < deadline:
        time.sleep(0.7)
        image, _ = _capture_visible_window(window)
        result_items = _ocr_items(image)
        last_mail_state = _mail_view_visible(result_items) or _mail_search_results_visible(
            result_items,
            search_key,
        )
        if not last_mail_state:
            continue
        point = _mail_result_click_point(result_items, search_key, image.size)
        if point is not None:
            return image, result_items, point
    if not last_mail_state:
        sample = " | ".join(
            str(item.get("text", "")) for item in result_items[:30]
        )
        print(f"Lark 搜索后 OCR：{sample}")
        raise RuntimeError("搜索后 Lark 邮箱页面校验失败，已停止自动下载。")
    key_items = [
        f"{item.get('text', '')}@{_item_center(item)}"
        for item in result_items
        if search_key in re.sub(r"\D", "", str(item.get("text", "")))
    ]
    print(f"Lark 搜索结果坐标：{' | '.join(key_items)}")
    raise RuntimeError(f"Lark 邮箱没有找到包含 {search_key} 的邮件。")


def _find_attachment(
    window,
    search_key,
    extensions,
    name_markers=(),
    max_scrolls=8,
):
    from pywinauto import mouse

    for _ in range(max_scrolls + 1):
        image, rectangle = _capture_visible_window(window)
        items = _ocr_items(image)
        key_visible = _mail_detail_visible(items, search_key, image.size)
        if not key_visible:
            raise RuntimeError(f"打开邮件后无法确认主单号 {search_key}，已停止点击。")
        point = _attachment_click_point(
            items,
            extensions,
            image.size,
            search_key,
            name_markers,
        )
        if point is not None:
            matched_text = next(
                (
                    str(item.get("text", ""))
                    for item in items
                    if abs(_item_center(item)[0] - point[0]) < 2
                    and abs(_item_center(item)[1] - point[1]) < 2
                ),
                "",
            )
            print(f"Lark 附件定位：{matched_text}@{point}")
            return image, items, point
        mouse.move(
            coords=_screen_point(
                (image.width * 0.78, image.height * 0.78),
                image.size,
                rectangle,
            )
        )
        mouse.scroll(wheel_dist=-6)
        time.sleep(0.7)
    return None, None, None


def _windows_download_dir(config):
    configured = str(config.get("lark_download_dir", "auto")).strip()
    if configured and configured.lower() != "auto":
        return Path(os.path.expandvars(configured)).expanduser()

    if os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            value_name = "{374DE290-123F-4565-9164-39C4925E467B}"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
            return Path(os.path.expandvars(value)).expanduser()
        except (OSError, ImportError):
            pass
    return Path.home() / "Downloads"


def _rename_download(path, prefix, search_key):
    path = Path(path)
    destination = path.with_name(f"{prefix}{search_key}{path.suffix.lower()}")
    if destination == path:
        return path
    if destination.exists():
        raise RuntimeError(f"目标文件已存在，未覆盖：{destination}")
    path.rename(destination)
    return destination


def _download_mail_files(
    search_keys,
    config,
    *,
    attachment_markers=(),
    rename_prefix=None,
    source_label="Cainiao",
):
    from pywinauto import mouse
    from pywinauto.keyboard import send_keys

    extensions = {
        str(extension).lower() if str(extension).startswith(".") else "." + str(extension).lower()
        for extension in config.get("allowed_extensions", [".xls", ".xlsx", ".csv"])
    }
    download_dir = _windows_download_dir(config)
    if not download_dir.is_dir():
        raise RuntimeError(f"Lark 下载目录不存在：{download_dir}")

    files_by_key = {}
    missing = []
    pending = []
    for search_key in search_keys:
        existing = _existing_download_for_key(download_dir, search_key, extensions)
        if existing is not None:
            files_by_key[search_key] = existing
        else:
            pending.append(search_key)
    if not pending:
        return files_by_key, missing

    window = _find_lark_window()
    timeout = max(10, int(config.get("download_timeout_seconds", 90)))
    for search_key in pending:
        try:
            image, _ = _capture_visible_window(window)
            items = _ocr_items(image)
            result_point = None
            if _mail_search_results_visible(items, search_key):
                result_point = _mail_result_click_point(items, search_key, image.size)
            if result_point is None:
                image, items = _ensure_mail_view(window)
                image, items, result_point = _search_mail(
                    window,
                    image,
                    items,
                    search_key,
                )
            image, items = _open_mail_result(
                window,
                image,
                items,
                result_point,
                search_key,
            )
            image, items, attachment_point = _find_attachment(
                window,
                search_key,
                extensions,
                attachment_markers,
            )
            if attachment_point is None:
                marker_text = " / ".join(attachment_markers) or search_key
                raise RuntimeError(f"邮件中没有识别到 {marker_text} 对应的 Excel/CSV 附件。")

            stage_dir = (
                download_dir
                / "iMileInbox"
                / f"{search_key}-{time.time_ns()}"
            )
            stage_dir.mkdir(parents=True, exist_ok=False)
            root_before = _download_snapshot(download_dir, extensions)
            rectangle = window.rectangle()
            attachment_coords = _screen_point(attachment_point, image.size, rectangle)
            mouse.right_click(coords=attachment_coords)
            time.sleep(0.8)
            menu_image, menu_rectangle = _capture_screen_window(window)
            menu_items = _ocr_items(menu_image)
            download_point = _context_download_point(
                menu_items,
                menu_image.size,
                attachment_point,
            )
            menu_items = [
                f"{_normalize_text(item.get('text', ''))}@{_item_center(item)}"
                for item in menu_items
                if "下载" in _normalize_text(item.get("text", ""))
                or "预览" in _normalize_text(item.get("text", ""))
                or "本地应用打开" in _normalize_text(item.get("text", ""))
                or "复制" in _normalize_text(item.get("text", ""))
            ]
            print(f"Lark 附件菜单：{' | '.join(menu_items)}；下载坐标：{download_point}")
            if download_point is not None:
                mouse.click(
                    coords=_screen_point(download_point, menu_image.size, menu_rectangle)
                )
            else:
                send_keys("{ESC}")
                time.sleep(0.4)
                rectangle = window.rectangle()
                hover_point = _hover_download_icon(
                    window,
                    attachment_point,
                    image.size,
                    rectangle,
                )
                if hover_point is None:
                    raise RuntimeError(
                        "没有可靠识别到附件右键菜单或悬停提示中的“下载”，已停止点击。"
                    )
                mouse.click(coords=hover_point)
            save_dialog_confirmed = _confirm_save_dialog(stage_dir)
            watched_dir = stage_dir if save_dialog_confirmed else download_dir
            before = {} if save_dialog_confirmed else root_before
            path = _wait_for_download(
                watched_dir,
                search_key,
                extensions,
                before,
                timeout,
                require_key=not attachment_markers,
            )
            if path is None:
                raise RuntimeError(f"已点击邮件附件，但等待 {search_key} 下载超时。")
            if rename_prefix:
                path = _rename_download(path, rename_prefix, search_key)
            files_by_key[search_key] = path
            print(f"{source_label} 邮件附件已下载：{path.name}")
            try:
                _, items = _ensure_mail_view(window)
            except RuntimeError as cleanup_error:
                print(f"附件已下载成功，返回邮箱首页失败：{cleanup_error}")
        except RuntimeError as exc:
            print(str(exc))
            missing.append(search_key)
            try:
                _, items = _ensure_mail_view(window)
            except Exception:
                break
    return files_by_key, missing


def download_cainiao_files(search_keys, config):
    return _download_mail_files(search_keys, config)


def download_shunyou_files(search_keys, config):
    markers = config.get("shunyou_attachment_markers", ["IMILE末端预报"])
    if isinstance(markers, str):
        markers = [markers]
    return _download_mail_files(
        search_keys,
        config,
        attachment_markers=tuple(str(marker) for marker in markers),
        rename_prefix=str(config.get("shunyou_filename_prefix", "顺友")),
        source_label="顺友",
    )
