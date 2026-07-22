import unittest

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

    def test_parse_driver_option_splits_name_and_id(self):
        option = dispatcher.parse_driver_option(
            "  Yang Jun-feng   |   D21023280101  "
        )

        self.assertEqual(option.name, "Yang Jun-feng")
        self.assertEqual(option.driver_id, "D21023280101")

    def test_exact_driver_name_does_not_choose_similar_search_result(self):
        expected = driver_option("Yang Jun-feng", "D21023280101")
        similar = driver_option("yang jun2-feng", "D21024948601")
        rule = dispatcher.DispatchRule("301", "yang jun-feng")

        resolved = dispatcher.resolve_driver([similar, expected], rule)

        self.assertEqual(resolved.driver_id, "D21023280101")

    def test_partial_driver_name_is_not_silently_resolved(self):
        options = [
            driver_option("Yang Jun-feng", "D21023280101"),
            driver_option("yang jun2-feng", "D21024948601"),
        ]
        rule = dispatcher.DispatchRule("301", "yang jun")

        with self.assertRaises(RuntimeError):
            dispatcher.resolve_driver(options, rule)

    def test_duplicate_exact_names_require_driver_id(self):
        options = [
            driver_option("Yang Jun-feng", "D21023280101"),
            driver_option("Yang Jun-feng", "D99999999999"),
        ]

        with self.assertRaises(RuntimeError):
            dispatcher.resolve_driver(
                options,
                dispatcher.DispatchRule("301", "Yang Jun-feng"),
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
            box_row("base-new", "301", "M900"),
            box_row("a-new", "301 A", "M900"),
            box_row("b-new", "301 B", "M900"),
            box_row("wrong", "3010", "B3010"),
        ]
        page = FakeDispatchPage(
            [before, stale_after_click, merged],
            [self.driver],
        )

        dispatcher.dispatch_one(self.rule, page, timeout=1.0)

        self.assertGreaterEqual(len(page.route_searches), 2)
        self.assertTrue(all(value == "301" for value in page.route_searches))
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
        fully_merged = [box_row("merged", "301", "M900", 60)]
        page = FakeDispatchPage([before, partial, fully_merged], [self.driver])

        dispatcher.dispatch_one(self.rule, page, timeout=0.5)

        self.assertEqual(page.opened_box_codes, ["M900"])
        self.assertEqual(page.confirm_count, 0)

    def test_404_selects_only_explicit_b_and_s_variants(self):
        rule = dispatcher.DispatchRule(
            "404",
            "Yang Jun-feng",
            "D21023280101",
            ("404", "404 B", "404 S"),
        )
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


if __name__ == "__main__":
    unittest.main()
