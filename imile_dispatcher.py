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
ROUTE_CODE_PATTERN = re.compile(r"[0-9]{3,}(?: [A-Z])?")
ROUTE_FAMILY_PATTERN = re.compile(
    r"([0-9]{3,})\s*(?:所有|ALL|\*)",
    re.IGNORECASE,
)


class NoPendingRouteError(RuntimeError):
    """The query loaded completely, but none of its rows matched the rule."""


@dataclass(frozen=True)
class DispatchRule:
    route_base: str
    driver_name: str
    driver_id: str | None = None
    route_codes: tuple[str, ...] = ()
    family_bases: tuple[str, ...] = ()


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


def _canonical_route_query(value):
    return ",".join(
        normalize_route_code(part)
        for part in re.split(r"[,，]+", str(value or ""))
        if normalize_route_code(part)
    )


def _normalize_person(value):
    return _collapse_spaces(value).casefold()


def route_code_matches(base, candidate):
    base_key = normalize_route_code(base)
    candidate_key = normalize_route_code(candidate)
    if not base_key or not candidate_key:
        return False
    return re.fullmatch(rf"{re.escape(base_key)}(?: [A-Z])?", candidate_key) is not None


def route_codes_in_cell(value):
    parts = tuple(
        dict.fromkeys(
            normalize_route_code(part)
            for part in re.split(r"[,，;；、\r\n]+", str(value or ""))
            if normalize_route_code(part)
        )
    )
    if not parts or any(ROUTE_CODE_PATTERN.fullmatch(part) is None for part in parts):
        return ()
    return parts


def row_route_codes(row):
    return route_codes_in_cell(row.route_code)


def matching_route_rows(rows, base):
    return [
        row
        for row in rows
        if row_route_codes(row)
        and all(route_code_matches(base, route) for route in row_route_codes(row))
    ]


def selected_route_rows(rows, route_codes):
    selected = {normalize_route_code(value) for value in route_codes}
    return [
        row
        for row in rows
        if row_route_codes(row)
        and all(route in selected for route in row_route_codes(row))
    ]


def _parse_route_selectors(route_spec):
    raw_selectors = [
        _collapse_spaces(value)
        for value in re.split(r"[,，]+", str(route_spec or ""))
        if _collapse_spaces(value)
    ]
    if not raw_selectors:
        raise ValueError("Route Code 不能为空。")

    route_codes = []
    family_bases = []
    for selector in raw_selectors:
        family_match = ROUTE_FAMILY_PATTERN.fullmatch(selector)
        if family_match is not None:
            route_code = normalize_route_code(family_match.group(1))
            family_bases.append(route_code)
        else:
            route_code = normalize_route_code(selector)
            if ROUTE_CODE_PATTERN.fullmatch(route_code) is None:
                raise ValueError(f"Route Code 格式无效：{route_code}")
        if route_code not in route_codes:
            route_codes.append(route_code)

    route_codes = tuple(route_codes)
    family_bases = tuple(dict.fromkeys(family_bases))
    route_query = ",".join(route_codes)
    return route_query, route_codes, family_bases


def _parse_route_codes(route_spec):
    route_query, route_codes, _family_bases = _parse_route_selectors(route_spec)
    return route_query, route_codes


def parse_dispatch_rule(route_spec, driver_spec):
    route_base, route_codes, family_bases = _parse_route_selectors(route_spec)

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
    return DispatchRule(
        route_base,
        _collapse_spaces(parts[0]),
        driver_id,
        route_codes,
        family_bases,
    )


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
    selector = _manifest_route_selector(token)
    return selector[0] if selector is not None and not selector[1] else None


def _manifest_route_selector(token):
    raw = _collapse_spaces(token)
    family_match = re.fullmatch(
        r"([0-9]{3,})(?:所有|ALL|\*)",
        raw,
        re.IGNORECASE,
    )
    if family_match is not None:
        return family_match.group(1), True

    match = re.fullmatch(r"([0-9]{3,})([A-Za-z]?)", raw)
    if match is None:
        return None
    number, suffix = match.groups()
    return number + (f" {suffix.upper()}" if suffix else ""), False


def _is_all_marker(value):
    return _collapse_spaces(value).casefold() in {"所有", "all", "*"}


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
        line = re.sub(r"\s*分给\s*", " ", line, count=1).strip()
        parts = line.split()
        route_selectors = []
        cursor = 0
        while cursor < len(parts):
            selector = _manifest_route_selector(parts[cursor])
            if selector is None:
                break
            route_code, is_family = selector
            cursor += 1
            if cursor < len(parts) and _is_all_marker(parts[cursor]):
                is_family = True
                cursor += 1
            route_selectors.append(route_code + ("所有" if is_family else ""))

        driver_parts = parts[cursor:]
        if not route_selectors:
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
                parse_dispatch_rule(",".join(route_selectors), " ".join(driver_parts))
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


def _rule_display_routes(rule):
    family_bases = {
        normalize_route_code(value)
        for value in rule.family_bases
    }
    return tuple(
        f"{route_code}所有"
        if normalize_route_code(route_code) in family_bases
        else route_code
        for route_code in _rule_route_codes(rule)
    )


def _route_matches_rule(rule, route_code):
    route = normalize_route_code(route_code)
    family_bases = {
        normalize_route_code(value)
        for value in rule.family_bases
    }
    exact_codes = {
        normalize_route_code(value)
        for value in _rule_route_codes(rule)
        if normalize_route_code(value) not in family_bases
    }
    return route in exact_codes or any(
        route_code_matches(base, route)
        for base in family_bases
    )


def matching_rule_rows(rows, rule):
    return [
        row
        for row in rows
        if row_route_codes(row)
        and all(_route_matches_rule(rule, route) for route in row_route_codes(row))
    ]


def _single_box(rows, rule, expected_routes=None, expected_waybills=None):
    matches = matching_rule_rows(rows, rule)
    if not matches or any(not row.box_code for row in matches):
        return None
    if expected_waybills is not None:
        counts = [row.waybill_count for row in matches]
        if any(value is None for value in counts) or sum(counts) != expected_waybills:
            return None
    if expected_routes is not None:
        current_routes = {
            route
            for row in matches
            for route in row_route_codes(row)
        }
        if set(expected_routes) != current_routes:
            return None
    box_codes = {row.box_code for row in matches}
    return next(iter(box_codes)) if len(box_codes) == 1 else None


def dispatch_one(rule, page, timeout=45, initial_rows=None):
    if initial_rows is None:
        loaded_rows = page.search_routes(rule.route_base)
        rows = (
            list(loaded_rows)
            if loaded_rows is not None
            else page.read_route_rows()
        )
    else:
        rows = list(initial_rows)
    route_codes = _rule_route_codes(rule)
    matches = matching_rule_rows(rows, rule)
    unsafe_mixed_rows = [
        row
        for row in rows
        if row_route_codes(row)
        and any(_route_matches_rule(rule, route) for route in row_route_codes(row))
        and not all(_route_matches_rule(rule, route) for route in row_route_codes(row))
    ]
    if unsafe_mixed_rows:
        details = "；".join(
            f"{row.box_code}: {row.route_code}"
            for row in unsafe_mixed_rows
        )
        raise RuntimeError(
            "查询结果中目标线路与未请求线路已混在同一箱号，无法安全拆分勾选："
            f"{details}"
        )
    if not matches:
        requested = ", ".join(route_codes)
        raise NoPendingRouteError(
            f"没有找到所选 Route Code（{requested}）的待分配箱号。"
        )
    if any(not row.box_code for row in matches):
        raise RuntimeError(f"Route Code {rule.route_base} 的结果缺少箱号，已停止操作。")

    matched_routes = tuple(
        dict.fromkeys(
            route
            for row in matches
            for route in row_route_codes(row)
        )
    )
    old_box_codes = tuple(dict.fromkeys(row.box_code for row in matches))
    expected_routes = set(matched_routes)
    counts = [row.waybill_count for row in matches]
    expected_waybills = sum(counts) if counts and all(value is not None for value in counts) else None
    merged_box_code = _single_box(
        matches,
        rule,
        expected_routes=expected_routes,
        expected_waybills=expected_waybills,
    )
    if merged_box_code is None:
        page.select_rows([row.row_key for row in matches])
        page.merge_selected()
        deadline = time.monotonic() + max(0, float(timeout))
        started_at = time.monotonic()
        refresh_attempted = False
        last_read_error = None
        while True:
            try:
                refreshed = page.read_route_rows()
                last_read_error = None
            except RuntimeError as exc:
                # React briefly removes or rebuilds table controls after merge.
                # A transient incomplete snapshot must not be treated as the
                # final merged state.
                refreshed = []
                last_read_error = exc
            merged_box_code = _single_box(
                refreshed,
                rule,
                expected_routes=expected_routes,
                expected_waybills=expected_waybills,
            )
            if merged_box_code is not None:
                break
            now = time.monotonic()
            refresh_grace = min(2.0, max(0.5, float(timeout) / 4))
            if (
                not refresh_attempted
                and now - started_at >= refresh_grace
                and hasattr(page, "refresh_routes")
            ):
                refresh_attempted = True
                remaining = max(0.1, deadline - now)
                try:
                    refreshed = page.refresh_routes(timeout=remaining)
                except RuntimeError as exc:
                    raise RuntimeError(
                        f"Route Code {rule.route_base} 合并后刷新结果失败，"
                        f"未执行司机分配：{exc}"
                    ) from exc
                merged_box_code = _single_box(
                    refreshed,
                    rule,
                    expected_routes=expected_routes,
                    expected_waybills=expected_waybills,
                )
                if merged_box_code is not None:
                    break
            if now >= deadline:
                detail = (
                    f"；最后一次读取错误：{last_read_error}"
                    if last_read_error is not None
                    else ""
                )
                raise RuntimeError(
                    f"Route Code {rule.route_base} 合并后仍未收敛为唯一箱号，"
                    f"未执行司机分配{detail}。"
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

    expected = _collapse_spaces(value)
    errors = []
    writers = (
        lambda: control.set_edit_text(value),
        lambda: control.iface_value.SetValue(value),
    )
    for write_value in writers:
        if guard is not None:
            guard()
        try:
            write_value()
        except Exception as exc:
            errors.append(exc)
            continue

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

    detail = f"：{errors[-1]}" if errors else ""
    raise RuntimeError(
        f"写入{field_name}后无法完整读回“{value}”，已停止操作{detail}"
    )


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
        self._last_loaded_query = None
        self._last_result_signature = None

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
        controls = _visible_controls(self.window)
        try:
            box_header, _count_header, _route_header, operation_header = self._headers()
            box_rect = dc._rectangle(box_header)
            operation_rect = dc._rectangle(operation_header)
            table_left = box_rect.left - max(120, _rect_width(box_rect))
            table_right = operation_rect.right
            table_top = max(box_rect.bottom, operation_rect.bottom)
        except RuntimeError:
            return False

        for control in controls:
            class_key = dc._control_class(control).casefold()
            is_loading = dc._control_type(control) == "ProgressBar" or any(
                marker in class_key for marker in ("circularprogress", "spinner", "loading")
            )
            rect = dc._rectangle(control)
            if (
                is_loading
                and rect is not None
                and table_left <= _center(rect)[0] <= table_right
                and _center(rect)[1] >= table_top
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

    def _current_route_query_matches(self, edit, base):
        expected = _canonical_route_query(base)
        return bool(expected) and any(
            _canonical_route_query(value) == expected
            for value in _control_values(edit)
        )

    def _existing_stable_result(self, timeout=0.8):
        deadline = time.monotonic() + max(0, float(timeout))
        last_signature = None
        stable_count = 0
        while time.monotonic() < deadline:
            self._require_active_dispatch()
            if self._is_loading():
                last_signature = None
                stable_count = 0
                time.sleep(0.15)
                continue
            try:
                signature = self._stable_result_signature()
            except RuntimeError:
                return None
            if signature is None:
                return None
            if signature == last_signature:
                stable_count += 1
            else:
                last_signature = signature
                stable_count = 1
            if stable_count >= 2:
                try:
                    return signature, self.read_route_rows()
                except RuntimeError:
                    return None
            time.sleep(0.15)
        return None

    def _click_query(self):
        query_deadline = time.monotonic() + min(5, self.action_timeout)
        while time.monotonic() < query_deadline:
            self._require_active_dispatch()
            if _activate_text_action(self.window, QUERY_KEYS, prefer_right=True):
                return
            time.sleep(0.2)
        raise RuntimeError("没有找到“查询”按钮。")

    def _wait_for_query_results(
        self,
        old_signature,
        require_transition,
        timeout=None,
    ):
        deadline = time.monotonic() + (
            self.action_timeout if timeout is None else max(0.1, float(timeout))
        )
        started_at = time.monotonic()
        last_signature = None
        stable_count = 0
        saw_loading = False
        repeated_error = None
        repeated_error_count = 0
        while time.monotonic() < deadline:
            time.sleep(0.25)
            self._require_active_dispatch()
            if self._is_loading():
                saw_loading = True
                last_signature = None
                stable_count = 0
                repeated_error = None
                repeated_error_count = 0
                continue
            try:
                signature = self._stable_result_signature()
            except RuntimeError as exc:
                error_text = str(exc)
                if error_text == repeated_error:
                    repeated_error_count += 1
                else:
                    repeated_error = error_text
                    repeated_error_count = 1
                last_signature = None
                stable_count = 0
                if (
                    repeated_error_count >= 5
                    and time.monotonic() - started_at >= 2
                ):
                    raise RuntimeError(
                        f"查询结果持续无法安全读取：{exc}"
                    ) from exc
                continue
            repeated_error = None
            repeated_error_count = 0
            if signature is None:
                last_signature = None
                stable_count = 0
                continue
            if signature == last_signature:
                stable_count += 1
            else:
                last_signature = signature
                stable_count = 1
            transitioned = (
                not require_transition
                or saw_loading
                or (
                    old_signature is not None
                    and signature != old_signature
                )
            )
            if (
                stable_count >= 2
                and transitioned
                and time.monotonic() - started_at >= 0.8
            ):
                try:
                    rows = self.read_route_rows()
                except RuntimeError:
                    last_signature = None
                    stable_count = 0
                else:
                    self._last_result_signature = signature
                    return rows
        if require_transition and old_signature is not None and not saw_loading:
            raise RuntimeError(
                "点击查询后没有观察到加载状态或结果变化；"
                "为避免把上一条线路的旧结果当成新结果，已停止操作。"
            )
        raise RuntimeError("查询结果没有完整、稳定地加载。")

    def search_routes(self, base):
        self._require_active_dispatch()
        edit = _find_route_edit(self.window)
        if edit is None:
            raise RuntimeError("没有找到 Route Code 输入框。")
        same_query = self._current_route_query_matches(edit, base)
        canonical_query = _canonical_route_query(base)
        trusted_same_query = (
            same_query
            and self._last_loaded_query == canonical_query
        )
        if trusted_same_query:
            existing = self._existing_stable_result()
            if existing is not None:
                signature, rows = existing
                if signature == self._last_result_signature:
                    self.route_base = base
                    return rows

        try:
            old_signature = (
                None if self._is_loading() else self._stable_result_signature()
            )
        except RuntimeError:
            old_signature = None

        if not same_query:
            _set_edit_text(
                edit,
                base,
                "Route Code",
                self._require_active_dispatch,
                lambda: _find_route_edit(self.window),
            )
        self.route_base = base
        self._click_query()
        rows = self._wait_for_query_results(
            old_signature,
            require_transition=not trusted_same_query,
            timeout=self.query_timeout,
        )
        self._last_loaded_query = canonical_query
        return rows

    def refresh_routes(self, timeout=None):
        """Refresh the current query once without rewriting the input field."""
        self._require_active_dispatch()
        edit = _find_route_edit(self.window)
        if edit is None:
            raise RuntimeError("没有找到 Route Code 输入框。")
        if not self._current_route_query_matches(edit, self.route_base):
            raise RuntimeError(
                "Route Code 输入框已被修改；为避免刷新错误线路，已停止操作。"
            )
        try:
            old_signature = (
                None if self._is_loading() else self._stable_result_signature()
            )
        except RuntimeError:
            old_signature = None
        self._click_query()
        rows = self._wait_for_query_results(
            old_signature,
            require_transition=old_signature is not None,
            timeout=timeout,
        )
        self._last_loaded_query = _canonical_route_query(self.route_base)
        return rows

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
        operation_x, _ = _center(operation_rect)
        box_left = box_x - (count_x - box_x) / 2
        box_right = (box_x + count_x) / 2
        count_left = box_right
        count_right = (count_x + route_x) / 2
        route_left = count_right
        route_right = min(
            (route_x + operation_x) / 2,
            route_x + (route_x - count_x) / 2,
        )

        checkbox_candidates = []
        for control in controls:
            rect = dc._rectangle(control)
            if rect is None or rect.top <= header_bottom:
                continue
            x, y = _center(rect)
            class_key = dc._control_class(control).casefold()
            if x >= box_left or not (
                dc._control_type(control) == "CheckBox"
                or "checkbox" in class_key
            ):
                continue
            checkbox_candidates.append((y, control, rect))

        checkbox_clusters = []
        for candidate in sorted(checkbox_candidates, key=lambda item: item[0]):
            if (
                checkbox_clusters
                and abs(
                    candidate[0]
                    - sum(item[0] for item in checkbox_clusters[-1])
                    / len(checkbox_clusters[-1])
                )
                <= 12
            ):
                checkbox_clusters[-1].append(candidate)
            else:
                checkbox_clusters.append([candidate])

        checkbox_rows = []
        for cluster in checkbox_clusters:
            y = sum(item[0] for item in cluster) / len(cluster)
            _candidate_y, checkbox, _candidate_rect = max(
                cluster,
                key=lambda item: (
                    dc._control_type(item[1]) == "CheckBox",
                    -_rect_area(item[2]),
                ),
            )
            checkbox_rows.append((checkbox, y))

        parsed = []
        for index, (checkbox, y) in enumerate(checkbox_rows):
            previous_y = checkbox_rows[index - 1][1] if index else None
            next_y = (
                checkbox_rows[index + 1][1]
                if index + 1 < len(checkbox_rows)
                else None
            )
            if previous_y is None:
                half_height = (next_y - y) / 2 if next_y is not None else 40
                row_top = max(header_bottom, y - max(30, half_height))
            else:
                row_top = (previous_y + y) / 2
            if next_y is None:
                half_height = (y - previous_y) / 2 if previous_y is not None else 40
                row_bottom = y + max(30, half_height)
            else:
                row_bottom = (y + next_y) / 2

            route_codes = []
            box_candidates = []
            count_candidates = []
            aligned_controls = []
            for control in controls:
                rect = dc._rectangle(control)
                if rect is None:
                    continue
                x, control_y = _center(rect)
                if not row_top <= control_y < row_bottom:
                    continue
                aligned_controls.append((control_y, x, control, rect))

            for control_y, x, control, rect in sorted(
                aligned_controls,
                key=lambda item: (item[0], item[1], _rect_area(item[3])),
            ):
                raw_name = dc._control_name(control)
                name = _collapse_spaces(raw_name)
                if route_left <= x < route_right:
                    for route_code in route_codes_in_cell(raw_name):
                        if route_code not in route_codes:
                            route_codes.append(route_code)
                if box_left <= x < box_right and name and name.casefold() != "boxcode":
                    if re.fullmatch(r"[0-9A-Z_-]{5,}", name.upper()):
                        box_candidates.append((abs(x - box_x), name))
                if count_left <= x < count_right and re.fullmatch(r"[\d,]+", name):
                    count_candidates.append((abs(x - count_x), int(name.replace(",", ""))))
            box_code = min(box_candidates, default=(0, ""), key=lambda item: item[0])[1]
            waybill_count = min(count_candidates, default=(0, None), key=lambda item: item[0])[1]
            if not route_codes:
                continue
            route_code = ",".join(route_codes)
            row_key = f"{box_code}\x1f{normalize_route_code(route_code)}\x1f{round(y)}"
            parsed.append(_UIRow(BoxRow(row_key, route_code, box_code, waybill_count), y, checkbox))

        self._rows = {
            row.value.row_key: row
            for row in sorted(parsed, key=lambda item: item.y)
        }
        if self._rows and any(row.value.waybill_count is None for row in self._rows.values()):
            raise RuntimeError("有表格行未识别到运单数，无法安全确认合并完整性，未执行选择。")
        counts = self._result_counts()
        if counts is not None and counts[1] != len(self._rows):
            raise RuntimeError(
                f"查询返回 {counts[1]} 行，但当前识别到 {len(self._rows)} 行。"
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
        window_rect = dc._rectangle(self.window)
        window_area = _rect_area(window_rect) if window_rect is not None else 0
        candidates = []
        for control in _visible_controls(self.window):
            rect = dc._rectangle(control)
            if rect is None:
                continue
            class_key = dc._control_class(control).casefold()
            control_type = dc._control_type(control)
            if not (
                control_type == "Window"
                or any(marker in class_key for marker in ("dialog", "modal"))
            ):
                continue
            area = _rect_area(rect)
            if area < 20_000 or (window_area and area >= window_area * 0.9):
                continue
            candidates.append(control)
        return sorted(candidates, key=lambda item: _rect_area(dc._rectangle(item)))

    def _assign_dialog(self, box_code=None):
        expected_box = str(box_code or getattr(self, "_assign_box_code", "")).strip()
        controls = _visible_controls(self.window)
        valid = []
        for dialog in self._dialogs():
            dialog_rect = dc._rectangle(dialog)
            contained = [
                control
                for control in controls
                if dc._rectangle(control) is not None
                and _contains(dialog_rect, *_center(dc._rectangle(control)))
            ]
            contained_keys = [
                dc._text_key(dc._control_name(control))
                for control in contained
                if dc._control_name(control)
            ]
            if any(
                supplier_key in control_key
                for control_key in contained_keys
                for supplier_key in SUPPLIER_KEYS
            ):
                continue
            title_controls = [
                control
                for control in contained
                if dc._text_key(dc._control_name(control)) in ASSIGN_KEYS
            ]
            if dc._text_key(dc._control_name(dialog)) in ASSIGN_KEYS:
                title_controls.append(dialog)
            driver_labels = [
                control
                for control in contained
                if dc._text_key(dc._control_name(control)) in DRIVER_LABEL_KEYS
            ]
            if not title_controls or not driver_labels:
                continue

            box_controls = []
            if expected_box:
                box_pattern = re.compile(
                    rf"(?<![0-9A-Z_-]){re.escape(expected_box.upper())}"
                    r"(?![0-9A-Z_-])"
                )
                box_controls = [
                    control
                    for control in contained
                    if box_pattern.search(dc._control_name(control).upper())
                ]
                if not box_controls:
                    continue

            edits = [
                control
                for control in contained
                if dc._control_type(control) in {"Edit", "ComboBox"}
            ]
            field_pairs = []
            for label in driver_labels:
                label_rect = dc._rectangle(label)
                for edit in edits:
                    edit_rect = dc._rectangle(edit)
                    if (
                        edit_rect.top >= label_rect.top
                        and edit_rect.top <= label_rect.bottom + 120
                    ):
                        field_pairs.append((label, edit))
            if not field_pairs:
                continue

            title_top = min(
                dc._rectangle(control).top
                for control in title_controls
                if dc._rectangle(control) is not None
            )
            driver_top = min(
                dc._rectangle(label).top
                for label, _edit in field_pairs
            )
            if title_top >= driver_top:
                continue
            if box_controls:
                box_top = min(dc._rectangle(control).top for control in box_controls)
                if not title_top <= box_top <= driver_top:
                    continue
            valid.append(dialog)

        return (
            min(valid, key=lambda item: _rect_area(dc._rectangle(item)))
            if valid
            else None
        )

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
            self._driver_search_edit,
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
    while True:
        rows = matching_rule_rows(page.read_route_rows(), rule)
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
    requested_routes = ", ".join(_rule_display_routes(rule))
    print(f"[1/6] 正在进入“分箱预分配 / 待分配”：{requested_routes}")
    window = _ensure_dispatch_page(config)
    query_text = rule.route_base or "全部当前待分配线路"
    print(f"[2/6] 正在查询：{query_text}")
    page = UIADispatchPage(window, rule.route_base, config)
    try:
        result = dispatch_one(
            rule,
            page,
            timeout=max(5, int(config.get("dc_dispatch_merge_timeout_seconds", 60))),
        )
    except NoPendingRouteError:
        print(f"[SKIPPED] {requested_routes} 当前没有匹配的待分配箱号。")
        return f"{requested_routes} 当前没有匹配的待分配箱号，已安全跳过。"
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
    skipped = []

    for index, rule in enumerate(rules, start=1):
        requested_routes = ", ".join(_rule_display_routes(rule))
        print(f"[{index}/{total}] 正在处理线路：{requested_routes}")
        try:
            result = dispatch_one(rule, page, timeout=merge_timeout)
        except NoPendingRouteError:
            skipped.append(rule)
            print(
                f"[SKIPPED {index}/{total}] {requested_routes} "
                "当前没有匹配的待分配箱号，继续下一组。"
            )
            continue
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

    if not results:
        return (
            f"批量分单检查完成：0 组需要确认，{len(skipped)} 组当前无待分配结果，"
            "均已安全跳过。"
        )
    return (
        f"批量分单完成：{len(results)} 组已由你人工确认，"
        f"{len(skipped)} 组当前无待分配结果并已跳过；"
        "已验证确认箱号离开“待分配”。"
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
            f"  {index}. {', '.join(_rule_display_routes(rule))} → {rule.driver_name}"
            + (f" | {rule.driver_id}" if rule.driver_id else "")
        )
    return _dispatch_rules(rules, config=config)


if __name__ == "__main__":
    raise SystemExit("请从 iMile 报表助手运行自动分单。")
