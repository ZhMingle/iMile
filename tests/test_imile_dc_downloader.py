import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import imile_dc_downloader as downloader


class FakeRect:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def width(self):
        return self.right - self.left


class FakeInfo:
    def __init__(self, control_type="Group", class_name="", automation_id=""):
        self.control_type = control_type
        self.class_name = class_name
        self.automation_id = automation_id


class FakeControl:
    def __init__(
        self,
        name,
        rect,
        control_type="Group",
        class_name="",
        automation_id="",
        visible=True,
    ):
        self.name = name
        self.rect = rect
        self.visible = visible
        self.element_info = FakeInfo(control_type, class_name, automation_id)

    def window_text(self):
        return self.name

    def rectangle(self):
        return self.rect

    def is_visible(self):
        return self.visible


class DCDownloaderTests(unittest.TestCase):
    def test_read_query_numbers_deduplicates_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "query_list.txt"
            path.write_text("A\nB\nA\n\nC\n", encoding="utf-8")

            resolved, numbers = downloader._read_query_numbers(path)

            self.assertEqual(resolved, path)
            self.assertEqual(numbers, ["A", "B", "C"])

    def test_parse_progress_accepts_export_format(self):
        self.assertEqual(downloader._parse_progress("9179/9179(100%)"), (9179, 9179, 100))
        self.assertEqual(downloader._parse_progress(" 12 / 30 ( 40 % ) "), (12, 30, 40))
        self.assertIsNone(downloader._parse_progress("排队中"))

    def test_query_result_does_not_accept_text_still_in_edit_box(self):
        edit = FakeControl("6072126000001", FakeRect(100, 100, 300, 130), "Edit")
        result = FakeControl("6072126000001", FakeRect(100, 300, 300, 330), "Text")

        with patch.object(downloader, "_descendants", return_value=[edit]):
            self.assertFalse(downloader._result_contains_query(object(), {"6072126000001"}))
        with patch.object(downloader, "_descendants", return_value=[edit, result]):
            self.assertTrue(downloader._result_contains_query(object(), {"6072126000001"}))

    def test_tracking_edit_accepts_english_label(self):
        label = FakeControl("Waybill number", FakeRect(100, 100, 250, 125), "Text")
        edit = FakeControl("", FakeRect(100, 125, 400, 165), "Edit")

        with patch.object(downloader, "_descendants", return_value=[label, edit]):
            self.assertIs(downloader._tracking_edit(object()), edit)

    def test_page_export_accepts_english_label(self):
        window = FakeControl("", FakeRect(0, 0, 1200, 900))
        parent = FakeControl(
            "",
            FakeRect(960, 100, 1140, 180),
            "Group",
            class_name="ImileActionButton-root hasText",
        )
        export = FakeControl("Export", FakeRect(1000, 120, 1120, 160), "Button")

        with patch.object(downloader, "_descendants", return_value=[parent, export]):
            self.assertIs(downloader._page_export_control(window), parent)

    def test_export_all_menu_accepts_group_control(self):
        export_all = FakeControl("导出全部", FakeRect(1000, 180, 1120, 220), "Group")

        with patch.object(downloader, "_descendants", return_value=[export_all]):
            self.assertIs(downloader._export_all_menu_control(object()), export_all)

    def test_create_export_task_clicks_drawer_export_button(self):
        drawer = FakeControl("", FakeRect(900, 100, 1400, 900), class_name="MuiDrawer-paper")
        create_export = FakeControl("", FakeRect(1100, 160, 1200, 200), class_name="export-button")

        with patch.object(downloader, "_export_drawer", return_value=drawer), patch.object(
            downloader, "_descendants", return_value=[drawer, create_export]
        ), patch.object(downloader, "_activate_control") as click:
            downloader._create_export_task(object())

        click.assert_called_once_with(create_export)

    def test_latest_task_selects_left_icon_inside_first_card(self):
        drawer = FakeControl("", FakeRect(1000, 100, 1400, 900), class_name="MuiDrawer-paper")
        first_title = FakeControl("中心运单查询", FakeRect(1040, 200, 1200, 230), "Text")
        second_title = FakeControl("中心运单查询", FakeRect(1040, 400, 1200, 430), "Text")
        progress = FakeControl("10/10(100%)", FakeRect(1200, 300, 1350, 330), "Text")
        download = FakeControl("", FakeRect(1320, 205, 1340, 225), class_name="Imile-ButtonIcon-root")
        delete = FakeControl("", FakeRect(1360, 205, 1380, 225), class_name="Imile-ButtonIcon-root")
        old_download = FakeControl("", FakeRect(1320, 405, 1340, 425), class_name="Imile-ButtonIcon-root")
        controls = [drawer, first_title, second_title, progress, delete, download, old_download]

        with patch.object(downloader, "_export_drawer", return_value=drawer), patch.object(
            downloader, "_descendants", return_value=controls
        ):
            state = downloader._latest_task_state(object())

        self.assertTrue(state["complete"])
        self.assertIs(state["download_control"], download)

    def test_latest_task_accepts_english_title_and_completion(self):
        drawer = FakeControl("", FakeRect(1000, 100, 1400, 900), class_name="MuiDrawer-paper")
        title = FakeControl("Central waybill query", FakeRect(1040, 200, 1250, 230), "Text")
        completed = FakeControl("Completed", FakeRect(1100, 260, 1200, 290), "Text")
        download = FakeControl("", FakeRect(1320, 205, 1340, 225), class_name="Imile-ButtonIcon-root")

        with patch.object(downloader, "_export_drawer", return_value=drawer), patch.object(
            downloader, "_descendants", return_value=[drawer, title, completed, download]
        ):
            state = downloader._latest_task_state(object())

        self.assertTrue(state["complete"])
        self.assertIs(state["download_control"], download)

    def test_export_drawer_ignores_hidden_dom_copy(self):
        hidden = FakeControl(
            "",
            FakeRect(1000, 100, 1600, 900),
            class_name="MuiDrawer-paper",
            visible=False,
        )
        visible = FakeControl(
            "",
            FakeRect(1100, 100, 1400, 900),
            class_name="MuiDrawer-paper",
        )

        with patch.object(downloader, "_descendants", return_value=[hidden, visible]):
            drawer = downloader._export_drawer(object())

        self.assertIs(drawer, visible)

    def test_validate_and_install_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "download.xlsx"
            target = root / "中心运单查询.xlsx"
            pd.DataFrame(
                {"运单号": ["6072126000001"], "路由码": ["AKL"], "商家编号": ["C1"]}
            ).to_excel(source, index=False)

            installed = downloader._install_export(source, target)

            self.assertEqual(installed, target)
            self.assertEqual(pd.read_excel(target, dtype=str).loc[0, "运单号"], "6072126000001")

    def test_english_export_is_normalized_for_statistics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "download.xlsx"
            target = root / "中心运单查询.xlsx"
            pd.DataFrame(
                {
                    "Waybill Number": ["6072126000001"],
                    "Routing Code": ["305"],
                    "Delivery Station S-Code": ["AKL"],
                    "Client Code": ["C2103960401"],
                }
            ).to_excel(source, index=False)

            downloader._install_export(source, target)
            installed = pd.read_excel(target, dtype=str)

            self.assertEqual(
                list(installed.columns),
                ["运单号", "路由码", "派件网点简码", "商家编号"],
            )
            self.assertEqual(installed.loc[0, "商家编号"], "C2103960401")

    def test_invalid_export_does_not_replace_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "wrong.xlsx"
            target = root / "中心运单查询.xlsx"
            pd.DataFrame({"other": [1]}).to_excel(source, index=False)
            target.write_bytes(b"existing")

            with self.assertRaisesRegex(RuntimeError, "缺少“运单号”列"):
                downloader._install_export(source, target)

            self.assertEqual(target.read_bytes(), b"existing")

    def test_search_fallback_uses_automation_id_not_screen_coordinate(self):
        source = inspect.getsource(downloader._open_from_search_menu)

        self.assertIn("ImileSMN-aside-MySearch", source)
        self.assertNotIn("mouse.click", source)


if __name__ == "__main__":
    unittest.main()
