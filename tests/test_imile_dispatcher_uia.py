import unittest
from types import SimpleNamespace
from unittest import mock

import imile_dispatcher as dispatcher


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class FakeControl:
    def __init__(
        self,
        name,
        control_type,
        rect,
        class_name="",
    ):
        self._name = name
        self._rect = rect
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


def control(name, control_type, left, top, right, bottom, class_name=""):
    return FakeControl(
        name,
        control_type,
        Rect(left, top, right, bottom),
        class_name,
    )


class UIARouteTableTests(unittest.TestCase):
    def make_headers(self):
        return (
            control("Boxcode", "Header", 100, 10, 360, 50),
            control("运单数", "Header", 360, 10, 560, 50),
            control("Routecode", "Header", 560, 10, 900, 50),
            control("操作", "Header", 1200, 10, 1380, 50),
        )

    def read_rows(self, controls, total, route_base="301"):
        page = dispatcher.UIADispatchPage(object(), route_base, {})
        page._require_active_dispatch = lambda: None
        page._headers = self.make_headers
        page._result_counts = lambda: (0, total)
        with mock.patch.object(
            dispatcher,
            "_visible_controls",
            return_value=list(controls),
        ):
            return page.read_route_rows()

    def test_wide_headers_do_not_mix_adjacent_numeric_columns_into_route(self):
        rows = self.read_rows(
            [
                control("", "CheckBox", 40, 140, 60, 160),
                control("20260721207301", "Text", 150, 140, 310, 160),
                control("301", "Text", 430, 140, 490, 160),
                control("404 B", "Text", 650, 140, 760, 160),
                control("0932", "Text", 960, 140, 1030, 160),
            ],
            total=1,
            route_base="404",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].box_code, "20260721207301")
        self.assertEqual(rows[0].waybill_count, 301)
        self.assertEqual(dispatcher.row_route_codes(rows[0]), ("404 B",))

    def test_one_physical_row_reads_multiline_route_text(self):
        rows = self.read_rows(
            [
                control("", "CheckBox", 40, 190, 60, 210),
                control("20260721207301", "Text", 150, 190, 310, 210),
                control("60", "Text", 430, 190, 490, 210),
                control(
                    "301\n301 A\n301 B",
                    "Group",
                    620,
                    170,
                    800,
                    230,
                ),
            ],
            total=1,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            dispatcher.row_route_codes(rows[0]),
            ("301", "301 A", "301 B"),
        )
        self.assertEqual(rows[0].box_code, "20260721207301")
        self.assertEqual(rows[0].waybill_count, 60)

    def test_one_physical_row_combines_duplicate_route_controls(self):
        rows = self.read_rows(
            [
                control("", "CheckBox", 40, 190, 60, 210),
                control("20260721207301", "Text", 150, 190, 310, 210),
                control("60", "Text", 430, 190, 490, 210),
                control(
                    "301,301 A,301 B",
                    "Group",
                    620,
                    170,
                    800,
                    230,
                ),
                control("301", "Text", 650, 170, 740, 190),
                control("301 A", "Text", 650, 190, 740, 210),
                control("301 B", "Text", 650, 210, 740, 230),
            ],
            total=1,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            dispatcher.row_route_codes(rows[0]),
            ("301", "301 A", "301 B"),
        )
        self.assertEqual(rows[0].box_code, "20260721207301")
        self.assertEqual(rows[0].waybill_count, 60)

    def test_distinct_physical_rows_with_same_box_code_are_preserved(self):
        shared_box = "20260721207301"
        rows = self.read_rows(
            [
                control("", "CheckBox", 40, 140, 60, 160),
                control(shared_box, "Text", 150, 140, 310, 160),
                control("10", "Text", 430, 140, 490, 160),
                control("301", "Text", 650, 140, 760, 160),
                control("", "CheckBox", 40, 240, 60, 260),
                control(shared_box, "Text", 150, 240, 310, 260),
                control("20", "Text", 430, 240, 490, 260),
                control("301 A", "Text", 650, 240, 760, 260),
            ],
            total=2,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [
                (
                    dispatcher.row_route_codes(row),
                    row.box_code,
                    row.waybill_count,
                )
                for row in rows
            ],
            [
                (("301",), shared_box, 10),
                (("301 A",), shared_box, 20),
            ],
        )

    def test_duplicate_checkbox_controls_for_one_physical_row_are_deduplicated(self):
        rows = self.read_rows(
            [
                control("", "CheckBox", 42, 190, 58, 210),
                control(
                    "",
                    "Group",
                    35,
                    189,
                    65,
                    219,
                    class_name="MuiCheckbox-root",
                ),
                control("20260721207301", "Text", 150, 194, 310, 214),
                control("44", "Text", 430, 194, 490, 214),
                control("301", "Text", 650, 194, 760, 214),
            ],
            total=1,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(dispatcher.row_route_codes(rows[0]), ("301",))
        self.assertEqual(rows[0].box_code, "20260721207301")
        self.assertEqual(rows[0].waybill_count, 44)

    def test_loading_indicator_is_limited_to_table_region(self):
        page = dispatcher.UIADispatchPage(object(), "301", {})
        page._headers = self.make_headers
        toolbar_spinner = control(
            "",
            "ProgressBar",
            900,
            0,
            940,
            30,
            class_name="loading",
        )
        table_spinner = control(
            "",
            "ProgressBar",
            700,
            100,
            740,
            140,
            class_name="loading",
        )

        with mock.patch.object(
            dispatcher,
            "_visible_controls",
            return_value=[toolbar_spinner],
        ):
            self.assertFalse(page._is_loading())

        with mock.patch.object(
            dispatcher,
            "_visible_controls",
            return_value=[table_spinner],
        ):
            self.assertTrue(page._is_loading())


if __name__ == "__main__":
    unittest.main()
