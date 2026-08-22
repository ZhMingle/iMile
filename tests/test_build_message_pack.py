import unittest
from unittest import mock

import pandas as pd

import build_message_pack


class BuildMessagePackTests(unittest.TestCase):
    def test_goose_keeps_all_routes_separate(self):
        group = pd.DataFrame(
            [["407", 51, "Goose"], ["408", 39, "Goose"], ["408A", 0, "Goose"]],
            columns=["route_code", "quantity", "supplier"],
        )

        rows, total = build_message_pack.supplier_display_rows("Goose", group)

        self.assertEqual(
            rows,
            [["407", 51, "Goose"], ["408", 39, "Goose"], ["408A", 0, "Goose"]],
        )
        self.assertEqual(total, 90)

    def test_panda_keeps_routes_separate(self):
        group = pd.DataFrame(
            [
                ["402", 35, "PANDA"],
                ["403", 35, "PANDA"],
                ["501B", 118, "PANDA"],
                ["501C", 4, "PANDA"],
                ["502A", 36, "PANDA"],
            ],
            columns=["route_code", "quantity", "supplier"],
        )

        rows, total = build_message_pack.supplier_display_rows("PANDA", group)

        self.assertEqual(
            rows,
            [
                ["402", 35, "PANDA"],
                ["403", 35, "PANDA"],
                ["501B", 118, "PANDA"],
                ["501C", 4, "PANDA"],
                ["502A", 36, "PANDA"],
            ],
        )
        self.assertEqual(total, 228)

    def test_fast_donkey_keeps_309_and_309a_separate_and_preserves_zero_group(self):
        group = pd.DataFrame(
            [
                ["211", 30, "Fast donkey"], ["211A", 27, "Fast donkey"],
                ["306", 66, "Fast donkey"],
                ["309", 27, "Fast donkey"], ["309A", 35, "Fast donkey"],
                ["310", 11, "Fast donkey"], ["311", 17, "Fast donkey"],
                ["312", 18, "Fast donkey"],
                ["503", 4, "Fast donkey"], ["503A", 48, "Fast donkey"],
                ["503B", 17, "Fast donkey"],
                ["607", 28, "Fast donkey"], ["607S", 6, "Fast donkey"],
                ["608", 5, "Fast donkey"],
                ["609", 0, "Fast donkey"], ["609A", 0, "Fast donkey"],
            ],
            columns=["route_code", "quantity", "supplier"],
        )

        rows, total = build_message_pack.supplier_display_rows("Fast donkey", group)

        self.assertEqual(
            rows,
            [
                ["211 / 211A", "30 / 27 (57)", "Fast donkey"],
                ["306", 66, "Fast donkey"],
                ["309", 27, "Fast donkey"],
                ["309A", 35, "Fast donkey"],
                ["310", 11, "Fast donkey"],
                ["311", 17, "Fast donkey"],
                ["312", 18, "Fast donkey"],
                ["503 / 503A / 503B", "4 / 48 / 17 (69)", "Fast donkey"],
                ["607 / 607S", "28 / 6 (34)", "Fast donkey"],
                ["608", 5, "Fast donkey"],
                ["609 / 609A", "0 / 0 (0)", "Fast donkey"],
            ],
        )
        self.assertEqual(total, 339)

    def test_feng_groups_and_keeps_406_606_separate(self):
        group = pd.DataFrame(
            [
                ["201", 21, "Feng"], ["201A", 3, "Feng"], ["201S", 6, "Feng"],
                ["202", 15, "Feng"], ["202S", 2, "Feng"],
                ["301", 37, "Feng"], ["301S", 9, "Feng"],
                ["302", 17, "Feng"], ["303", 13, "Feng"],
                ["401A", 12, "Feng"], ["401B", 9, "Feng"],
                ["401C", 10, "Feng"], ["401S", 11, "Feng"],
                ["404", 33, "Feng"], ["404A", 10, "Feng"],
                ["404B", 7, "Feng"], ["404S", 12, "Feng"],
                ["406", 57, "Feng"],
                ["604", 18, "Feng"], ["604A", 35, "Feng"], ["604S", 5, "Feng"],
                ["605", 21, "Feng"], ["605A", 5, "Feng"], ["605S", 2, "Feng"],
                ["606", 20, "Feng"],
            ],
            columns=["route_code", "quantity", "supplier"],
        )

        rows, total = build_message_pack.supplier_display_rows("Feng", group)

        self.assertEqual(
            rows,
            [
                ["201 / 201A / 201S", "21 / 3 / 6 (30)", "Feng"],
                ["202 / 202S", "15 / 2 (17)", "Feng"],
                ["301 / 301S", "37 / 9 (46)", "Feng"],
                ["302 / 303", "17 / 13 (30)", "Feng"],
                ["401A / 401B / 401C / 401S", "12 / 9 / 10 / 11 (42)", "Feng"],
                ["404 / 404A / 404B / 404S", "33 / 10 / 7 / 12 (62)", "Feng"],
                ["406", 57, "Feng"],
                ["604 / 604A / 604S", "18 / 35 / 5 (58)", "Feng"],
                ["605 / 605A / 605S", "21 / 5 / 2 (28)", "Feng"],
                ["606", 20, "Feng"],
            ],
        )
        self.assertEqual(total, 390)

    def test_click_n_code_groups_and_keeps_603_separate(self):
        group = pd.DataFrame(
            [
                ["203", 7, "Click'N Code"],
                ["203 A", 14, "Click'N Code"],
                ["203 B", 17, "Click'N Code"],
                ["206", 17, "Click'N Code"],
                ["207", 23, "Click'N Code"],
                ["207 S", 3, "Click'N Code"],
                ["210", 40, "Click'N Code"],
                ["405", 7, "Click'N Code"],
                ["405 A", 0, "Click'N Code"],
                ["405 B", 0, "Click'N Code"],
                ["405 C", 70, "Click'N Code"],
                ["405 D", 25, "Click'N Code"],
                ["603", 41, "Click'N Code"],
            ],
            columns=["route_code", "quantity", "supplier"],
        )

        rows, total = build_message_pack.supplier_display_rows("Click'N Code", group)

        self.assertEqual(
            rows,
            [
                ["203 / 203A / 203B", "7 / 14 / 17 (38)", "Click'N Code"],
                ["206 / 210", "17 / 40 (57)", "Click'N Code"],
                ["207 / 207S", "23 / 3 (26)", "Click'N Code"],
                [
                    "405 / 405A / 405B / 405C / 405D",
                    "7 / 0 / 0 / 70 / 25 (102)",
                    "Click'N Code",
                ],
                ["603", 41, "Click'N Code"],
            ],
        )
        self.assertEqual(total, 264)

    def test_fast_rabbit_groups_keep_304_separate(self):
        group = pd.DataFrame(
            [
                ["304", 34, "Fast Rabbit"],
                ["307", 11, "Fast Rabbit"],
                ["307 A", 35, "Fast Rabbit"],
                ["307 B", 15, "Fast Rabbit"],
                ["308", 14, "Fast Rabbit"],
                ["308 A", 11, "Fast Rabbit"],
                ["308 B", 19, "Fast Rabbit"],
                ["308 C", 13, "Fast Rabbit"],
                ["308 D", 24, "Fast Rabbit"],
            ],
            columns=["route_code", "quantity", "supplier"],
        )

        rows, total = build_message_pack.supplier_display_rows("Fast Rabbit", group)

        self.assertEqual(
            rows,
            [
                ["304", 34, "Fast Rabbit"],
                ["307 / 307A / 307B", "11 / 35 / 15 (61)", "Fast Rabbit"],
                [
                    "308 / 308A / 308B / 308C / 308D",
                    "14 / 11 / 19 / 13 / 24 (81)",
                    "Fast Rabbit",
                ],
            ],
        )
        self.assertEqual(total, 176)

    def test_empire_supplier_groups_show_detail_and_total(self):
        group = pd.DataFrame(
            [
                ["101", 5, "EMPIRE COURIER"],
                ["102", 2, "EMPIRE COURIER"],
                ["103", 0, "EMPIRE COURIER"],
                ["104", 26, "EMPIRE COURIER"],
                ["105", 30, "EMPIRE COURIER"],
                ["106", 17, "EMPIRE COURIER"],
                ["107", 32, "EMPIRE COURIER"],
                ["108", 25, "EMPIRE COURIER"],
                ["204", 15, "EMPIRE COURIER"],
                ["204 S", 6, "EMPIRE COURIER"],
                ["501", 11, "EMPIRE COURIER"],
                ["501 A", 9, "EMPIRE COURIER"],
                ["501 D", 24, "EMPIRE COURIER"],
                ["502", 9, "EMPIRE COURIER"],
                ["502 B", 11, "EMPIRE COURIER"],
                ["502 C", 35, "EMPIRE COURIER"],
                ["504", 35, "EMPIRE COURIER"],
                ["505", 25, "EMPIRE COURIER"],
                ["506", 31, "EMPIRE COURIER"],
                ["507", 23, "EMPIRE COURIER"],
                ["508", 7, "EMPIRE COURIER"],
            ],
            columns=["route_code", "quantity", "supplier"],
        )

        rows, total = build_message_pack.supplier_display_rows("EMPIRE COURIER", group)

        self.assertEqual(
            rows,
            [
                ["101 / 102 / 103", "5 / 2 / 0 (7)", "EMPIRE COURIER"],
                ["104 / 105 / 106", "26 / 30 / 17 (73)", "EMPIRE COURIER"],
                ["107 / 108", "32 / 25 (57)", "EMPIRE COURIER"],
                ["204 / 204S", "15 / 6 (21)", "EMPIRE COURIER"],
                [
                    "501 / 501A / 501D",
                    "11 / 9 / 24 (44)",
                    "EMPIRE COURIER",
                ],
                ["502 / 502B / 502C", "9 / 11 / 35 (55)", "EMPIRE COURIER"],
                [
                    "504 / 505 / 506 / 507 / 508",
                    "35 / 25 / 31 / 23 / 7 (121)",
                    "EMPIRE COURIER",
                ],
            ],
        )
        self.assertEqual(total, 378)

    def test_empire_group_does_not_pull_routes_from_panda(self):
        empire = pd.DataFrame(
            [
                ["101", 5, "EMPIRE COURIER"],
                ["102", 2, "EMPIRE COURIER"],
                ["103", 0, "EMPIRE COURIER"],
                ["104", 26, "EMPIRE COURIER"],
                ["105", 30, "EMPIRE COURIER"],
                ["106", 17, "EMPIRE COURIER"],
                ["107", 32, "EMPIRE COURIER"],
                ["108", 25, "EMPIRE COURIER"],
                ["204", 15, "EMPIRE COURIER"],
                ["204S", 6, "EMPIRE COURIER"],
                ["501", 11, "EMPIRE COURIER"],
                ["501A", 9, "EMPIRE COURIER"],
                ["501D", 24, "EMPIRE COURIER"],
                ["502", 9, "EMPIRE COURIER"],
                ["502B", 11, "EMPIRE COURIER"],
                ["502C", 35, "EMPIRE COURIER"],
                ["504", 35, "EMPIRE COURIER"],
                ["505", 25, "EMPIRE COURIER"],
                ["506", 31, "EMPIRE COURIER"],
                ["507", 23, "EMPIRE COURIER"],
                ["508", 7, "EMPIRE COURIER"],
            ],
            columns=["route_code", "quantity", "supplier"],
        )
        panda = pd.DataFrame(
            [
                ["501B", 118, "PANDA"],
                ["501C", 4, "PANDA"],
                ["502A", 36, "PANDA"],
            ],
            columns=["route_code", "quantity", "supplier"],
        )

        empire_rows, _ = build_message_pack.supplier_display_rows("EMPIRE COURIER", empire)
        panda_rows, _ = build_message_pack.supplier_display_rows("PANDA", panda)

        empire_text = " ".join(str(value) for row in empire_rows for value in row)
        self.assertNotIn("501B", empire_text)
        self.assertNotIn("501C", empire_text)
        self.assertEqual(
            panda_rows,
            [
                ["501B", 118, "PANDA"],
                ["501C", 4, "PANDA"],
                ["502A", 36, "PANDA"],
            ],
        )

    def test_supplier_render_uses_wide_fit_columns_and_preserves_grand_total(self):
        group = pd.DataFrame(
            [
                ["101", 5, "EMPIRE COURIER"],
                ["102", 2, "EMPIRE COURIER"],
                ["103", 0, "EMPIRE COURIER"],
                ["104", 26, "EMPIRE COURIER"],
                ["105", 30, "EMPIRE COURIER"],
                ["106", 17, "EMPIRE COURIER"],
                ["107", 32, "EMPIRE COURIER"],
                ["108", 25, "EMPIRE COURIER"],
                ["204", 15, "EMPIRE COURIER"],
                ["204S", 6, "EMPIRE COURIER"],
                ["501", 11, "EMPIRE COURIER"],
                ["501A", 9, "EMPIRE COURIER"],
                ["501D", 24, "EMPIRE COURIER"],
                ["502", 9, "EMPIRE COURIER"],
                ["502B", 11, "EMPIRE COURIER"],
                ["502C", 35, "EMPIRE COURIER"],
                ["504", 35, "EMPIRE COURIER"],
                ["505", 25, "EMPIRE COURIER"],
                ["506", 31, "EMPIRE COURIER"],
                ["507", 23, "EMPIRE COURIER"],
                ["508", 7, "EMPIRE COURIER"],
            ],
            columns=["route_code", "quantity", "supplier"],
        )

        with mock.patch.object(build_message_pack, "render_table_image") as render:
            build_message_pack.render_supplier_image(
                self.temp_path,
                "EMPIRE COURIER",
                group,
            )

        kwargs = render.call_args.kwargs
        self.assertEqual(kwargs["widths"], [300, 340, 260])
        self.assertEqual(kwargs["fit_body_columns"], (0, 1))
        self.assertFalse(kwargs["hide_total_label"])
        self.assertEqual(kwargs["rows"][-1], ["Total", 378, "EMPIRE COURIER"])

    def test_ungrouped_supplier_keeps_original_layout(self):
        group = pd.DataFrame(
            [["205", 25, "SAFE"], ["208", 26, "SAFE"]],
            columns=["route_code", "quantity", "supplier"],
        )

        with mock.patch.object(build_message_pack, "render_table_image") as render:
            build_message_pack.render_supplier_image(self.temp_path, "SAFE", group)

        kwargs = render.call_args.kwargs
        self.assertEqual(kwargs["widths"], [170, 260, 260])
        self.assertEqual(kwargs["fit_body_columns"], ())
        self.assertFalse(kwargs["hide_total_label"])

    def test_total_breakdown_preserves_unassigned_volume(self):
        self.assertEqual(
            build_message_pack.parse_total_breakdown(
                "8238(4790+0+3448)",
                province_count=0,
            ),
            (8238, 4790, 0, 3448),
        )

    def test_legacy_total_breakdown_derives_missing_unassigned_volume(self):
        self.assertEqual(
            build_message_pack.parse_total_breakdown(
                "8238(4790+0)",
                province_count=0,
            ),
            (8238, 4790, 0, 3448),
        )

    def test_non_auckland_image_accepts_the_workbook_board_capacity(self):
        overview = pd.DataFrame(
            [["总计", 0, 0, 0]],
            columns=["station", "arrival_volume", "cainiao_volume", "sunyou_volume"],
        )
        board_3l = pd.DataFrame(
            [["总计", 0]],
            columns=["station", "boards"],
        )
        board_5l = board_3l.copy()

        captured = []
        original = build_message_pack.draw_centered_text

        def capture(draw, box, text, font, fill=build_message_pack.BLACK):
            captured.append(text)

        build_message_pack.draw_centered_text = capture
        try:
            build_message_pack.render_non_auckland_overview(
                self.temp_path,
                overview,
                board_3l,
                board_5l,
                200,
                350,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        finally:
            build_message_pack.draw_centered_text = original

        self.assertIn(200, captured)

    def setUp(self):
        self.temp_path = build_message_pack.OUTPUT_DIR / "test_board_capacity.png"

    def tearDown(self):
        self.temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
