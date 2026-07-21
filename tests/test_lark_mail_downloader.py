from pathlib import Path
import tempfile
import unittest

import lark_mail_downloader as downloader


def ocr_item(text, y, x=100, width=180):
    return {
        "text": text,
        "score": 0.99,
        "box": [[x, y], [x + width, y], [x + width, y + 30], [x, y + 30]],
    }


class LarkMailDownloaderTests(unittest.TestCase):
    def test_mail_view_requires_mail_inbox_and_search(self):
        items = [
            ocr_item("邮箱", 50),
            ocr_item("收件箱", 100),
            ocr_item("搜索邮件(Ctrl+Shift+F)", 150),
        ]

        self.assertTrue(downloader._mail_view_visible(items))
        self.assertFalse(downloader._mail_view_visible(items[:2]))

    def test_mail_search_point_uses_search_label(self):
        search = ocr_item("搜索邮件(Ctrl+Shift+F)", 150, x=300, width=260)

        self.assertEqual(downloader._mail_search_point([search]), (430.0, 165.0))

    def test_mail_navigation_point_uses_left_sidebar(self):
        sidebar = ocr_item("邮箱", 150, x=30)
        content = ocr_item("邮箱", 50, x=900)

        point = downloader._mail_navigation_point([sidebar, content], (2000, 1200))

        self.assertEqual(point, downloader._item_center(sidebar))

    def test_mail_search_results_require_key(self):
        items = [
            ocr_item("邮箱", 50),
            ocr_item("搜索结果", 80),
            ocr_item("60500510", 120),
        ]

        self.assertTrue(downloader._mail_search_results_visible(items, "60500510"))
        self.assertFalse(downloader._mail_search_results_visible(items, "60500495"))
        self.assertTrue(downloader._mail_results_page_visible(items))

    def test_mail_results_back_point_uses_top_return_label(self):
        top_return = ocr_item("返回", 50, x=700)
        body_return = ocr_item("返回", 700, x=1300)

        point = downloader._mail_results_back_point(
            [top_return, body_return],
            (2000, 1200),
        )

        self.assertEqual(point, downloader._item_center(top_return))

    def test_mail_result_point_ignores_search_box(self):
        items = [
            ocr_item("60411190", 140, x=300),
            ocr_item("Pre-Alert HKG-AKL 086-60411190", 500, x=700, width=400),
        ]

        point = downloader._mail_result_click_point(items, "60411190", (2000, 1200))

        self.assertEqual(point, downloader._item_center(items[1]))

    def test_mail_detail_requires_key_in_right_pane(self):
        result_list = ocr_item("Pre-alert 086-60411190", 200, x=700)
        detail = ocr_item("MAWB: 086-60411190", 400, x=1300)

        self.assertFalse(
            downloader._mail_detail_visible([result_list], "60411190", (2000, 1200))
        )
        self.assertTrue(
            downloader._mail_detail_visible(
                [result_list, detail],
                "60411190",
                (2000, 1200),
            )
        )

    def test_attachment_point_is_in_mail_detail_pane(self):
        items = [
            ocr_item("list-file.xls", 500, x=700),
            ocr_item("Cainiao-08660411190.xlsx", 800, x=1300, width=350),
        ]

        point = downloader._attachment_click_point(
            items,
            {".xls", ".xlsx"},
            (2000, 1200),
            "60411190",
        )

        self.assertEqual(point, downloader._item_center(items[1]))
        self.assertIsNone(
            downloader._attachment_click_point(
                items,
                {".xls", ".xlsx"},
                (2000, 1200),
                "60500510",
            )
        )

    def test_attachment_point_accepts_lark_truncated_xls_name(self):
        item = ocr_item("086-60500510_data.x", 700, x=1300, width=320)

        point = downloader._attachment_click_point(
            [item],
            {".xls", ".xlsx"},
            (2000, 1200),
            "60500510",
        )

        self.assertEqual(point, downloader._item_center(item))

    def test_attachment_point_accepts_filename_split_by_ocr(self):
        number = ocr_item("086-60500495", 700, x=1300, width=170)
        extension = ocr_item("5_data.xls", 700, x=1470, width=120)

        point = downloader._attachment_click_point(
            [number, extension],
            {".xls", ".xlsx"},
            (2000, 1200),
            "60500495",
        )

        self.assertEqual(point, downloader._item_center(number))

    def test_attachment_point_selects_shunyou_excel_marker(self):
        pdf = ocr_item("086-60410932 MAWB.pdf", 700, x=1200, width=260)
        excel = ocr_item("IMILE末端预报.xlsx", 700, x=1550, width=260)

        point = downloader._attachment_click_point(
            [pdf, excel],
            {".xls", ".xlsx"},
            (2200, 1400),
            "60410932",
            ("IMILE末端预报",),
        )

        self.assertEqual(point, downloader._item_center(excel))

    def test_context_download_requires_menu_and_accepts_ocr_arrow_prefix(self):
        download = ocr_item("上下载", 800, x=1300)
        preview = ocr_item("预览", 850, x=1300)

        point = downloader._context_download_point(
            [download, preview],
            (2000, 1200),
            (1400, 760),
        )

        self.assertEqual(point, downloader._item_center(download))
        self.assertIsNone(
            downloader._context_download_point(
                [download],
                (2000, 1200),
                (1400, 760),
            )
        )

    def test_screen_point_scales_ocr_coordinates_to_window(self):
        class Rectangle:
            left = 100
            top = 50
            right = 1100
            bottom = 550

        point = downloader._screen_point((1000, 500), (2000, 1000), Rectangle())

        self.assertEqual(point, (600, 300))

    def test_hover_scan_points_follow_attachment_and_viewport(self):
        points = downloader._hover_scan_points((1500, 700), (2000, 1200))

        self.assertEqual(points[0], (1500, 700))
        self.assertTrue(any(x > 1500 for x, _ in points))
        self.assertTrue(any(x < 1500 for x, _ in points))
        self.assertTrue(all(960 <= x <= 1940 for x, _ in points))

    def test_existing_download_matches_eight_digit_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            expected = folder / "Pre-Alert-08660411190.xlsx"
            expected.write_bytes(b"excel")

            match = downloader._existing_download_for_key(
                folder,
                "60411190",
                {".xls", ".xlsx"},
            )

            self.assertEqual(match, expected.resolve())

    def test_shunyou_download_is_renamed_with_search_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "IMILE末端预报.xlsx"
            source.write_bytes(b"excel")

            renamed = downloader._rename_download(source, "顺友", "60410932")

            self.assertEqual(renamed.name, "顺友60410932.xlsx")
            self.assertTrue(renamed.exists())

    def test_explicit_download_directory_is_portable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolved = downloader._windows_download_dir(
                {"lark_download_dir": temp_dir}
            )

            self.assertEqual(resolved, Path(temp_dir))


if __name__ == "__main__":
    unittest.main()
