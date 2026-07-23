import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import webbrowser


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "wecom_download_config.json"
QUERY_FILE = APP_DIR / "output" / "query_list.txt"
TARGET_FILE = APP_DIR / "中心运单查询.xlsx"
DEFAULT_DC_URL = (
    "https://dc.imile.com/#/DCoperation/"
    "DCoperationWaybillManagement/CentralWaybillQuery"
)
EXPORT_EXTENSIONS = {".xlsx", ".xls", ".csv"}
PROGRESS_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+)\s*\(\s*(\d+)\s*%\s*\)")
PAGE_NAME_KEYS = {"中心运单查询", "centralwaybillquery"}
TRACKING_LABEL_KEYS = {"运单号", "waybillnumber"}
EXPORT_LABEL_KEYS = {"导出", "export"}
EXPORT_ALL_LABEL_KEYS = {"导出全部", "exportall"}
DOWNLOAD_LABEL_KEYS = {"下载", "download"}
SECURITY_WARNING_KEYS = {
    "数据安全告警",
    "datasecuritywarning",
    "datasecurityalert",
    "datasecurityalarm",
}
EXPORT_COMPLETE_KEYS = {"已完成", "导出成功", "completed", "exportsuccess", "finished"}
EXPORT_COLUMN_KEY_MAP = {
    "运单号": "运单号",
    "waybillnumber": "运单号",
    "trackingnumber": "运单号",
    "路由码": "路由码",
    "routingcode": "路由码",
    "routecode": "路由码",
    "派件网点简码": "派件网点简码",
    "deliverystationscode": "派件网点简码",
    "deliverystationcode": "派件网点简码",
    "dispatchstationcode": "派件网点简码",
    "参考订单号": "参考订单号",
    "referenceordernumber": "参考订单号",
    "商家编号": "商家编号",
    "clientcode": "商家编号",
    "merchantcode": "商家编号",
}


def _load_config(config=None):
    if config is not None:
        return dict(config)
    if not CONFIG_PATH.exists():
        raise RuntimeError("找不到 wecom_download_config.json，请先打开收件设置。")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def _resolve_app_path(path, default):
    value = Path(os.path.expandvars(str(path or default))).expanduser()
    return value if value.is_absolute() else APP_DIR / value


def _read_query_numbers(query_file=QUERY_FILE):
    path = _resolve_app_path(query_file, QUERY_FILE)
    if not path.exists():
        raise RuntimeError(f"找不到查询单号文件：{path}")
    numbers = []
    seen = set()
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        value = raw_line.strip()
        if value and value not in seen:
            numbers.append(value)
            seen.add(value)
    if not numbers:
        raise RuntimeError(f"查询单号文件为空：{path}")
    return path, numbers


def _normalize_text(value):
    return re.sub(r"\s+", "", str(value or "")).lower()


def _text_key(value):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def _has_text_key(value, keys):
    return _text_key(value) in keys


def _control_name(control):
    try:
        return str(control.window_text()).strip()
    except Exception:
        return ""


def _control_class(control):
    try:
        return str(control.element_info.class_name or "")
    except Exception:
        return ""


def _control_type(control):
    try:
        return str(control.element_info.control_type or "")
    except Exception:
        return ""


def _automation_id(control):
    try:
        return str(control.element_info.automation_id or "")
    except Exception:
        return ""


def _rectangle(control):
    try:
        return control.rectangle()
    except Exception:
        return None


def _is_visible(control):
    rect = _rectangle(control)
    if rect is None or rect.right <= rect.left or rect.bottom <= rect.top:
        return False
    try:
        return bool(control.is_visible())
    except Exception:
        return True


def _descendants(window):
    try:
        return window.descendants()
    except Exception:
        return []


def _click_control(control):
    errors = []
    methods = (
        ("invoke", "legacy", "click")
        if _automation_id(control)
        else ("click", "invoke", "legacy")
    )
    for method in methods:
        try:
            if method == "invoke":
                control.iface_invoke.Invoke()
            elif method == "legacy":
                control.iface_legacy_iaccessible.DoDefaultAction()
            else:
                control.click_input()
            return
        except Exception as exc:
            errors.append(exc)
    raise RuntimeError(f"控件点击失败：{errors[-1]}")


def _activate_control(control):
    try:
        control.iface_invoke.Invoke()
        return
    except Exception:
        _click_control(control)


def _set_clipboard_text(text):
    import win32clipboard

    for attempt in range(10):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return
        except Exception:
            if attempt == 9:
                raise RuntimeError("无法写入 Windows 剪贴板，请关闭占用剪贴板的程序后重试。")
            time.sleep(0.1)


def _tracking_edit(window):
    controls = _descendants(window)
    edits = [
        control
        for control in controls
        if _control_type(control) == "Edit"
        and _rectangle(control) is not None
        and _rectangle(control).right > _rectangle(control).left
        and _rectangle(control).bottom > _rectangle(control).top
    ]
    for control in edits:
        class_name = _control_class(control)
        if "bg-transparent" in class_name and "outline-none" in class_name:
            return control

    labels = [
        control
        for control in controls
        if _has_text_key(_control_name(control), TRACKING_LABEL_KEYS)
        and _control_type(control) == "Text"
    ]
    for label in sorted(labels, key=lambda item: (_rectangle(item).top, _rectangle(item).left)):
        label_rect = _rectangle(label)
        if label_rect is None:
            continue
        nearby = []
        for edit in edits:
            rect = _rectangle(edit)
            if rect is None or "Omnibox" in _control_class(edit):
                continue
            if (
                rect.left >= label_rect.left - 20
                and rect.top >= label_rect.top
                and rect.top <= label_rect.bottom + 80
            ):
                nearby.append(edit)
        if nearby:
            return min(nearby, key=lambda item: _rectangle(item).top)
    return None


def _page_ready(window):
    return _tracking_edit(window) is not None


def _browser_window_handles():
    import win32gui

    handles = []

    def collect(handle, _):
        try:
            if not win32gui.IsWindowVisible(handle):
                return
            if win32gui.GetClassName(handle) != "Chrome_WidgetWin_1":
                return
            title = win32gui.GetWindowText(handle).strip()
            normalized = title.lower().replace("\u200b", "")
            if not any(
                marker in normalized
                for marker in ("microsoft edge", "google chrome")
            ):
                return
            score = 1
            if title.startswith(("DC -", "DS -")):
                score += 20
            if (
                "中心运单查询" in title
                or "central waybill query" in normalized
                or "分箱预分配" in title
                or "box planning" in normalized
            ):
                score += 20
            if "imile" in normalized or "dc" in normalized:
                score += 5
            handles.append((score, handle, title))
        except Exception:
            return

    win32gui.EnumWindows(collect, None)
    return sorted(handles, reverse=True)


def _address_bar_url(window):
    for control in _descendants(window):
        if _control_type(control) != "Edit":
            continue
        if "Omnibox" not in _control_class(control):
            continue
        try:
            return str(control.get_value()).strip()
        except Exception:
            return _control_name(control)
    return ""


def _find_dc_window():
    from pywinauto import Desktop

    best = None
    for title_score, handle, _ in _browser_window_handles():
        try:
            window = Desktop(backend="uia").window(handle=handle)
            url = _address_bar_url(window)
            score = title_score + (
                50
                if re.search(r"https?://[^/]*\.imile\.com(?:/|$)", url.lower())
                else 0
            )
            if best is None or score > best[0]:
                best = (score, window)
        except Exception:
            continue
    if best is None or best[0] < 1:
        return None
    return best[1]


def _login_page_visible(window):
    combined = " ".join(_normalize_text(_control_name(control)) for control in _descendants(window))
    markers = (
        "账号登录",
        "密码登录",
        "手机号登录",
        "登录imile",
        "signin",
        "loginto",
        "verificationcode",
    )
    return any(marker in combined for marker in markers)


def _portal_shell_visible(window):
    return any(
        _automation_id(control) == "ImileSMN-aside-MySearch"
        for control in _descendants(window)
    )


def _open_from_search_menu(window, timeout=20):
    search_control = next(
        (
            control
            for control in _descendants(window)
            if _automation_id(control) == "ImileSMN-aside-MySearch"
        ),
        None,
    )
    if search_control is None:
        return False
    _click_control(search_control)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window_rect = _rectangle(window)
        matches = []
        for control in _descendants(window):
            if not _has_text_key(_control_name(control), PAGE_NAME_KEYS):
                continue
            if not _is_visible(control):
                continue
            if _control_type(control) not in {"Text", "Button", "ListItem"}:
                continue
            rect = _rectangle(control)
            if rect is None or window_rect is None:
                continue
            if rect.left < window_rect.left + window_rect.width() * 0.45:
                matches.append(control)
        if matches:
            preferred = [item for item in matches if "DragHandle" not in _control_class(item)]
            _click_control((preferred or matches)[-1])
            page_deadline = time.monotonic() + timeout
            while time.monotonic() < page_deadline:
                if _page_ready(window):
                    return True
                time.sleep(0.5)
            return False
        time.sleep(0.5)
    return False


def _prepare_window(window):
    try:
        if window.is_minimized():
            window.restore()
    except Exception:
        pass
    try:
        window.maximize()
    except Exception:
        pass
    try:
        window.set_focus()
    except Exception:
        pass


def _ensure_dc_page(config):
    if sys.platform != "win32":
        raise RuntimeError("中心运单查询自动下载只能在 Windows 电脑上运行。")
    timeout = max(20, int(config.get("dc_page_timeout_seconds", 60)))
    url = str(config.get("dc_url") or DEFAULT_DC_URL).strip()

    window = _find_dc_window()
    if window is not None:
        _prepare_window(window)
        if _page_ready(window):
            return window
        if _portal_shell_visible(window) and _open_from_search_menu(window):
            return window

    print(f"正在打开中心运单查询：{url}")
    webbrowser.open(url, new=2)
    deadline = time.monotonic() + timeout
    last_window = None
    search_attempted = False
    while time.monotonic() < deadline:
        candidate = _find_dc_window()
        if candidate is None:
            time.sleep(0.8)
            continue
        last_window = candidate
        _prepare_window(candidate)
        if _page_ready(candidate):
            return candidate
        if _login_page_visible(candidate):
            raise RuntimeError(
                "iMile DC 系统尚未登录。请先在浏览器完成登录，再点击“重试中心运单导出”。"
            )
        if not search_attempted and _portal_shell_visible(candidate):
            search_attempted = True
            if _open_from_search_menu(candidate):
                return candidate
        time.sleep(0.8)

    if last_window is not None and _login_page_visible(last_window):
        raise RuntimeError(
            "iMile DC 系统尚未登录。请先在浏览器完成登录，再点击“重试中心运单导出”。"
        )
    raise RuntimeError(
        "没有进入“中心运单查询”页面。程序已尝试固定网址和左侧搜索入口，"
        "请确认账号有该页面权限后重试。"
    )


def _result_contains_query(window, query_set):
    for control in _descendants(window):
        if _control_type(control) != "Text" or not _is_visible(control):
            continue
        name = _control_name(control)
        if name in query_set:
            return True
        if _normalize_text(name) in {"暂无数据", "无数据", "nodata"}:
            return True
    return False


def _submit_query(window, numbers, timeout):
    from pywinauto.keyboard import send_keys

    edit = _tracking_edit(window)
    if edit is None:
        raise RuntimeError("没有找到中心运单查询的“运单号”输入框，已停止操作。")
    _set_clipboard_text("\r\n".join(numbers))
    try:
        edit.click_input()
    except Exception:
        _click_control(edit)
    send_keys("^a")
    send_keys("^v")
    send_keys("{ENTER}")
    print(f"已提交 {len(numbers)} 个唯一运单号，正在等待查询结果。")

    deadline = time.monotonic() + max(10, int(timeout))
    query_set = set(numbers)
    while time.monotonic() < deadline:
        time.sleep(1.0)
        if _result_contains_query(window, query_set):
            return
    raise RuntimeError(
        f"提交查询后等待 {int(timeout)} 秒仍未确认结果，请检查 DC 页面后点击重试。"
    )


def _page_export_control(window):
    window_rect = _rectangle(window)
    if window_rect is None:
        return None
    controls = _descendants(window)
    candidates = []
    for control in controls:
        if not _has_text_key(_control_name(control), EXPORT_LABEL_KEYS):
            continue
        if not _is_visible(control):
            continue
        if "export-button" in _control_class(control):
            continue
        if _control_type(control) not in {"Text", "Button", "Group"}:
            continue
        rect = _rectangle(control)
        if rect is None:
            continue
        if rect.left > window_rect.left + window_rect.width() * 0.65:
            parents = []
            center_x = (rect.left + rect.right) / 2
            center_y = (rect.top + rect.bottom) / 2
            for candidate in controls:
                candidate_rect = _rectangle(candidate)
                if candidate_rect is None or not _is_visible(candidate):
                    continue
                if "ImileActionButton-root" not in _control_class(candidate):
                    continue
                if (
                    candidate_rect.left <= center_x <= candidate_rect.right
                    and candidate_rect.top <= center_y <= candidate_rect.bottom
                ):
                    parents.append(candidate)
            if parents:
                candidates.append(min(parents, key=lambda item: _rectangle(item).width()))
            else:
                candidates.append(control)
    return min(candidates, key=lambda item: _rectangle(item).top) if candidates else None


def _export_drawer(window):
    candidates = [
        control
        for control in _descendants(window)
        if "MuiDrawer-paper" in _control_class(control) and _is_visible(control)
    ]
    return max(candidates, key=lambda item: _rectangle(item).width()) if candidates else None


def _export_all_menu_control(window):
    candidates = [
        control
        for control in _descendants(window)
        if _has_text_key(_control_name(control), EXPORT_ALL_LABEL_KEYS)
        and _control_type(control) in {"MenuItem", "ListItem", "Text", "Button", "Group"}
        and _is_visible(control)
    ]
    return min(candidates, key=lambda item: _rectangle(item).top) if candidates else None


def _open_export_drawer(window, timeout=15):
    from pywinauto.keyboard import send_keys

    for attempt in range(2):
        existing = _export_drawer(window)
        if existing is not None:
            return existing
        export_control = None
        control_deadline = time.monotonic() + max(2, timeout / 3)
        while time.monotonic() < control_deadline:
            export_control = _page_export_control(window)
            if export_control is not None:
                break
            time.sleep(0.3)
        if export_control is None:
            if attempt == 0:
                continue
            raise RuntimeError("没有找到页面右上角的“导出”控件，已停止操作。")
        _activate_control(export_control)
        menu_deadline = time.monotonic() + timeout / 2
        while time.monotonic() < menu_deadline:
            drawer = _export_drawer(window)
            if drawer is not None:
                return drawer
            menu_item = _export_all_menu_control(window)
            if menu_item is not None:
                _activate_control(menu_item)
                break
            time.sleep(0.3)
        else:
            drawer = _export_drawer(window)
            if drawer is not None:
                return drawer
            if attempt == 0:
                send_keys("{ESC}")
                continue
            raise RuntimeError("点击导出后没有出现“导出全部”菜单，已停止操作。")

        drawer_deadline = time.monotonic() + timeout / 2
        while time.monotonic() < drawer_deadline:
            drawer = _export_drawer(window)
            if drawer is not None:
                return drawer
            time.sleep(0.4)
        send_keys("{ESC}")
    raise RuntimeError("已点击“导出全部”，但导出任务抽屉没有打开。")


def _parse_progress(text):
    match = PROGRESS_PATTERN.search(str(text or ""))
    if not match:
        return None
    current, total, percent = (int(value) for value in match.groups())
    return current, total, percent


def _latest_task_state(window):
    drawer = _export_drawer(window)
    if drawer is None:
        return None
    drawer_rect = _rectangle(drawer)
    controls = _descendants(window)
    titles = []
    for control in controls:
        if not _has_text_key(_control_name(control), PAGE_NAME_KEYS):
            continue
        if not _is_visible(control):
            continue
        rect = _rectangle(control)
        if rect is None:
            continue
        if (
            drawer_rect.left <= rect.left <= drawer_rect.right
            and drawer_rect.top + 60 <= rect.top <= drawer_rect.bottom
        ):
            titles.append(control)
    if not titles:
        return None
    titles.sort(key=lambda item: _rectangle(item).top)
    title = titles[0]
    title_rect = _rectangle(title)
    next_top = _rectangle(titles[1]).top if len(titles) > 1 else drawer_rect.bottom
    band_bottom = min(next_top - 1, title_rect.top + 220)

    progress = None
    band_text = []
    icons = []
    for control in controls:
        if not _is_visible(control):
            continue
        rect = _rectangle(control)
        if rect is None:
            continue
        if not (
            drawer_rect.left <= rect.left <= drawer_rect.right
            and title_rect.top - 15 <= rect.top < band_bottom
        ):
            continue
        name = _control_name(control)
        if name:
            band_text.append(name)
            parsed = _parse_progress(name)
            if parsed is not None:
                progress = parsed
        if "Imile-ButtonIcon-root" in _control_class(control):
            icons.append(control)
    icons.sort(key=lambda item: _rectangle(item).left)
    combined_text_key = _text_key(" ".join(band_text))
    return {
        "count": len(titles),
        "signature": tuple(sorted(set(band_text))),
        "progress": progress,
        "complete": bool(progress and (progress[2] >= 100 or progress[0] >= progress[1] > 0))
        or any(marker in combined_text_key for marker in EXPORT_COMPLETE_KEYS),
        "download_control": icons[0] if icons else None,
    }


def _create_export_task(window):
    drawer = _export_drawer(window)
    if drawer is None:
        raise RuntimeError("导出任务抽屉已关闭，无法创建导出任务。")
    drawer_rect = _rectangle(drawer)
    candidates = []
    for control in _descendants(window):
        if "export-button" not in _control_class(control):
            continue
        if not _is_visible(control):
            continue
        rect = _rectangle(control)
        if rect is not None and drawer_rect.left <= rect.left <= drawer_rect.right:
            candidates.append(control)
    if not candidates:
        raise RuntimeError("导出任务抽屉中没有找到蓝色“导出”按钮。")
    _activate_control(min(candidates, key=lambda item: _rectangle(item).top))


def _wait_for_new_task(window, previous, timeout, poll_interval):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = _latest_task_state(window)
        if latest is not None and (
            previous is None
            or latest["count"] > previous["count"]
            or latest["signature"] != previous["signature"]
        ):
            break
        time.sleep(min(1.0, poll_interval))
    else:
        raise RuntimeError("点击导出后没有检测到新的中心运单查询任务，已停止下载。")

    last_progress = None
    while time.monotonic() < deadline:
        latest = _latest_task_state(window)
        if latest is not None:
            if latest["progress"] != last_progress and latest["progress"] is not None:
                current, total, percent = latest["progress"]
                print(f"中心运单导出进度：{current}/{total} ({percent}%)")
                last_progress = latest["progress"]
            if latest["complete"]:
                return latest
        time.sleep(poll_interval)
    raise RuntimeError(f"中心运单导出等待超过 {int(timeout)} 秒，可稍后点击重试继续下载。")


def _security_download_button(window, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        controls = _descendants(window)
        warning = next(
            (
                control
                for control in controls
                if _has_text_key(_control_name(control), SECURITY_WARNING_KEYS)
            ),
            None,
        )
        if warning is None:
            time.sleep(0.3)
            continue
        warning_rect = _rectangle(warning)
        candidates = []
        for control in controls:
            if not _has_text_key(_control_name(control), DOWNLOAD_LABEL_KEYS):
                continue
            if not _is_visible(control):
                continue
            if _control_type(control) not in {"Button", "Text", "Group"}:
                continue
            rect = _rectangle(control)
            if rect is None or warning_rect is None:
                continue
            if rect.top > warning_rect.top:
                candidates.append(control)
        if candidates:
            return max(candidates, key=lambda item: _rectangle(item).left)
        time.sleep(0.3)
    return None


def _windows_download_dir(config):
    configured = str(config.get("dc_download_dir", "auto")).strip()
    if configured and configured.lower() != "auto":
        return Path(os.path.expandvars(configured)).expanduser()
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        value_name = "{374DE290-123F-4565-9164-39C4925E467B}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
        return Path(os.path.expandvars(value)).expanduser()
    except (OSError, ImportError):
        return Path.home() / "Downloads"


def _download_snapshot(folder):
    folder = Path(folder)
    snapshot = {}
    if not folder.exists():
        return snapshot
    for path in folder.iterdir():
        try:
            if path.is_file() and path.suffix.lower() in EXPORT_EXTENSIONS:
                stat = path.stat()
                snapshot[path.resolve()] = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            continue
    return snapshot


def _wait_for_download(folder, before, started_at, timeout):
    deadline = time.monotonic() + timeout
    stable = {}
    while time.monotonic() < deadline:
        current = _download_snapshot(folder)
        candidates = []
        for path, state in current.items():
            if before.get(path) == state:
                continue
            try:
                if path.stat().st_mtime < started_at - 3:
                    continue
            except OSError:
                continue
            previous_size, stable_count = stable.get(path, (-1, 0))
            size = state[0]
            stable[path] = (size, stable_count + 1 if size == previous_size else 0)
            if size > 0 and stable[path][1] >= 2:
                candidates.append(path)
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime_ns)
        time.sleep(0.8)
    return None


def _column_rename_map(columns):
    existing = {str(column).strip() for column in columns}
    rename_map = {}
    for column in columns:
        original = str(column).strip()
        canonical = EXPORT_COLUMN_KEY_MAP.get(_text_key(original), original)
        if canonical != original and canonical not in existing:
            rename_map[column] = canonical
    return rename_map


def _read_export_frame(path, nrows=None):
    import pandas as pd

    path = Path(path)
    try:
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, nrows=nrows, dtype=str, encoding_errors="replace")
        else:
            frame = pd.read_excel(path, nrows=nrows, dtype=str)
    except Exception as exc:
        raise RuntimeError(f"下载文件无法作为中心运单查询表读取：{path.name} ({exc})") from exc
    rename_map = _column_rename_map(frame.columns)
    return frame.rename(columns=rename_map), rename_map


def _validate_export(path):
    path = Path(path)
    frame, rename_map = _read_export_frame(path, nrows=5)
    columns = {str(column).strip() for column in frame.columns}
    if "运单号" not in columns:
        raise RuntimeError(f"下载文件缺少“运单号”列，未覆盖现有报表数据：{path.name}")
    supporting = {"路由码", "派件网点简码", "参考订单号", "商家编号"}
    if not columns.intersection(supporting):
        raise RuntimeError(f"下载文件不像中心运单查询导出表，未覆盖现有数据：{path.name}")
    return columns, rename_map


def _install_export(source, target=TARGET_FILE):
    source = Path(source)
    target = _resolve_app_path(target, TARGET_FILE)
    _, rename_map = _validate_export(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.{time.time_ns()}.tmp.xlsx")
    try:
        if source.suffix.lower() == ".xlsx" and not rename_map:
            shutil.copy2(source, temporary)
        else:
            frame, _ = _read_export_frame(source)
            frame.to_excel(temporary, index=False)
        os.replace(temporary, target)
    except PermissionError as exc:
        raise RuntimeError(f"无法更新 {target.name}，请先关闭 Excel 中打开的同名文件。") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def verify_dc_page(config=None):
    config = _load_config(config)
    window = _ensure_dc_page(config)
    query_input = _tracking_edit(window)
    export_control = _page_export_control(window)
    search_control = next(
        (
            control
            for control in _descendants(window)
            if _automation_id(control) == "ImileSMN-aside-MySearch"
        ),
        None,
    )
    if query_input is None or export_control is None:
        raise RuntimeError("DC 页面已打开，但查询输入框或导出按钮未能通过动态控件识别。")
    return {
        "query_input": True,
        "export": True,
        "search_fallback": search_control is not None,
        "url": _address_bar_url(window),
    }


def download_center_waybill_query(query_file=QUERY_FILE, config=None):
    config = _load_config(config)
    query_path, numbers = _read_query_numbers(query_file)
    print(f"读取查询单号：{query_path.name}，共 {len(numbers)} 个。")
    window = _ensure_dc_page(config)
    _submit_query(
        window,
        numbers,
        config.get("dc_query_timeout_seconds", 120),
    )
    _open_export_drawer(window)
    print("已选择“导出全部”，正在点击导出任务抽屉中的“导出”。")
    previous = _latest_task_state(window)
    _create_export_task(window)
    print("已创建最新导出任务，正在等待进度达到 100%。")
    latest = _wait_for_new_task(
        window,
        previous,
        max(30, int(config.get("dc_export_timeout_seconds", 900))),
        max(1, int(config.get("dc_poll_interval_seconds", 3))),
    )
    latest = _latest_task_state(window) or latest
    download_control = latest.get("download_control")
    if download_control is None:
        raise RuntimeError("导出任务已完成，但没有识别到任务卡片内的下载图标。")
    print("最新导出任务已达 100%，正在点击任务右侧的小下载图标。")

    download_dir = _windows_download_dir(config)
    download_dir.mkdir(parents=True, exist_ok=True)
    stage_dir = download_dir / "iMileDC" / str(time.time_ns())
    stage_dir.mkdir(parents=True, exist_ok=False)
    before = _download_snapshot(download_dir)
    started_at = time.time()
    _activate_control(download_control)
    confirmation = _security_download_button(window)
    if confirmation is not None:
        _activate_control(confirmation)

    from lark_mail_downloader import _confirm_save_dialog

    save_dialog = _confirm_save_dialog(stage_dir, timeout=4)
    watched_dir = stage_dir if save_dialog else download_dir
    watched_before = {} if save_dialog else before
    downloaded = _wait_for_download(
        watched_dir,
        watched_before,
        started_at,
        max(20, int(config.get("dc_file_download_timeout_seconds", 120))),
    )
    if downloaded is None:
        raise RuntimeError("已确认下载，但等待中心运单查询文件保存超时。")
    target = _install_export(downloaded)
    print(f"中心运单查询已下载并校验：{target}")
    return target


if __name__ == "__main__":
    print(download_center_waybill_query())
