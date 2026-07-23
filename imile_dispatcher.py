import re
import time
import unicodedata
import webbrowser
from dataclasses import dataclass

import imile_dc_downloader as dc


PAGE_NAME_KEYS = {"分箱预分配", "boxpreallocation", "boxpreassignment"}
DEFAULT_DISPATCH_URL = "https://ds.imile.com/#/DSOperation/DispatchManagementNew/BoxPlanning"
PENDING_ASSIGN_KEYS = {"待分配", "pendingallocation", "pendingassignment"}
ROUTE_LABEL_KEYS = {"routecode"}
QUERY_KEYS = {"查询", "search"}
MERGE_KEYS = {"合并箱号", "mergeboxcode", "mergeboxnumber"}
EXPORT_KEYS = {"导出", "export"}
BATCH_KEYS = {"批量操作", "batchoperation", "batchactions"}
ASSIGN_KEYS = {"分配", "assign", "assignment"}
SUPPLIER_KEYS = {"供应商", "supplier"}
CONFIRM_KEYS = {"确定", "确认", "confirm", "ok"}
DRIVER_LABEL_KEYS = {"分配司机", "司机", "assigndriver", "driver"}
NO_DATA_KEYS = {"暂无数据", "无数据", "nodata", "noresults"}
RESULTS_PATTERN = re.compile(r"showing\s+(\d+)\s+of\s+(\d+)\s+results", re.IGNORECASE)


@dataclass(frozen=True)
class DispatchRule:
    route_base: str
    driver_name: str
    driver_id: str | None = None
    route_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoxRow:
    row_key: str
    route_code: str
    box_code: str
    waybill_count: int | None = None


@dataclass(frozen=True)
class DriverOption:
    name: str
    driver_id: str
    raw_text: str


@dataclass(frozen=True)
class DispatchResult:
    route_base: str
    matched_routes: tuple[str, ...]
    old_box_codes: tuple[str, ...]
    merged_box_code: str
    driver: DriverOption


@dataclass
class _UIRow:
    value: BoxRow
    y: float
    checkbox: object | None


def _collapse_spaces(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).strip())


def normalize_route_code(value):
    return _collapse_spaces(value).upper()


def _normalize_person(value):
    return _collapse_spaces(value).casefold()


def route_code_matches(base, candidate):
    base_key = normalize_route_code(base)
    candidate_key = normalize_route_code(candidate)
    if not base_key or not candidate_key:
        return False
    return re.fullmatch(rf"{re.escape(base_key)}(?: [A-Z])?", candidate_key) is not None


def matching_route_rows(rows, base):
    return [row for row in rows if route_code_matches(base, row.route_code)]


def selected_route_rows(rows, route_codes):
    selected = {normalize_route_code(value) for value in route_codes}
    return [row for row in rows if normalize_route_code(row.route_code) in selected]


def _parse_route_codes(route_spec):
    raw_codes = re.split(r"[,，]+", str(route_spec or ""))
    route_codes = tuple(
        dict.fromkeys(normalize_route_code(value) for value in raw_codes if normalize_route_code(value))
    )
    if not route_codes:
        raise ValueError("Route Code 不能为空。")
    for route_code in route_codes:
        if not re.fullmatch(r"[0-9]{3,}(?: [A-Z])?", route_code):
            raise ValueError(f"Route Code 格式无效：{route_code}")

    route_query = ",".join(route_codes)
    return route_query, route_codes


def parse_dispatch_rule(route_spec, driver_spec):
    route_base, route_codes = _parse_route_codes(route_spec)

    parts = [part.strip() for part in str(driver_spec or "").split("|")]
    if not parts or not parts[0]:
        raise ValueError("司机姓名不能为空。")
    if len(parts) > 2:
        raise ValueError("司机格式应为“完整姓名”或“完整姓名 | 司机ID”。")
    driver_id = parts[1] if len(parts) == 2 else None
    if len(parts) == 2 and not driver_id:
        raise ValueError("“|”后面缺少司机 ID。")
    if driver_id and not re.fullmatch(r"[Dd][0-9A-Za-z]+", driver_id):
        raise ValueError(f"司机 ID 格式无效：{driver_id}")
    return DispatchRule(route_base, _collapse_spaces(parts[0]), driver_id, route_codes)


def _split_dispatch_groups(value):
    return tuple(
        group.strip()
        for group in re.split(r"[;；\r\n]+", str(value or ""))
        if group.strip()
    )


def parse_dispatch_batch(route_spec, driver_spec):
    route_groups = _split_dispatch_groups(route_spec)
    driver_groups = _split_dispatch_groups(driver_spec)
    if not route_groups:
        raise ValueError("Route Code 不能为空。")
    if not driver_groups:
        raise ValueError("司机姓名不能为空。")
    if len(route_groups) != len(driver_groups):
        raise ValueError(
            f"线路共 {len(route_groups)} 组，司机共 {len(driver_groups)} 组；"
            "请用分号分组并确保一一对应。"
        )

    rules = []
    for index, (route_group, driver_group) in enumerate(
        zip(route_groups, driver_groups),
        start=1,
    ):
        try:
            rules.append(parse_dispatch_rule(route_group, driver_group))
        except ValueError as exc:
            raise ValueError(f"第 {index} 组输入无效：{exc}") from exc
    return tuple(rules)


def _manifest_route_code(token):
    match = re.fullmatch(r"([0-9]{3,})([A-Za-z]?)", str(token or "").strip())
    if match is None:
        return None
    number, suffix = match.groups()
    return number + (f" {suffix.upper()}" if suffix else "")


def parse_dispatch_manifest(manifest):
    lines = [
        (line_number, line.strip())
        for line_number, line in enumerate(str(manifest or "").splitlines(), start=1)
        if line.strip()
    ]
    if not lines:
        raise ValueError("分单清单不能为空。")

    rules = []
    for line_number, line in lines:
        parts = line.split()
        route_codes = []
        split_at = 0
        for split_at, token in enumerate(parts):
            route_code = _manifest_route_code(token)
            if route_code is None:
                break
            route_codes.append(route_code)
        else:
            split_at = len(parts)

        driver_parts = parts[split_at:]
        if not route_codes:
            raise ValueError(f"第 {line_number} 行开头没有有效线路：{line}")
        if not driver_parts:
            raise ValueError(f"第 {line_number} 行缺少司机：{line}")
        if len(driver_parts) > 1 and re.fullmatch(r"[A-Za-z]", driver_parts[0]):
            raise ValueError(
                f"第 {line_number} 行的字母线路后缀请紧贴数字填写，"
                "例如写 404B；程序会自动转换为 404 B。"
            )

        try:
            rules.append(
                parse_dispatch_rule(",".join(route_codes), " ".join(driver_parts))
            )
        except ValueError as exc:
            raise ValueError(f"第 {line_number} 行输入无效：{exc}") from exc
    return tuple(rules)


def parse_driver_option(text):
    raw_text = _collapse_spaces(text)
    if "|" not in raw_text:
        raise ValueError(f"司机选项缺少 ID：{raw_text}")
    name, driver_id = (part.strip() for part in raw_text.rsplit("|", 1))
    if not name or not driver_id:
        raise ValueError(f"司机选项格式无效：{raw_text}")
    if not re.fullmatch(r"[Dd][0-9A-Za-z]+", driver_id):
        raise ValueError(f"司机选项 ID 格式无效：{raw_text}")
    return DriverOption(name, driver_id, raw_text)


def resolve_driver(options, rule):
    unique = {}
    for option in options:
        key = (_normalize_person(option.name), option.driver_id.casefold())
        unique.setdefault(key, option)

    candidates = list(unique.values())
    if rule.driver_id is None:
        if candidates:
            return candidates[0]
        raise RuntimeError(f"搜索司机 {rule.driver_name} 后没有可选结果。")

    matches = [
        option
        for option in candidates
        if _normalize_person(option.name) == _normalize_person(rule.driver_name)
        and option.driver_id.casefold() == rule.driver_id.casefold()
    ]
    if not matches:
        choices = "、".join(option.raw_text for option in candidates)
        detail = f"；当前候选：{choices}" if choices else ""
        raise RuntimeError(
            f"没有找到精确司机：{rule.driver_name} | {rule.driver_id}{detail}"
        )
    return matches[0]


def _rule_route_codes(rule):
    return rule.route_codes or (rule.route_base,)


def _single_box(rows, route_codes, expected_routes=None, expected_waybills=None):
    matches = selected_route_rows(rows, route_codes)
    if not matches or any(not row.box_code for row in matches):
        return None
    if expected_waybills is not None:
        counts = [row.waybill_count for row in matches]
        if any(value is None for value in counts) or sum(counts) != expected_waybills:
            return None
    elif expected_routes is not None:
        current_routes = {normalize_route_code(row.route_code) for row in matches}
        if not set(expected_routes).issubset(current_routes):
            return None
    box_codes = {row.box_code for row in matches}
    return next(iter(box_codes)) if len(box_codes) == 1 else None


def dispatch_one(rule, page, timeout=45, initial_rows=None):
    if initial_rows is None:
        page.search_routes(rule.route_base)
        rows = page.read_route_rows()
    else:
        rows = list(initial_rows)
    route_codes = _rule_route_codes(rule)
    matches = selected_route_rows(rows, route_codes)
    if not matches:
        requested = ", ".join(route_codes)
        raise RuntimeError(f"没有找到所选 Route Code（{requested}）的待分配箱号。")
    if any(not row.box_code for row in matches):
        raise RuntimeError(f"Route Code {rule.route_base} 的结果缺少箱号，已停止操作。")

    matched_routes = tuple(dict.fromkeys(row.route_code for row in matches))
    old_box_codes = tuple(dict.fromkeys(row.box_code for row in matches))
    expected_routes = {normalize_route_code(row.route_code) for row in matches}
    counts = [row.waybill_count for row in matches]
    expected_waybills = sum(counts) if counts and all(value is not None for value in counts) else None
    merged_box_code = _single_box(matches, route_codes)
    if merged_box_code is None:
        page.select_rows([row.row_key for row in matches])
        page.merge_selected()
        deadline = time.monotonic() + max(0, float(timeout))
        page.search_routes(rule.route_base)
        while True:
            refreshed = page.read_route_rows()
            merged_box_code = _single_box(
                refreshed,
                route_codes,
                expected_routes=expected_routes,
                expected_waybills=expected_waybills,
            )
            if merged_box_code is not None:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Route Code {rule.route_base} 合并后仍未收敛为唯一箱号，未执行司机分配。"
                )
            time.sleep(0.25)

    page.open_assign(merged_box_code)
    page.search_drivers(rule.driver_name)
    option = resolve_driver(page.read_driver_options(), rule)
    page.choose_driver(option)
    return DispatchResult(
        route_base=rule.route_base,
        matched_routes=matched_routes,
        old_box_codes=old_box_codes,
        merged_box_code=merged_box_code,
        driver=option,
    )


def _rect_width(rect):
    return rect.right - rect.left


def _rect_height(rect):
    return rect.bottom - rect.top


def _rect_area(rect):
    return max(0, _rect_width(rect)) * max(0, _rect_height(rect))


def _center(rect):
    return ((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2)


def _contains(rect, x, y):
    return rect.left <= x <= rect.right and rect.top <= y <= rect.bottom


def _visible_controls(window):
    return [control for control in dc._descendants(window) if dc._is_visible(control)]


def _clickable_for_text(controls, text_control):
    rect = dc._rectangle(text_control)
    if rect is None:
        return text_control
    x, y = _center(rect)
    parents = []
    for control in controls:
        candidate_rect = dc._rectangle(control)
        if candidate_rect is None or not _contains(candidate_rect, x, y):
            continue
        class_key = dc._control_class(control).casefold()
        if dc._control_type(control) in {"Button", "Tab", "MenuItem", "ListItem"} or any(
            marker in class_key for marker in ("button", "menuitem", "muitab-root")
        ):
            parents.append(control)
    return min(parents, key=lambda item: _rect_area(dc._rectangle(item))) if parents else text_control


def _text_actions(window, keys):
    controls = _visible_controls(window)
    actions = []
    seen = set()
    for control in controls:
        if dc._text_key(dc._control_name(control)) not in keys:
            continue
        action = _clickable_for_text(controls, control)
        rect = dc._rectangle(action)
        if rect is None:
            continue
        signature = (round(_center(rect)[0]), round(_center(rect)[1]))
        if signature not in seen:
            actions.append(action)
            seen.add(signature)
    return actions


def _activate_text_action(window, keys, prefer_right=False):
    actions = _text_actions(window, keys)
    if not actions:
        return False
    actions.sort(key=lambda item: (_center(dc._rectangle(item))[0], _center(dc._rectangle(item))[1]))
    dc._activate_control(actions[-1] if prefer_right else actions[0])
    return True


def _find_route_edit(window):
    controls = _visible_controls(window)
    edits = [
        control
        for control in controls
        if dc._control_type(control) in {"Edit", "ComboBox"}
        and "Omnibox" not in dc._control_class(control)
    ]
    labels = [
        control
        for control in controls
        if dc._text_key(dc._control_name(control)) in ROUTE_LABEL_KEYS
        and dc._control_type(control) in {"Text", "Group"}
    ]
    candidates = []
    for label in labels:
        label_rect = dc._rectangle(label)
        if label_rect is None:
            continue
        for edit in edits:
            rect = dc._rectangle(edit)
            if rect is None:
                continue
            if (
                rect.left >= label_rect.left - 30
                and rect.left <= label_rect.right + 260
                and rect.top >= label_rect.top - 10
                and rect.top <= label_rect.bottom + 90
            ):
                candidates.append((abs(rect.left - label_rect.left) + abs(rect.top - label_rect.bottom), edit))
    if not candidates:
        return None
    text_edits = [
        candidate
        for candidate in candidates
        if dc._control_type(candidate[1]) == "Edit"
    ]
    return min(text_edits or candidates, key=lambda item: item[0])[1]


def _control_values(control):
    values = []
    try:
        values.append(str(control.get_value()))
    except Exception:
        pass
    try:
        values.append(str(control.iface_value.CurrentValue))
    except Exception:
        pass
    values.append(dc._control_name(control))
    return [value for value in values if value]


def _set_edit_text(control, value, field_name, guard=None, refetch=None):
    errors = []
    try:
        control.set_edit_text("")
    except Exception as exc:
        errors.append(exc)
        try:
            control.iface_value.SetValue("")
        except Exception as fallback_exc:
            errors.append(fallback_exc)
            raise RuntimeError(
                f"无法直接写入{field_name}输入框；为避免误选网页文字，已停止操作：{errors[-1]}"
            ) from fallback_exc

    focused = False
    focus_error = None
    for _attempt in range(2):
        if refetch is not None:
            refreshed = refetch()
            if refreshed is not None:
                control = refreshed
        try:
            control.click_input()
        except Exception as exc:
            focus_error = exc
            continue
        focus_deadline = time.monotonic() + 2
        while time.monotonic() < focus_deadline:
            try:
                if control.has_keyboard_focus():
                    focused = True
                    break
            except Exception:
                pass
            time.sleep(0.1)
        if focused:
            break
    if not focused:
        suffix = f"：{focus_error}" if focus_error is not None else ""
        raise RuntimeError(f"{field_name}输入框没有获得键盘焦点；为避免误输到网页，已停止操作。")

    if guard is not None:
        guard()
    try:
        control.type_keys(
            value,
            pause=0.03,
            with_spaces=True,
            set_foreground=True,
        )
    except Exception as exc:
        raise RuntimeError(f"无法向{field_name}输入框键入内容，已停止操作：{exc}") from exc

    expected = _collapse_spaces(value)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = refetch() if refetch is not None else None
        candidates = [item for item in (current, control) if item is not None]
        if any(
            _collapse_spaces(item) == expected
            for candidate in candidates
            for item in _control_values(candidate)
        ):
            return
        time.sleep(0.15)
    raise RuntimeError(f"写入{field_name}后无法读回确认，已停止操作。")


def _page_ready(window):
    return _find_route_edit(window) is not None and bool(_text_actions(window, PENDING_ASSIGN_KEYS))


def _active_dispatch_page(window):
    return _dispatch_url_active(window) and _page_ready(window)


def _dispatch_url_active(window):
    active_url = dc._address_bar_url(window).casefold()
    return "dsoperation/dispatchmanagementnew/boxplanning" in active_url


def _pending_table_visible(window):
    keys = {
        dc._text_key(dc._control_name(control))
        for control in _visible_controls(window)
        if dc._control_name(control)
    }
    return "boxcode" in keys and bool({"运单数", "waybillcount"}.intersection(keys))


def _open_dispatch_from_search(window, timeout=25):
    search_control = next(
        (
            control
            for control in dc._descendants(window)
            if dc._automation_id(control) == "ImileSMN-aside-MySearch"
        ),
        None,
    )
    if search_control is None:
        return False
    dc._click_control(search_control)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window_rect = dc._rectangle(window)
        actions = []
        for action in _text_actions(window, PAGE_NAME_KEYS):
            rect = dc._rectangle(action)
            if rect is None or window_rect is None:
                continue
            if rect.left < window_rect.left + _rect_width(window_rect) * 0.45:
                if "DragHandle" not in dc._control_class(action):
                    actions.append(action)
        if actions:
            dc._activate_control(actions[-1])
            page_deadline = time.monotonic() + timeout
            while time.monotonic() < page_deadline:
                if _page_ready(window):
                    return True
                time.sleep(0.5)
            return False
        time.sleep(0.5)
    return False


def _activate_pending_tab(window, timeout=25):
    deadline = time.monotonic() + timeout
    target = None
    while time.monotonic() < deadline:
        actions = [
            control
            for control in _visible_controls(window)
            if dc._control_type(control) == "TabItem"
            and dc._text_key(dc._control_name(control)) in PENDING_ASSIGN_KEYS
        ]
        if actions:
            target = min(actions, key=lambda item: _center(dc._rectangle(item))[1])
            try:
                selected = bool(target.iface_selection_item.CurrentIsSelected)
            except Exception:
                selected = None
            if selected is not False and _pending_table_visible(window):
                return
            break
        time.sleep(0.4)
    if target is None:
        raise RuntimeError("没有找到“待分配”页签，已停止自动分单。")
    try:
        target.click_input()
    except Exception:
        try:
            target.select()
        except Exception:
            dc._activate_control(target)
    while time.monotonic() < deadline:
        actions = [
            control
            for control in _visible_controls(window)
            if dc._control_type(control) == "TabItem"
            and dc._text_key(dc._control_name(control)) in PENDING_ASSIGN_KEYS
        ]
        if actions and _find_route_edit(window) is not None and _pending_table_visible(window):
            current = min(actions, key=lambda item: _center(dc._rectangle(item))[1])
            try:
                if not bool(current.iface_selection_item.CurrentIsSelected):
                    time.sleep(0.4)
                    continue
            except Exception:
                pass
            return
        time.sleep(0.4)
    raise RuntimeError("点击“待分配”后页面没有就绪，已停止自动分单。")


def _activate_existing_dispatch_browser_tab(window, timeout=20):
    candidates = []
    for control in dc._descendants(window):
        if dc._control_type(control) != "TabItem" or not dc._is_visible(control):
            continue
        name = dc._control_name(control)
        if "分箱预分配" in name:
            candidates.append(control)
    if not candidates:
        return False
    candidates.sort(key=lambda item: (dc._control_name(item) != "DS - 分箱预分配", len(dc._control_name(item))))
    target = candidates[0]
    try:
        target.click_input()
    except Exception:
        dc._activate_control(target)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            tab_selected = bool(target.iface_selection_item.CurrentIsSelected)
        except Exception:
            tab_selected = False
        if tab_selected and _active_dispatch_page(window):
            return True
        time.sleep(0.4)
    return False


def _ensure_dispatch_page(config):
    if dc.sys.platform != "win32":
        raise RuntimeError("自动分单只能在 Windows 电脑上运行。")
    timeout = max(20, int(config.get("dc_dispatch_page_timeout_seconds", 60)))
    from pywinauto import Desktop

    windows = []
    for _score, handle, _title in dc._browser_window_handles():
        try:
            windows.append(Desktop(backend="uia").window(handle=handle))
        except Exception:
            continue

    for window in windows:
        dc._prepare_window(window)
        if _active_dispatch_page(window):
            _activate_pending_tab(window, timeout=min(timeout, 25))
            return window

    per_window_timeout = max(3, min(8, timeout // max(1, len(windows))))
    for window in windows:
        dc._prepare_window(window)
        if _activate_existing_dispatch_browser_tab(window, per_window_timeout):
            _activate_pending_tab(window, timeout=min(timeout, 25))
            return window

    configured_url = str(config.get("dc_dispatch_url") or DEFAULT_DISPATCH_URL).strip()
    print("没有找到现有分箱预分配标签页，正在新开一个页面。")
    webbrowser.open(configured_url, new=2)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidate = dc._find_dc_window()
        if candidate is None:
            time.sleep(0.8)
            continue
        dc._prepare_window(candidate)
        if _active_dispatch_page(candidate):
            _activate_pending_tab(candidate, timeout=min(timeout, 25))
            return candidate
        time.sleep(0.8)
    raise RuntimeError(
        "没有找到或打开“分箱预分配”的“待分配”页面。请确认 Edge 已登录 DC 后重试。"
    )


class UIADispatchPage:
    def __init__(self, window, route_base, config):
        self.window = window
        self.route_base = route_base
        self.config = config
        self.action_timeout = max(8, int(config.get("dc_dispatch_action_timeout_seconds", 20)))
        self.query_timeout = max(
            self.action_timeout,
            int(config.get("dc_dispatch_query_timeout_seconds", 45)),
        )
        self._rows = {}
        self._driver_controls = {}
        self._assign_dialog_confirmed = False

    def _require_active_dispatch(self):
        if _dispatch_url_active(self.window):
            return
        if _activate_existing_dispatch_browser_tab(self.window, timeout=5):
            return
        refreshed = dc._find_dc_window()
        if refreshed is not None:
            self.window = refreshed
            if _dispatch_url_active(self.window):
                return
            if _activate_existing_dispatch_browser_tab(self.window, timeout=5):
                return
        raise RuntimeError(
            "当前 Edge 已离开“分箱预分配”页面；为避免误点其他业务页面，已停止自动分单。"
        )

    def _headers(self):
        controls = _visible_controls(self.window)
        route_headers = [
            control
            for control in controls
            if dc._text_key(dc._control_name(control)) == "routecode"
            and dc._control_type(control) in {"Text", "Header", "HeaderItem", "Group"}
        ]
        box_headers = [control for control in controls if dc._text_key(dc._control_name(control)) == "boxcode"]
        count_headers = [
            control
            for control in controls
            if dc._text_key(dc._control_name(control)) in {"运单数", "waybillcount"}
        ]
        operation_headers = [
            control
            for control in controls
            if dc._text_key(dc._control_name(control)) in {"操作", "operation", "actions"}
        ]
        matches = []
        for route in route_headers:
            route_rect = dc._rectangle(route)
            if route_rect is None:
                continue
            _, route_y = _center(route_rect)
            for box in box_headers:
                box_rect = dc._rectangle(box)
                if box_rect is None:
                    continue
                _, box_y = _center(box_rect)
                if abs(route_y - box_y) > 35 or box_rect.left >= route_rect.left:
                    continue
                aligned_counts = []
                for count in count_headers:
                    count_rect = dc._rectangle(count)
                    if count_rect is None:
                        continue
                    _, count_y = _center(count_rect)
                    if abs(route_y - count_y) <= 35 and box_rect.left < count_rect.left < route_rect.left:
                        aligned_counts.append(count)
                if not aligned_counts:
                    continue
                for operation in operation_headers:
                    operation_rect = dc._rectangle(operation)
                    if operation_rect is None:
                        continue
                    _, operation_y = _center(operation_rect)
                    if abs(route_y - operation_y) <= 35 and operation_rect.left > route_rect.left:
                        matches.append((route_rect.top, box, aligned_counts[0], route, operation))
        if not matches:
            raise RuntimeError("没有识别到待分配表格的 Boxcode / Routecode / 操作列。")
        _, box, count, route, operation = max(matches, key=lambda item: item[0])
        return box, count, route, operation

    def _result_counts(self):
        controls = _visible_controls(self.window)
        for control in controls:
            match = RESULTS_PATTERN.search(dc._control_name(control))
            if match:
                return int(match.group(1)), int(match.group(2))
        rows = {}
        for control in controls:
            rect = dc._rectangle(control)
            name = _collapse_spaces(dc._control_name(control))
            if rect is None or not name:
                continue
            _, y = _center(rect)
            rows.setdefault(round(y / 8), []).append((rect.left, name))
        for parts in rows.values():
            combined = " ".join(name for _, name in sorted(parts))
            match = RESULTS_PATTERN.search(combined)
            if match:
                return int(match.group(1)), int(match.group(2))
        return None

    def _has_no_data(self):
        return any(
            dc._text_key(dc._control_name(control)) in NO_DATA_KEYS
            for control in _visible_controls(self.window)
        )

    def _is_loading(self):
        for control in _visible_controls(self.window):
            class_key = dc._control_class(control).casefold()
            if dc._control_type(control) == "ProgressBar" or any(
                marker in class_key for marker in ("circularprogress", "spinner", "loading")
            ):
                return True
        return False

    def _stable_result_signature(self):
        counts = self._result_counts()
        if counts is None:
            return None
        if counts[1] == 0 or self._has_no_data():
            return (counts, ())
        rows = self.read_route_rows()
        if len(rows) != counts[1]:
            return None
        values = tuple(
            (normalize_route_code(row.route_code), row.box_code, row.waybill_count)
            for row in rows
        )
        return counts, values

    def search_routes(self, base):
        self._require_active_dispatch()
        edit = _find_route_edit(self.window)
        if edit is None:
            raise RuntimeError("没有找到 Route Code 输入框。")
        _set_edit_text(
            edit,
            base,
            "Route Code",
            self._require_active_dispatch,
            lambda: _find_route_edit(self.window),
        )
        query_deadline = time.monotonic() + min(5, self.action_timeout)
        query_clicked = False
        while time.monotonic() < query_deadline:
            self._require_active_dispatch()
            if _activate_text_action(self.window, QUERY_KEYS, prefer_right=True):
                query_clicked = True
                break
            time.sleep(0.2)
        if not query_clicked:
            raise RuntimeError("没有找到“查询”按钮。")
        deadline = time.monotonic() + self.action_timeout
        started_at = time.monotonic()
        last_signature = None
        stable_count = 0
        while time.monotonic() < deadline:
            time.sleep(0.4)
            if self._is_loading() or time.monotonic() - started_at < 0.8:
                continue
            try:
                signature = self._stable_result_signature()
            except RuntimeError as exc:
                if "分页" in str(exc) or "未识别到运单数" in str(exc):
                    raise
                signature = None
            if signature is None:
                stable_count = 0
                continue
            if signature == last_signature:
                stable_count += 1
            else:
                last_signature = signature
                stable_count = 1
            if stable_count >= 2:
                return
        raise RuntimeError(f"查询 Route Code {base} 后结果没有完整、稳定地加载。")

    def read_route_rows(self):
        self._require_active_dispatch()
        box_header, count_header, route_header, operation_header = self._headers()
        controls = _visible_controls(self.window)
        box_rect = dc._rectangle(box_header)
        count_rect = dc._rectangle(count_header)
        route_rect = dc._rectangle(route_header)
        operation_rect = dc._rectangle(operation_header)
        header_bottom = max(box_rect.bottom, count_rect.bottom, route_rect.bottom, operation_rect.bottom)
        route_x, _ = _center(route_rect)
        box_x, _ = _center(box_rect)
        count_x, _ = _center(count_rect)
        route_tolerance = max(90, _rect_width(route_rect) * 1.8)
        box_tolerance = max(110, _rect_width(box_rect) * 2.2)
        count_tolerance = max(70, _rect_width(count_rect) * 1.8)
        route_cells = []
        for control in controls:
            if dc._control_type(control) not in {"Text", "DataItem", "Group"}:
                continue
            rect = dc._rectangle(control)
            name = _collapse_spaces(dc._control_name(control))
            if rect is None or rect.top <= header_bottom or not name:
                continue
            x, y = _center(rect)
            if abs(x - route_x) <= route_tolerance and re.fullmatch(r"[0-9A-Z]+(?: [A-Z])?", name.upper()):
                route_cells.append((y, name, control))

        parsed = []
        for y, route_code, _ in route_cells:
            box_candidates = []
            count_candidates = []
            checkbox_candidates = []
            for control in controls:
                rect = dc._rectangle(control)
                if rect is None:
                    continue
                x, control_y = _center(rect)
                if abs(control_y - y) > 28:
                    continue
                name = _collapse_spaces(dc._control_name(control))
                if abs(x - box_x) <= box_tolerance and name and name.casefold() != "boxcode":
                    if re.fullmatch(r"[0-9A-Z_-]{5,}", name.upper()):
                        box_candidates.append((abs(x - box_x), name))
                if abs(x - count_x) <= count_tolerance and re.fullmatch(r"[\d,]+", name):
                    count_candidates.append((abs(x - count_x), int(name.replace(",", ""))))
                class_key = dc._control_class(control).casefold()
                if x < box_rect.left and (
                    dc._control_type(control) == "CheckBox" or "checkbox" in class_key
                ):
                    checkbox_candidates.append((abs(control_y - y), -x, control))
            box_code = min(box_candidates, default=(0, ""), key=lambda item: item[0])[1]
            waybill_count = min(count_candidates, default=(0, None), key=lambda item: item[0])[1]
            checkbox = min(checkbox_candidates, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]
            if checkbox is None:
                continue
            row_key = f"{box_code}\x1f{normalize_route_code(route_code)}\x1f{round(y)}"
            parsed.append(_UIRow(BoxRow(row_key, route_code, box_code, waybill_count), y, checkbox))

        deduped = {}
        for row in sorted(parsed, key=lambda item: item.y):
            key = (normalize_route_code(row.value.route_code), row.value.box_code)
            deduped.setdefault(key, row)
        self._rows = {row.value.row_key: row for row in deduped.values()}
        if self._rows and any(row.value.waybill_count is None for row in self._rows.values()):
            raise RuntimeError("有表格行未识别到运单数，无法安全确认合并完整性，未执行选择。")
        counts = self._result_counts()
        if counts is not None and counts[1] > len(self._rows):
            raise RuntimeError(
                f"查询返回 {counts[1]} 行，但当前只识别到 {len(self._rows)} 行。"
                "页面可能有分页或控件尚未加载完成，未执行选择。"
            )
        return [row.value for row in self._rows.values()]

    def _toggle_state(self, control):
        try:
            return bool(control.get_toggle_state())
        except Exception:
            try:
                return bool(control.iface_toggle.CurrentToggleState)
            except Exception:
                return None

    def select_rows(self, row_keys):
        self._require_active_dispatch()
        selected_count = self._result_counts()
        if selected_count is not None and selected_count[0] != 0:
            raise RuntimeError("当前页面已有勾选项，请先取消选择后再运行自动分单。")
        targets = []
        for row_key in row_keys:
            row = self._rows.get(row_key)
            if row is None or row.checkbox is None:
                raise RuntimeError("目标线路中有一行未识别到复选框，未执行合并。")
            targets.append(
                (
                    normalize_route_code(row.value.route_code),
                    row.value.box_code,
                    row.value.waybill_count,
                )
            )

        for expected_selected, (route_code, box_code, waybill_count) in enumerate(targets, start=1):
            confirmed = False
            for _attempt in range(2):
                self.read_route_rows()
                current = [
                    row
                    for row in self._rows.values()
                    if normalize_route_code(row.value.route_code) == route_code
                    and row.value.box_code == box_code
                    and row.value.waybill_count == waybill_count
                ]
                if len(current) != 1 or current[0].checkbox is None:
                    raise RuntimeError(
                        f"勾选过程中目标行发生变化：{route_code} / {box_code}，未执行合并。"
                    )
                counts = self._result_counts()
                if counts is not None and counts[0] == expected_selected:
                    confirmed = True
                    break
                checkbox = current[0].checkbox
                state = self._toggle_state(checkbox)
                if state is not True:
                    self._require_active_dispatch()
                    try:
                        checkbox.click_input()
                    except Exception:
                        dc._activate_control(checkbox)

                deadline = time.monotonic() + min(8, self.action_timeout)
                while time.monotonic() < deadline:
                    counts = self._result_counts()
                    if counts is not None and counts[0] == expected_selected:
                        confirmed = True
                        break
                    time.sleep(0.2)
                if confirmed:
                    break
            if not confirmed:
                raise RuntimeError(
                    f"勾选 {route_code} / {box_code} 后未确认选中数量为 {expected_selected}，"
                    "未执行合并。"
                )

    def _wait_text_action(self, keys, timeout=None):
        deadline = time.monotonic() + (timeout or self.action_timeout)
        while time.monotonic() < deadline:
            actions = _text_actions(self.window, keys)
            if actions:
                return actions[-1]
            time.sleep(0.25)
        return None

    def _confirm_merge_dialog(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            controls = _visible_controls(self.window)
            dialogs = [
                control
                for control in controls
                if (
                    "dialog" in dc._control_class(control).casefold()
                    or dc._control_type(control) == "Window"
                )
                and dc._rectangle(control) is not None
            ]
            for dialog in dialogs:
                dialog_rect = dc._rectangle(dialog)
                text_key = dc._text_key(
                    " ".join(
                        dc._control_name(control)
                        for control in controls
                        if dc._rectangle(control) is not None
                        and _contains(dialog_rect, *_center(dc._rectangle(control)))
                    )
                )
                if not any(key in text_key for key in MERGE_KEYS):
                    continue
                candidates = []
                for action in _text_actions(self.window, CONFIRM_KEYS):
                    rect = dc._rectangle(action)
                    if rect is not None and _contains(dialog_rect, *_center(rect)):
                        candidates.append(action)
                if candidates:
                    self._require_active_dispatch()
                    dc._activate_control(max(candidates, key=lambda item: _center(dc._rectangle(item))[0]))
                    return
            time.sleep(0.2)

    def merge_selected(self):
        self._require_active_dispatch()
        merge_action = self._wait_text_action(MERGE_KEYS, timeout=1)
        if merge_action is None:
            opened = _activate_text_action(self.window, EXPORT_KEYS, prefer_right=True)
            if not opened:
                opened = _activate_text_action(self.window, BATCH_KEYS, prefer_right=True)
            if not opened:
                raise RuntimeError("没有找到包含“合并箱号”的操作菜单。")
            merge_action = self._wait_text_action(MERGE_KEYS)
        if merge_action is None:
            raise RuntimeError("操作菜单中没有找到“合并箱号”。")
        self._require_active_dispatch()
        dc._activate_control(merge_action)
        self._confirm_merge_dialog()

    def _operation_controls_for_row(self, row):
        _, _, _, operation_header = self._headers()
        operation_rect = dc._rectangle(operation_header)
        controls = _visible_controls(self.window)
        raw = []
        for control in controls:
            rect = dc._rectangle(control)
            if rect is None:
                continue
            x, y = _center(rect)
            class_key = dc._control_class(control).casefold()
            if (
                abs(y - row.y) <= 30
                and x >= operation_rect.left - 20
                and (dc._control_type(control) == "Button" or "button" in class_key)
                and _rect_width(rect) <= 70
                and _rect_height(rect) <= 70
            ):
                raw.append(control)
        grouped = {}
        for control in raw:
            rect = dc._rectangle(control)
            x, _ = _center(rect)
            key = round(x / 8)
            current = grouped.get(key)
            if current is None or _rect_area(rect) > _rect_area(dc._rectangle(current)):
                grouped[key] = control
        candidates = sorted(grouped.values(), key=lambda item: _center(dc._rectangle(item))[0])
        if len(candidates) != 5:
            return []
        # The DS operation column is stable: the driver assignment control is
        # the second square icon. The right-most paper-plane icon assigns a
        # supplier and must never be used by this workflow.
        return [candidates[1]]

    def _dialogs(self):
        candidates = [
            control
            for control in _visible_controls(self.window)
            if (
                "dialog" in dc._control_class(control).casefold()
                or dc._control_type(control) == "Window"
            )
            and dc._rectangle(control) is not None
        ]
        return sorted(candidates, key=lambda item: _rect_area(dc._rectangle(item)), reverse=True)

    def _assign_dialog(self, box_code=None):
        expected_box = str(box_code or getattr(self, "_assign_box_code", "")).strip()
        controls = _visible_controls(self.window)
        for dialog in self._dialogs():
            dialog_rect = dc._rectangle(dialog)
            title_key = dc._text_key(dc._control_name(dialog))
            names = [
                dc._control_name(control)
                for control in controls
                if dc._rectangle(control) is not None
                and _contains(dialog_rect, *_center(dc._rectangle(control)))
            ]
            text_key = dc._text_key(" ".join(names))
            if any(key in text_key for key in SUPPLIER_KEYS):
                continue
            if self._assign_dialog_confirmed and title_key in ASSIGN_KEYS:
                return dialog
            has_assign = any(key in text_key for key in ASSIGN_KEYS)
            has_driver = any(key in text_key for key in DRIVER_LABEL_KEYS)
            has_box = not expected_box or expected_box.casefold() in " ".join(names).casefold()
            if has_assign and has_driver and has_box:
                return dialog
        return None

    def open_assign(self, box_code):
        self._require_active_dispatch()
        self._assign_dialog_confirmed = False
        self.read_route_rows()
        rows = [row for row in self._rows.values() if row.value.box_code == box_code]
        if not rows:
            raise RuntimeError(f"合并后没有找到箱号 {box_code} 的表格行。")
        controls = self._operation_controls_for_row(rows[0])
        if not controls:
            raise RuntimeError(f"箱号 {box_code} 的操作列中没有识别到“分配”按钮。")
        target = controls[0]
        self._assign_box_code = box_code
        self._require_active_dispatch()
        dc._activate_control(target)
        deadline = time.monotonic() + self.query_timeout
        while time.monotonic() < deadline:
            if self._assign_dialog(box_code) is not None:
                self._assign_dialog_confirmed = True
                return
            time.sleep(0.25)
        raise RuntimeError("点击后没有识别到包含目标箱号和“分配司机”的分配窗口。")

    def _dialog_controls(self):
        dialog = self._assign_dialog()
        if dialog is None:
            return None, []
        dialog_rect = dc._rectangle(dialog)
        controls = [
            control
            for control in _visible_controls(self.window)
            if dc._rectangle(control) is not None
            and _contains(dialog_rect, *_center(dc._rectangle(control)))
        ]
        return dialog, controls

    def _driver_edit(self):
        dialog, controls = self._dialog_controls()
        if dialog is None:
            return None
        labels = [
            control
            for control in controls
            if dc._text_key(dc._control_name(control)) in DRIVER_LABEL_KEYS
        ]
        edits = [
            control
            for control in controls
            if dc._control_type(control) in {"Edit", "ComboBox"}
        ]
        candidates = []
        for label in labels:
            label_rect = dc._rectangle(label)
            for edit in edits:
                rect = dc._rectangle(edit)
                if rect.top >= label_rect.top and rect.top <= label_rect.bottom + 100:
                    candidates.append((abs(rect.top - label_rect.bottom), edit))
        if not candidates:
            return None
        text_edits = [
            candidate
            for candidate in candidates
            if dc._control_type(candidate[1]) == "Edit"
        ]
        return min(text_edits or candidates, key=lambda item: item[0])[1]

    def _driver_popup(self):
        candidates = [
            control
            for control in _visible_controls(self.window)
            if dc._control_type(control) == "List"
            and "pro-select-content" in dc._control_class(control)
            and dc._rectangle(control) is not None
        ]
        return max(candidates, key=lambda item: _rect_area(dc._rectangle(item))) if candidates else None

    def _driver_search_edit(self):
        popup = self._driver_popup()
        if popup is None:
            return None
        popup_rect = dc._rectangle(popup)
        candidates = [
            control
            for control in _visible_controls(self.window)
            if dc._control_type(control) == "Edit"
            and dc._text_key(dc._control_name(control)) in {"搜索", "search"}
            and dc._rectangle(control) is not None
            and _contains(popup_rect, *_center(dc._rectangle(control)))
        ]
        return min(candidates, key=lambda item: dc._rectangle(item).top) if candidates else None

    def search_drivers(self, query):
        self._require_active_dispatch()
        edit = self._driver_edit()
        if edit is None:
            raise RuntimeError("分配窗口中没有找到司机输入框。")
        try:
            edit.click_input()
        except Exception:
            dc._click_control(edit)
        search_deadline = time.monotonic() + min(10, self.action_timeout)
        while time.monotonic() < search_deadline:
            search_edit = self._driver_search_edit()
            if search_edit is not None:
                edit = search_edit
                break
            time.sleep(0.15)
        if dc._control_type(edit) != "Edit":
            raise RuntimeError("展开司机下拉框后没有找到“搜索”输入框。")
        self._require_active_dispatch()
        _set_edit_text(
            edit,
            query,
            "司机",
            self._require_active_dispatch,
            self._driver_edit,
        )
        deadline = time.monotonic() + self.query_timeout
        started_at = time.monotonic()
        last_signature = None
        stable_count = 0
        while time.monotonic() < deadline:
            options = self.read_driver_options()
            if any(
                _normalize_person(option.name) == _normalize_person(query)
                for option in options
            ):
                return
            signature = tuple(option.raw_text for option in options)
            if signature and signature == last_signature:
                stable_count += 1
            else:
                last_signature = signature
                stable_count = 1 if signature else 0
            if stable_count >= 3 and time.monotonic() - started_at >= 1.2:
                return
            time.sleep(0.3)
        raise RuntimeError(f"搜索司机 {query} 后没有出现带司机 ID 的选项。")

    def read_driver_options(self):
        dialog, _ = self._dialog_controls()
        popup = self._driver_popup()
        if dialog is None and popup is None:
            return []
        scope_rect = dc._rectangle(popup or dialog)
        controls = _visible_controls(self.window)
        options = []
        self._driver_controls = {}
        option_controls = []
        for control in controls:
            raw = _collapse_spaces(dc._control_name(control))
            rect = dc._rectangle(control)
            if rect is None:
                continue
            x, y = _center(rect)
            if not _contains(scope_rect, x, y):
                continue
            if raw:
                option_controls.append((control, rect, raw))
            if "|" not in raw:
                continue
            try:
                option = parse_driver_option(raw)
            except ValueError:
                continue
            key = (_normalize_person(option.name), option.driver_id.casefold())
            if key not in self._driver_controls:
                self._driver_controls[key] = _clickable_for_text(controls, control)
                options.append(option)
        if options:
            return options

        rows = {}
        for control, rect, raw in option_controls:
            _, y = _center(rect)
            rows.setdefault(round(y / 8), []).append((rect.left, raw, control))
        option_pattern = re.compile(r"([^|]{1,100}?)\s*\|\s*([Dd][0-9A-Za-z]+)")
        for parts in rows.values():
            ordered = sorted(parts, key=lambda item: item[0])
            combined = _collapse_spaces(" ".join(value for _, value, _ in ordered))
            match = option_pattern.search(combined)
            if not match:
                continue
            try:
                option = parse_driver_option(f"{match.group(1).strip()} | {match.group(2)}")
            except ValueError:
                continue
            key = (_normalize_person(option.name), option.driver_id.casefold())
            if key not in self._driver_controls:
                anchor = next(
                    (control for _, value, control in reversed(ordered) if option.driver_id.casefold() in value.casefold()),
                    ordered[-1][2],
                )
                self._driver_controls[key] = _clickable_for_text(controls, anchor)
                options.append(option)
        return options

    def choose_driver(self, option):
        self._require_active_dispatch()
        key = (_normalize_person(option.name), option.driver_id.casefold())
        control = self._driver_controls.get(key)
        if control is None:
            self.read_driver_options()
            control = self._driver_controls.get(key)
        if control is None:
            raise RuntimeError(f"司机选项已经消失：{option.raw_text}")
        self._require_active_dispatch()
        dc._activate_control(control)
        deadline = time.monotonic() + min(5, self.action_timeout)
        while time.monotonic() < deadline:
            edit = self._driver_edit()
            values = []
            if edit is not None:
                try:
                    values.append(str(edit.get_value()))
                except Exception:
                    pass
                try:
                    values.append(str(edit.iface_value.CurrentValue))
                except Exception:
                    pass
                values.append(dc._control_name(edit))
                edit_rect = dc._rectangle(edit)
                if edit_rect is not None:
                    _, controls = self._dialog_controls()
                    values.extend(
                        dc._control_name(item)
                        for item in controls
                        if dc._rectangle(item) is not None
                        and _contains(edit_rect, *_center(dc._rectangle(item)))
                    )
            if any(
                _normalize_person(option.name) in _normalize_person(value)
                and option.driver_id.casefold() in str(value).casefold()
                for value in values
            ):
                return
            time.sleep(0.2)
        raise RuntimeError(f"点击后未能确认司机已选中：{option.raw_text}")

    def assignment_dialog_visible(self, box_code):
        self._require_active_dispatch()
        return self._assign_dialog(box_code) is not None


def wait_for_manual_confirmation(
    rule,
    page,
    result,
    timeout=900,
    verify_timeout=60,
    poll_interval=0.5,
):
    deadline = time.monotonic() + max(0, float(timeout))
    while page.assignment_dialog_visible(result.merged_box_code):
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"等待人工确认超时：{', '.join(result.matched_routes)} / "
                f"{result.merged_box_code}。队列已停止，程序没有点击“确定”。"
            )
        time.sleep(max(0, float(poll_interval)))

    verify_deadline = time.monotonic() + max(0, float(verify_timeout))
    route_codes = _rule_route_codes(rule)
    while True:
        page.search_routes(rule.route_base)
        rows = selected_route_rows(page.read_route_rows(), route_codes)
        if all(row.box_code != result.merged_box_code for row in rows):
            return
        if time.monotonic() >= verify_deadline:
            raise RuntimeError(
                f"箱号 {result.merged_box_code} 仍在“待分配”中。"
                "可能点击了“取消”或分配未成功，队列已停止。"
            )
        time.sleep(max(0, float(poll_interval)))


def _dispatch_single_rule(rule, config=None):
    config = dc._load_config(config)
    requested_routes = ", ".join(rule.route_codes)
    print(f"[1/6] 正在进入“分箱预分配 / 待分配”：{requested_routes}")
    window = _ensure_dispatch_page(config)
    query_text = rule.route_base or "全部当前待分配线路"
    print(f"[2/6] 正在查询：{query_text}")
    page = UIADispatchPage(window, rule.route_base, config)
    result = dispatch_one(
        rule,
        page,
        timeout=max(5, int(config.get("dc_dispatch_merge_timeout_seconds", 60))),
    )
    print(f"[3/6] 精确匹配线路：{', '.join(result.matched_routes)}")
    print(f"[4/6] 唯一合并箱号：{result.merged_box_code}")
    print(f"[5/6] 已选择司机：{result.driver.raw_text}")
    print("[6/6] 已停在分配窗口；请人工核对后点击“确定”。")
    return (
        f"{', '.join(result.matched_routes)}：{len(result.old_box_codes)} 个箱号合并为 "
        f"{result.merged_box_code}，已选中 {result.driver.raw_text}。"
        "请回到网页核对箱号和司机，再手动点击“确定”。"
    )


def _dispatch_rules(rules, config=None):
    if len(rules) == 1:
        return _dispatch_single_rule(rules[0], config=config)

    config = dc._load_config(config)
    total = len(rules)
    merge_timeout = max(5, int(config.get("dc_dispatch_merge_timeout_seconds", 60)))
    confirm_timeout = max(
        60,
        int(config.get("dc_dispatch_manual_confirm_timeout_seconds", 900)),
    )
    print(f"[准备] 已校验 {total} 组线路与司机，正在进入“分箱预分配 / 待分配”。")
    window = _ensure_dispatch_page(config)
    page = UIADispatchPage(window, rules[0].route_base, config)
    verify_timeout = max(page.query_timeout, 60)
    results = []

    for index, rule in enumerate(rules, start=1):
        requested_routes = ", ".join(rule.route_codes)
        print(f"[{index}/{total}] 正在处理线路：{requested_routes}")
        result = dispatch_one(rule, page, timeout=merge_timeout)
        print(
            f"[{index}/{total}] 已选中 {result.driver.raw_text}；"
            f"箱号 {result.merged_box_code}。"
        )
        print(
            f"[{index}/{total}] 请在网页核对后手动点击“确定”；"
            "成功后程序会自动继续下一组。"
        )
        wait_for_manual_confirmation(
            rule,
            page,
            result,
            timeout=confirm_timeout,
            verify_timeout=verify_timeout,
        )
        results.append(result)
        print(f"[{index}/{total}] 已确认从“待分配”移除。")

    return (
        f"批量分单完成：{len(results)} 组均已由你人工确认，"
        "且已验证目标箱号离开“待分配”。"
    )


def dispatch_route(route_code, driver_spec, config=None):
    return _dispatch_single_rule(
        parse_dispatch_rule(route_code, driver_spec),
        config=config,
    )


def dispatch_batch(route_spec, driver_spec, config=None):
    return _dispatch_rules(
        parse_dispatch_batch(route_spec, driver_spec),
        config=config,
    )


def dispatch_manifest(manifest, config=None):
    rules = parse_dispatch_manifest(manifest)
    print(f"[清单] 已识别 {len(rules)} 组分单任务：")
    for index, rule in enumerate(rules, start=1):
        print(
            f"  {index}. {', '.join(rule.route_codes)} → {rule.driver_name}"
            + (f" | {rule.driver_id}" if rule.driver_id else "")
        )
    return _dispatch_rules(rules, config=config)


if __name__ == "__main__":
    raise SystemExit("请从 iMile 报表助手运行自动分单。")
