import unittest
from types import SimpleNamespace
from unittest import mock

import imile_dispatcher as dispatcher


class FakeDispatchPage:
    def __init__(self, route_snapshots, driver_options=(), verify_result=True):
        self._route_snapshots = [list(rows) for rows in route_snapshots]
        self._route_read_index = 0
        self._driver_options = list(driver_options)
        self.verify_result = verify_result

        self.route_searches = []
        self.selected_row_keys = []
        self.merge_count = 0
        self.opened_box_codes = []
        self.driver_searches = []
        self.chosen_drivers = []
        self.confirm_count = 0
        self.verified_assignments = []

    def search_routes(self, base):
        self.route_searches.append(base)

    def read_route_rows(self):
        if not self._route_snapshots:
            return []
        index = min(self._route_read_index, len(self._route_snapshots) - 1)
        self._route_read_index += 1
        return list(self._route_snapshots[index])

    def select_rows(self, row_keys):
        self.selected_row_keys.append(list(row_keys))

    def merge_selected(self):
        self.merge_count += 1

    def open_assign(self, box_code):
        self.opened_box_codes.append(box_code)

    def search_drivers(self, query):
        self.driver_searches.append(query)

    def read_driver_options(self):
        return list(self._driver_options)

    def choose_driver(self, option):
        self.chosen_drivers.append(option)

    def confirm_assignment(self):
        self.confirm_count += 1

    def verify_assignment(self, box_code, option):
        self.verified_assignments.append((box_code, option))
        return self.verify_result


class ManualConfirmationPage:
    def __init__(self, dialog_states, route_snapshots):
        self._dialog_states = list(dialog_states)
        self._route_snapshots = [list(rows) for rows in route_snapshots]
        self.route_searches = []

    def assignment_dialog_visible(self, _box_code):
        if not self._dialog_states:
            return False
        if len(self._dialog_states) == 1:
            return self._dialog_states[0]
        return self._dialog_states.pop(0)

    def search_routes(self, base):
        self.route_searches.append(base)

    def read_route_rows(self):
        if not self._route_snapshots:
            return []
        if len(self._route_snapshots) == 1:
            return list(self._route_snapshots[0])
        return list(self._route_snapshots.pop(0))


def box_row(row_key, route_code, box_code, waybill_count=None):
    return dispatcher.BoxRow(
        row_key=row_key,
        route_code=route_code,
        box_code=box_code,
        waybill_count=waybill_count,
    )


def driver_option(name, driver_id):
    return dispatcher.DriverOption(
        name=name,
        driver_id=driver_id,
        raw_text=f"{name} | {driver_id}",
    )


class RouteCodeMatchingTests(unittest.TestCase):
    def test_301_family_matches_only_exact_code_or_single_letter_variant(self):
        for candidate in ("301", " 301 ", "301 S", "301 A", "301 B", "301 a"):
            with self.subTest(candidate=candidate):
                self.assertTrue(dispatcher.route_code_matches("301", candidate))

        for candidate in (
            "3010",
            "1301",
            "301S",
            "301-A",
            "301 AA",
            "301 A EXTRA",
            "",
            None,
        ):
            with self.subTest(candidate=candidate):
                self.assertFalse(dispatcher.route_code_matches("301", candidate))

    def test_matching_route_rows_excludes_substring_matches(self):
        rows = [
            box_row("base", "301", "B1"),
            box_row("a", "301 A", "B2"),
            box_row("s", "301 S", "B3"),
            box_row("ten", "3010", "WRONG"),
            box_row("prefix", "1301", "WRONG"),
        ]

        matched = dispatcher.matching_route_rows(rows, "301")

        self.assertEqual([row.row_key for row in matched], ["base", "a", "s"])

    def test_composite_route_cell_is_split_and_normalized(self):
        self.assertEqual(
            dispatcher.route_codes_in_cell("203, 203 B，203 A；203 S"),
            ("203", "203 B", "203 A", "203 S"),
        )
        self.assertEqual(
            dispatcher.route_codes_in_cell("203\n203 B、203 A"),
            ("203", "203 B", "203 A"),
        )
        self.assertEqual(dispatcher.route_codes_in_cell("203A"), ())


class DriverResolutionTests(unittest.TestCase):
    def test_parse_dispatch_rule_accepts_name_and_stable_driver_id(self):
        rule = dispatcher.parse_dispatch_rule(
            " 301 ",
            " Yang Jun-feng | D21023280101 ",
        )

        self.assertEqual(rule.route_base, "301")
        self.assertEqual(rule.driver_name, "Yang Jun-feng")
        self.assertEqual(rule.driver_id, "D21023280101")
        self.assertEqual(rule.route_codes, ("301",))

    def test_parse_dispatch_rule_accepts_only_explicit_route_variants(self):
        rule = dispatcher.parse_dispatch_rule(
            "404, 404 B，404 S",
            "Yang Jun-feng | D21023280101",
        )

        self.assertEqual(rule.route_base, "404,404 B,404 S")
        self.assertEqual(rule.route_codes, ("404", "404 B", "404 S"))
        self.assertEqual(rule.family_bases, ())

    def test_parse_dispatch_rule_accepts_all_suffix_variants(self):
        rule = dispatcher.parse_dispatch_rule(
            "202, 301 所有",
            "Travis",
        )

        self.assertEqual(rule.route_base, "202,301")
        self.assertEqual(rule.route_codes, ("202", "301"))
        self.assertEqual(rule.family_bases, ("301",))

    def test_parse_dispatch_rule_accepts_all_marker_aliases(self):
        for route_spec in ("301ALL", "301*"):
            with self.subTest(route_spec=route_spec):
                rule = dispatcher.parse_dispatch_rule(route_spec, "Travis")
                self.assertEqual(rule.route_base, "301")
                self.assertEqual(rule.route_codes, ("301",))
                self.assertEqual(rule.family_bases, ("301",))

    def test_parse_dispatch_rule_does_not_use_short_prefix_for_mixed_routes(self):
        rule = dispatcher.parse_dispatch_rule(
            "309, 310, 311, 312",
            "马德华1",
        )

        self.assertEqual(rule.route_base, "309,310,311,312")
        self.assertEqual(rule.route_codes, ("309", "310", "311", "312"))

    def test_parse_dispatch_rule_requires_at_least_three_digits(self):
        for route_spec in ("3", "31", "A01", "501B"):
            with self.subTest(route_spec=route_spec):
                with self.assertRaises(ValueError):
                    dispatcher.parse_dispatch_rule(route_spec, "马德华1")

    def test_parse_dispatch_batch_pairs_semicolon_groups(self):
        rules = dispatcher.parse_dispatch_batch(
            "201;302,303;401;406;604;606;605;404,404 B,404 S;202,301",
            "Yang Jun;宋修丞;冯卫周3;冯卫周2;吴良梅;吴良梅2;冯卫周;戴女士;Travis",
        )

        self.assertEqual(len(rules), 9)
        self.assertEqual(rules[0].route_codes, ("201",))
        self.assertEqual(rules[0].driver_name, "Yang Jun")
        self.assertEqual(rules[1].route_codes, ("302", "303"))
        self.assertEqual(rules[7].route_codes, ("404", "404 B", "404 S"))
        self.assertEqual(rules[8].route_codes, ("202", "301"))
        self.assertEqual(rules[8].driver_name, "Travis")

    def test_parse_dispatch_batch_accepts_chinese_semicolon_and_newline(self):
        rules = dispatcher.parse_dispatch_batch(
            "201；302,303\n401",
            "Yang Jun；宋修丞\n冯卫周3",
        )

        self.assertEqual(
            [rule.route_codes for rule in rules],
            [("201",), ("302", "303"), ("401",)],
        )

    def test_parse_dispatch_batch_requires_matching_group_counts(self):
        with self.assertRaisesRegex(ValueError, "线路共 2 组，司机共 1 组"):
            dispatcher.parse_dispatch_batch("201;302", "Yang Jun")

    def test_parse_dispatch_manifest_accepts_user_paste_and_normalizes_suffixes(self):
        rules = dispatcher.parse_dispatch_manifest(
            """201 Yang Jun
302 303 宋修丞
401 冯卫周3
406 冯卫周2
604 吴良梅
606 吴良梅2
605 冯卫周
404 404B 404S 戴女士
202 301 Travis"""
        )

        self.assertEqual(len(rules), 9)
        self.assertEqual(rules[0].route_codes, ("201",))
        self.assertEqual(rules[0].driver_name, "Yang Jun")
        self.assertEqual(rules[1].route_codes, ("302", "303"))
        self.assertEqual(rules[7].route_codes, ("404", "404 B", "404 S"))
        self.assertEqual(rules[7].driver_name, "戴女士")
        self.assertEqual(rules[8].route_codes, ("202", "301"))
        self.assertEqual(rules[8].driver_name, "Travis")

    def test_parse_dispatch_manifest_accepts_name_and_driver_id(self):
        rules = dispatcher.parse_dispatch_manifest(
            "301 Yang Jun-feng | D21023280101"
        )

        self.assertEqual(rules[0].driver_name, "Yang Jun-feng")
        self.assertEqual(rules[0].driver_id, "D21023280101")

    def test_parse_dispatch_manifest_accepts_all_and_natural_assign_wording(self):
        rules = dispatcher.parse_dispatch_manifest(
            "203 所有分给rowan\n206 210 分给史毅"
        )

        self.assertEqual(rules[0].route_base, "203")
        self.assertEqual(rules[0].route_codes, ("203",))
        self.assertEqual(rules[0].family_bases, ("203",))
        self.assertEqual(rules[0].driver_name, "rowan")
        self.assertEqual(rules[1].route_codes, ("206", "210"))
        self.assertEqual(rules[1].driver_name, "史毅")

    def test_parse_dispatch_manifest_rejects_spaced_route_suffix(self):
        with self.assertRaisesRegex(ValueError, "字母线路后缀请紧贴数字"):
            dispatcher.parse_dispatch_manifest("404 404 B 戴女士")

    def test_parse_dispatch_manifest_requires_driver_on_every_line(self):
        with self.assertRaisesRegex(ValueError, "第 2 行缺少司机"):
            dispatcher.parse_dispatch_manifest("201 Yang Jun\n302 303")

    def test_parse_driver_option_splits_name_and_id(self):
        option = dispatcher.parse_driver_option(
            "  Yang Jun-feng   |   D21023280101  "
        )

        self.assertEqual(option.name, "Yang Jun-feng")
        self.assertEqual(option.driver_id, "D21023280101")

    def test_name_only_chooses_first_displayed_search_result(self):
        first = driver_option("Travis North", "D21024948601")
        second = driver_option("Travis", "D21023280101")
        rule = dispatcher.DispatchRule("301", "Travis")

        resolved = dispatcher.resolve_driver([first, second], rule)

        self.assertEqual(resolved.driver_id, "D21024948601")

    def test_name_only_chooses_first_result_even_for_partial_match(self):
        options = [
            driver_option("Yang Jun-feng", "D21023280101"),
            driver_option("yang jun2-feng", "D21024948601"),
        ]
        rule = dispatcher.DispatchRule("301", "yang jun")

        resolved = dispatcher.resolve_driver(options, rule)

        self.assertEqual(resolved.driver_id, "D21023280101")

    def test_driver_id_still_requires_exact_name_and_id(self):
        options = [
            driver_option("Yang Jun-feng", "D21023280101"),
            driver_option("Yang Jun-feng", "D99999999999"),
        ]

        with self.assertRaisesRegex(RuntimeError, "没有找到精确司机"):
            dispatcher.resolve_driver(
                options,
                dispatcher.DispatchRule("301", "Yang Jun-feng", "D00000000000"),
            )

        resolved = dispatcher.resolve_driver(
            options,
            dispatcher.DispatchRule(
                "301",
                "Yang Jun-feng",
                "D21023280101",
            ),
        )
        self.assertEqual(resolved.driver_id, "D21023280101")


class EditInputTests(unittest.TestCase):
    class FakeEdit:
        def __init__(self):
            self.value = ""
            self.set_calls = []
            self.iface_value = self

        @property
        def CurrentValue(self):
            return self.value

        def click_input(self):
            return None

        def has_keyboard_focus(self):
            return True

        def set_edit_text(self, value):
            self.set_calls.append(value)
            self.value = value

        def SetValue(self, value):
            self.value = value

        def get_value(self):
            return self.value

        def type_keys(self, *_args, **_kwargs):
            raise AssertionError("character-by-character typing must not be used")

    def test_set_edit_text_writes_complete_value_once(self):
        edit = self.FakeEdit()

        dispatcher._set_edit_text(
            edit,
            "404,404 B,404 S",
            "Route Code",
            refetch=lambda: edit,
        )

        self.assertEqual(edit.set_calls, ["404,404 B,404 S"])
        self.assertEqual(edit.value, "404,404 B,404 S")


class DialogRecognitionTests(unittest.TestCase):
    class Rect:
        def __init__(self, left, top, right, bottom):
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

    class Control:
        def __init__(
            self,
            name,
            control_type,
            rect,
            class_name="",
            children=(),
        ):
            self._name = name
            self._rect = rect
            self._children = list(children)
            self.element_info = SimpleNamespace(
                class_name=class_name,
                control_type=control_type,
                automation_id="",
            )

        def window_text(self):
            return self._name

        def rectangle(self):
            return self._rect

        def is_visible(self):
            return True

        def descendants(self):
            return list(self._children)

    def make_page(self, include_supplier=False, box_text="BOX203"):
        rect = self.Rect
        children = [
            self.Control(
                "分配",
                "Text",
                rect(120, 120, 180, 150),
            ),
            self.Control(
                "当前箱号",
                "Text",
                rect(120, 180, 210, 210),
            ),
            self.Control(
                box_text,
                "Text",
                rect(220, 180, 340, 210),
            ),
            self.Control(
                "分配司机",
                "Text",
                rect(120, 250, 220, 280),
            ),
            self.Control(
                "请选择",
                "ComboBox",
                rect(120, 285, 500, 330),
            ),
        ]
        if include_supplier:
            children.append(
                self.Control(
                    "分配供应商",
                    "Text",
                    rect(120, 350, 260, 380),
                )
            )
        modal = self.Control(
            "",
            "Group",
            rect(100, 100, 600, 600),
            class_name="z-imd-modal",
        )
        window = self.Control(
            "",
            "Window",
            rect(0, 0, 1000, 1000),
            children=[modal, *children],
        )
        return dispatcher.UIADispatchPage(window, "203", {}), modal

    def test_nonstandard_modal_group_is_recognized(self):
        page, modal = self.make_page()

        self.assertIs(page._assign_dialog("BOX203"), modal)

    def test_supplier_modal_and_box_prefix_are_rejected(self):
        supplier_page, _ = self.make_page(include_supplier=True)
        prefix_page, _ = self.make_page(box_text="BOX2039")

        self.assertIsNone(supplier_page._assign_dialog("BOX203"))
        self.assertIsNone(prefix_page._assign_dialog("BOX203"))


class DispatchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.rule = dispatcher.DispatchRule(
            "301",
            "Yang Jun-feng",
            "D21023280101",
            ("301", "301 A", "301 B"),
        )
        self.driver = driver_option("Yang Jun-feng", "D21023280101")

    def test_merge_refreshes_rows_and_assigns_using_new_box_code(self):
        before = [
            box_row("base", "301", "B1"),
            box_row("a", "301 A", "B2"),
            box_row("b", "301 B", "B3"),
            box_row("wrong", "3010", "B3010"),
        ]
        stale_after_click = list(before)
        merged = [
            box_row("merged", "301,301 A,301 B", "M900"),
            box_row("wrong", "3010", "B3010"),
        ]
        page = FakeDispatchPage(
            [before, stale_after_click, merged],
            [self.driver],
        )

        dispatcher.dispatch_one(self.rule, page, timeout=1.0)

        self.assertEqual(page.route_searches, ["301"])
        self.assertEqual(page.selected_row_keys, [["base", "a", "b"]])
        self.assertEqual(page.merge_count, 1)
        self.assertEqual(page.opened_box_codes, ["M900"])
        self.assertEqual(page.driver_searches, ["Yang Jun-feng"])
        self.assertEqual(page.chosen_drivers, [self.driver])
        self.assertEqual(page.confirm_count, 0)
        self.assertEqual(page.verified_assignments, [])

    def test_already_single_box_skips_merge_for_safe_retry(self):
        already_merged = [
            box_row("base", "301", "M900"),
            box_row("a", "301 A", "M900"),
            box_row("wrong", "3010", "B3010"),
        ]
        page = FakeDispatchPage([already_merged], [self.driver])

        dispatcher.dispatch_one(self.rule, page, timeout=0.2)

        self.assertEqual(page.selected_row_keys, [])
        self.assertEqual(page.merge_count, 0)
        self.assertEqual(page.opened_box_codes, ["M900"])
        self.assertEqual(page.confirm_count, 0)

    def test_unconverged_merge_never_opens_assignment(self):
        before = [
            box_row("base", "301", "B1"),
            box_row("a", "301 A", "B2"),
        ]
        still_separate = [
            box_row("base-new", "301", "M1"),
            box_row("a-new", "301 A", "M2"),
        ]
        page = FakeDispatchPage([before, still_separate], [self.driver])

        with self.assertRaises(RuntimeError):
            dispatcher.dispatch_one(self.rule, page, timeout=0.02)

        self.assertEqual(page.merge_count, 1)
        self.assertEqual(page.opened_box_codes, [])
        self.assertEqual(page.chosen_drivers, [])
        self.assertEqual(page.confirm_count, 0)

    def test_partial_merged_snapshot_waits_for_full_waybill_total(self):
        before = [
            box_row("base", "301", "B1", 10),
            box_row("a", "301 A", "B2", 20),
            box_row("b", "301 B", "B3", 30),
        ]
        partial = [box_row("partial", "301", "M900", 10)]
        fully_merged = [
            box_row("merged", "301,301 A,301 B", "M900", 60)
        ]
        page = FakeDispatchPage([before, partial, fully_merged], [self.driver])

        dispatcher.dispatch_one(self.rule, page, timeout=0.5)

        self.assertEqual(page.opened_box_codes, ["M900"])
        self.assertEqual(page.confirm_count, 0)

    def test_404_selects_only_explicit_b_and_s_variants(self):
        rule = dispatcher.parse_dispatch_manifest(
            "404 404B 404S Yang Jun-feng | D21023280101"
        )[0]
        before = [
            box_row("base", "404", "B1"),
            box_row("a", "404 A", "DO-NOT-SELECT"),
            box_row("b", "404 B", "B2"),
            box_row("s", "404 S", "B3"),
        ]
        merged = [
            box_row("base-new", "404", "M404"),
            box_row("a", "404 A", "DO-NOT-SELECT"),
            box_row("b-new", "404 B", "M404"),
            box_row("s-new", "404 S", "M404"),
        ]
        page = FakeDispatchPage([before, merged], [self.driver])

        dispatcher.dispatch_one(rule, page, timeout=0.5)

        self.assertEqual(page.selected_row_keys, [["base", "b", "s"]])
        self.assertEqual(page.opened_box_codes, ["M404"])
        self.assertEqual(page.confirm_count, 0)

    def test_all_suffix_variants_selects_family_but_not_prefix_noise(self):
        rule = dispatcher.parse_dispatch_manifest(
            "301所有 Yang Jun-feng | D21023280101"
        )[0]
        before = [
            box_row("base", "301", "B1", 10),
            box_row("a", "301 A", "B2", 20),
            box_row("b", "301 B", "B3", 30),
            box_row("number", "3010", "DO-NOT-SELECT", 99),
            box_row("no-space", "301A", "DO-NOT-SELECT", 99),
        ]
        merged = [
            box_row("merged", "301,301 A,301 B", "M301", 60),
            box_row("number", "3010", "DO-NOT-SELECT", 99),
        ]
        page = FakeDispatchPage([before, merged], [self.driver])

        result = dispatcher.dispatch_one(rule, page, timeout=0.5)

        self.assertEqual(page.route_searches, ["301"])
        self.assertEqual(page.selected_row_keys, [["base", "a", "b"]])
        self.assertEqual(result.matched_routes, ("301", "301 A", "301 B"))
        self.assertEqual(page.opened_box_codes, ["M301"])
        self.assertEqual(page.confirm_count, 0)

    def test_composite_row_with_unrequested_route_fails_closed(self):
        rule = dispatcher.parse_dispatch_rule("404", "戴女士")
        page = FakeDispatchPage(
            [[box_row("mixed", "404,404 A", "MIXED", 20)]],
            [self.driver],
        )

        with self.assertRaisesRegex(RuntimeError, "混在同一箱号"):
            dispatcher.dispatch_one(rule, page, timeout=0.1)

        self.assertEqual(page.selected_row_keys, [])
        self.assertEqual(page.opened_box_codes, [])

    def test_exact_404_does_not_select_unrequested_suffix_rows(self):
        rule = dispatcher.parse_dispatch_rule("404", "Yang Jun-feng")
        page = FakeDispatchPage(
            [[
                box_row("base", "404", "B404", 10),
                box_row("b", "404 B", "DO-NOT-SELECT", 20),
                box_row("s", "404 S", "DO-NOT-SELECT", 30),
            ]],
            [self.driver],
        )

        result = dispatcher.dispatch_one(rule, page, timeout=0.1)

        self.assertEqual(result.matched_routes, ("404",))
        self.assertEqual(result.merged_box_code, "B404")
        self.assertEqual(page.selected_row_keys, [])
        self.assertEqual(page.opened_box_codes, ["B404"])

    def test_501_selects_only_explicit_a_and_d_variants(self):
        rule = dispatcher.DispatchRule(
            "501",
            "Yang Jun-feng",
            "D21023280101",
            ("501", "501 A", "501 D"),
        )
        before = [
            box_row("base", "501", "B1"),
            box_row("a", "501 A", "B2"),
            box_row("c", "501 C", "DO-NOT-SELECT"),
            box_row("d", "501 D", "B3"),
        ]
        merged = [
            box_row("base-new", "501", "M501"),
            box_row("a-new", "501 A", "M501"),
            box_row("c", "501 C", "DO-NOT-SELECT"),
            box_row("d-new", "501 D", "M501"),
        ]
        page = FakeDispatchPage([before, merged], [self.driver])

        dispatcher.dispatch_one(rule, page, timeout=0.5)

        self.assertEqual(page.selected_row_keys, [["base", "a", "d"]])
        self.assertEqual(page.opened_box_codes, ["M501"])
        self.assertEqual(page.confirm_count, 0)

    def test_manual_confirmation_continues_after_box_leaves_pending(self):
        result = dispatcher.DispatchResult(
            route_base="301",
            matched_routes=("301",),
            old_box_codes=("B1",),
            merged_box_code="M900",
            driver=self.driver,
        )
        page = ManualConfirmationPage([True, False], [[]])

        dispatcher.wait_for_manual_confirmation(
            self.rule,
            page,
            result,
            timeout=0.1,
            verify_timeout=0.1,
            poll_interval=0,
        )

        self.assertEqual(page.route_searches, [])

    def test_manual_confirmation_stops_if_box_remains_pending(self):
        result = dispatcher.DispatchResult(
            route_base="301",
            matched_routes=("301",),
            old_box_codes=("B1",),
            merged_box_code="M900",
            driver=self.driver,
        )
        page = ManualConfirmationPage(
            [False],
            [[box_row("still-pending", "301", "M900", 1)]],
        )

        with self.assertRaisesRegex(RuntimeError, "可能点击了“取消”"):
            dispatcher.wait_for_manual_confirmation(
                self.rule,
                page,
                result,
                timeout=0.1,
                verify_timeout=0,
                poll_interval=0,
            )

    def test_manual_confirmation_timeout_never_clicks_confirm(self):
        result = dispatcher.DispatchResult(
            route_base="301",
            matched_routes=("301",),
            old_box_codes=("B1",),
            merged_box_code="M900",
            driver=self.driver,
        )
        page = ManualConfirmationPage([True], [[]])

        with self.assertRaisesRegex(RuntimeError, "程序没有点击“确定”"):
            dispatcher.wait_for_manual_confirmation(
                self.rule,
                page,
                result,
                timeout=0,
                verify_timeout=0,
                poll_interval=0,
            )


class BatchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.rules = (
            dispatcher.parse_dispatch_rule("201", "Yang Jun"),
            dispatcher.parse_dispatch_rule("302", "宋修丞"),
        )
        self.driver = driver_option("宋修丞", "D21020000001")
        self.result = dispatcher.DispatchResult(
            route_base="302",
            matched_routes=("302",),
            old_box_codes=("B302",),
            merged_box_code="M302",
            driver=self.driver,
        )

    def test_batch_skips_no_pending_group_and_continues(self):
        page = SimpleNamespace(query_timeout=1)
        with (
            mock.patch.object(dispatcher.dc, "_load_config", return_value={}),
            mock.patch.object(dispatcher, "_ensure_dispatch_page", return_value=object()),
            mock.patch.object(dispatcher, "UIADispatchPage", return_value=page),
            mock.patch.object(
                dispatcher,
                "dispatch_one",
                side_effect=[
                    dispatcher.NoPendingRouteError("none"),
                    self.result,
                ],
            ) as dispatch_mock,
            mock.patch.object(
                dispatcher,
                "wait_for_manual_confirmation",
            ) as wait_mock,
        ):
            summary = dispatcher._dispatch_rules(self.rules, config={})

        self.assertEqual(dispatch_mock.call_count, 2)
        wait_mock.assert_called_once()
        self.assertIn("1 组已由你人工确认", summary)
        self.assertIn("1 组当前无待分配结果", summary)

    def test_batch_does_not_skip_other_runtime_errors(self):
        page = SimpleNamespace(query_timeout=1)
        with (
            mock.patch.object(dispatcher.dc, "_load_config", return_value={}),
            mock.patch.object(dispatcher, "_ensure_dispatch_page", return_value=object()),
            mock.patch.object(dispatcher, "UIADispatchPage", return_value=page),
            mock.patch.object(
                dispatcher,
                "dispatch_one",
                side_effect=RuntimeError("unsafe UI failure"),
            ) as dispatch_mock,
            mock.patch.object(
                dispatcher,
                "wait_for_manual_confirmation",
            ) as wait_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "unsafe UI failure"):
                dispatcher._dispatch_rules(self.rules, config={})

        self.assertEqual(dispatch_mock.call_count, 1)
        wait_mock.assert_not_called()

    def test_batch_all_skipped_does_not_wait_for_confirmation(self):
        page = SimpleNamespace(query_timeout=1)
        with (
            mock.patch.object(dispatcher.dc, "_load_config", return_value={}),
            mock.patch.object(dispatcher, "_ensure_dispatch_page", return_value=object()),
            mock.patch.object(dispatcher, "UIADispatchPage", return_value=page),
            mock.patch.object(
                dispatcher,
                "dispatch_one",
                side_effect=dispatcher.NoPendingRouteError("none"),
            ) as dispatch_mock,
            mock.patch.object(
                dispatcher,
                "wait_for_manual_confirmation",
            ) as wait_mock,
        ):
            summary = dispatcher._dispatch_rules(self.rules, config={})

        self.assertEqual(dispatch_mock.call_count, 2)
        wait_mock.assert_not_called()
        self.assertIn("0 组需要确认", summary)
        self.assertIn("2 组当前无待分配结果", summary)

    def test_single_rule_no_pending_returns_safe_skip_summary(self):
        rule = self.rules[0]
        page = SimpleNamespace()
        with (
            mock.patch.object(dispatcher.dc, "_load_config", return_value={}),
            mock.patch.object(dispatcher, "_ensure_dispatch_page", return_value=object()),
            mock.patch.object(dispatcher, "UIADispatchPage", return_value=page),
            mock.patch.object(
                dispatcher,
                "dispatch_one",
                side_effect=dispatcher.NoPendingRouteError("none"),
            ),
        ):
            summary = dispatcher._dispatch_single_rule(rule, config={})

        self.assertIn("已安全跳过", summary)


if __name__ == "__main__":
    unittest.main()
