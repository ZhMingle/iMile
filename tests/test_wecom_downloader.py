import json
import inspect
import os
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import wecom_downloader as downloader


def ocr_item(text, y, x=600, score=0.99):
    return {
        "text": text,
        "score": score,
        "box": [[x, y], [x + 250, y], [x + 250, y + 30], [x, y + 30]],
    }


class WeComDownloaderTests(unittest.TestCase):
    def test_temu_numbers_stop_before_cainiao_section(self):
        items = [
            ocr_item("Temu:", 100),
            ocr_item("112-08847484", 140),
            ocr_item("086-63177450", 180),
            ocr_item("Cainiao:", 220),
            ocr_item("086-60500495", 260),
        ]

        numbers = downloader._temu_search_keys_from_items(items, (1479, 976))

        self.assertEqual(numbers, ["08847484", "63177450"])

    def test_temu_numbers_accept_compact_and_same_line_values(self):
        items = [
            ocr_item("Temu: 11208847484", 100),
            ocr_item("086 63177450", 140),
            ocr_item("Cainiao: 08660500495", 180),
        ]

        numbers = downloader._temu_search_keys_from_items(items)

        self.assertEqual(numbers, ["08847484", "63177450"])

    def test_shipment_numbers_separate_temu_and_cainiao(self):
        items = [
            ocr_item("Temu:", 100),
            ocr_item("160-13958501", 140),
            ocr_item("Cainiao:", 180),
            ocr_item("086-60500440", 220),
            ocr_item("784-85041036", 260),
        ]

        numbers = downloader._shipment_search_keys_from_items(items, (1479, 976))

        self.assertEqual(numbers["temu"], ["13958501"])
        self.assertEqual(numbers["cainiao"], ["60500440", "85041036"])

    def test_shunyou_numbers_are_deduplicated_from_chat_and_quotes(self):
        items = [
            ocr_item("Hi, all 3 deliveries - 086-60410906", 100),
            ocr_item("086-60410932", 140),
            ocr_item("086-60411190", 180),
            ocr_item("quoted again: 086-60410932", 500),
            ocr_item("low confidence 086-99999999", 540, score=0.4),
        ]

        numbers = downloader._shunyou_search_keys_from_items(items)

        self.assertEqual(numbers, ["60410906", "60410932", "60411190"])

    def test_shunyou_flow_archives_download_and_reports_ticket_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "顺友60410932.xlsx"
            source.write_bytes(b"excel")
            config = {
                "shunyou_archive_dir": str(root / "archive"),
                "auto_extract_tracking": False,
            }
            today = date.today()
            items = [
                ocr_item("Mere @微信", 50),
                ocr_item(f"{today.month}/{today.day} 09:30:00", 50, x=900),
                ocr_item("086-60410932", 100),
            ]

            with patch(
                "lark_mail_downloader.download_shunyou_files",
                return_value=({"60410932": source}, []),
            ):
                message = downloader._read_shunyou_chat(
                    config,
                    "iMile x Auslink TEMU handover",
                    items,
                )

            archived = list((root / "archive").rglob("顺友60410932.xlsx"))
            self.assertEqual(len(archived), 1)
            self.assertIn("识别 1 票", message)
            self.assertIn("60410932", message)

    def test_message_date_filter_keeps_only_today(self):
        target = date(2026, 7, 22)
        yesterday = target - timedelta(days=1)
        items = [
            ocr_item("James Wang Wiseway NZ @微信", 50),
            ocr_item(f"{yesterday.month}/{yesterday.day} 09:33:35", 50, x=900),
            ocr_item("Temu:", 100),
            ocr_item("112-08847484", 140),
            ocr_item("James Wang Wiseway NZ @微信", 300),
            ocr_item(f"{target.month}/{target.day} 09:35:00", 300, x=900),
            ocr_item("Temu:", 350),
            ocr_item("160-13958501", 390),
            ocr_item("Cainiao:", 430),
            ocr_item("086-60500495", 470),
        ]

        selected, visible_dates = downloader._message_items_for_date(items, target)
        numbers = downloader._shipment_search_keys_from_items(selected)

        self.assertEqual(visible_dates, {yesterday, target})
        self.assertEqual(numbers["temu"], ["13958501"])
        self.assertEqual(numbers["cainiao"], ["60500495"])

    def test_time_only_sender_header_counts_as_today(self):
        target = date(2026, 7, 22)
        items = [
            ocr_item("James Wang Wiseway NZ @微信", 50),
            ocr_item("09:35:00", 50, x=900),
            ocr_item("Temu:", 100),
            ocr_item("160-13958501", 140),
        ]

        selected, visible_dates = downloader._message_items_for_date(items, target)

        self.assertEqual(visible_dates, {target})
        self.assertEqual(downloader._temu_search_keys_from_items(selected), ["13958501"])

    def test_confirmation_can_be_disabled_for_unattended_runs(self):
        self.assertTrue(
            downloader._confirm_tracking_continuation(
                "summary",
                {"confirm_before_tracking": False},
            )
        )

    def test_temu_numbers_ignore_sidebar_and_low_confidence(self):
        items = [
            ocr_item("Temu:", 100),
            ocr_item("112-08847484", 140, x=20),
            ocr_item("086-63177450", 180, score=0.4),
        ]

        self.assertEqual(downloader._temu_search_keys_from_items(items, (1479, 976)), [])

    def test_cached_files_for_keys_selects_latest_matching_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old = root / "11208957723-ETA-old.xls"
            latest = root / "11208957723-ETA-new.xls"
            other = root / "88050881106-ETA.xls"
            old.write_bytes(b"old")
            latest.write_bytes(b"new")
            other.write_bytes(b"other")
            os.utime(old, (1, 1))
            os.utime(latest, (2, 2))

            matches = downloader._cached_files_for_keys(
                [root], ["08957723", "50881106", "missing"], {".xls"}
            )

            self.assertEqual(matches["08957723"], latest.resolve())
            self.assertEqual(matches["50881106"], other.resolve())
            self.assertNotIn("missing", matches)

    def test_archive_cached_files_deduplicates_by_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = root / "cache"
            archive_root = root / "input" / "TEMU"
            cache.mkdir()
            source = cache / "16013958501-ETA.xls"
            source.write_bytes(b"excel")

            archived, duplicates = downloader._archive_cached_files(
                {"13958501": source}, archive_root
            )
            second_archived, second_duplicates = downloader._archive_cached_files(
                {"13958501": source}, archive_root
            )

            self.assertEqual(len(archived), 1)
            self.assertEqual(duplicates, [])
            self.assertEqual(second_archived, [])
            self.assertEqual(second_duplicates, [source])
            manifest = json.loads(
                (archive_root / ".downloaded_files.json").read_text(encoding="utf-8")
            )
            self.assertEqual(next(iter(manifest.values()))["search_key"], "13958501")

    def test_chat_name_visible_accepts_ocr_spacing(self):
        items = [{"text": "iMile x WISEWAY", "score": 0.99, "box": []}]

        self.assertTrue(downloader._chat_name_visible(items, "iMile x WISEWAY"))
        self.assertFalse(downloader._chat_name_visible(items, "Other group"))

    def test_login_state_distinguishes_chat_shell_and_login_page(self):
        logged_in = [
            {"text": "消息"},
            {"text": "邮件"},
            {"text": "企业微信团队 登录操作通知"},
            {"text": "工作台"},
        ]
        logged_out = [
            {"text": "使用微信扫码登录企业微信"},
            {"text": "手机号登录"},
        ]

        self.assertEqual(downloader._login_state(logged_in), "logged_in")
        self.assertEqual(downloader._login_state(logged_out), "logged_out")
        self.assertEqual(downloader._login_state([{"text": "企业微信"}]), "unknown")

    def test_history_view_requires_tabs_and_filter(self):
        history = [
            ocr_item("全部", 50),
            ocr_item("文件", 50, x=900),
            ocr_item("图片与视频", 50, x=1100),
            ocr_item("发送人", 170),
            ocr_item("日期", 170, x=900),
        ]

        self.assertTrue(downloader._history_view_visible(history))
        self.assertFalse(downloader._history_view_visible(history[:2]))

    def test_history_search_point_is_below_all_tab(self):
        all_tab = ocr_item("全部", 50, x=100)

        point = downloader._history_search_point([all_tab])

        self.assertEqual(point, (375.0, 141.0))

    def test_file_result_click_point_prefers_attachment_card(self):
        items = [
            ocr_item("16013958501-", 250, x=120),
            ocr_item("ETA-18.07.2026.xls", 285, x=120),
            ocr_item("160-13958501", 520, x=120),
        ]

        point = downloader._file_result_click_point(items, "13958501", {".xls", ".xlsx"})

        self.assertEqual(point, downloader._item_center(items[0]))
        self.assertIsNone(downloader._file_result_click_point(items, "bad", {".xls"}))

    def test_history_search_has_no_enter_keystroke(self):
        source = inspect.getsource(downloader._search_history).upper()

        self.assertNotIn("{ENTER}", source)


if __name__ == "__main__":
    unittest.main()
