from datetime import date, datetime, time
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app_workflows
import run_daily_report
import update_report_data


class BotMessageConfigurationTests(unittest.TestCase):
    @staticmethod
    def _write_config(folder, messages, default_send_as="auto"):
        config_path = Path(folder) / "lark_config.json"
        config_path.write_text(
            json.dumps(
                {
                    "app_id": "app-id",
                    "app_secret": "app-secret",
                    "send_as": default_send_as,
                    "messages": messages,
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def test_filters_each_mode_and_resolves_auto_messages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = self._write_config(
                temp_dir,
                [
                    {
                        "name": "Auto webhook",
                        "send_as": "auto",
                        "webhook": "https://example.test/hook",
                    },
                    {
                        "name": "Auto app",
                        "receive_id_type": "chat_id",
                        "receive_id": "oc_app",
                    },
                    {
                        "name": "Explicit user",
                        "send_as": "user",
                        "receive_id_type": "open_id",
                        "receive_id": "ou_user",
                    },
                ],
            )

            webhook_messages = app_workflows.configured_bot_messages(config_path, "webhook")
            app_messages = app_workflows.configured_bot_messages(config_path, "app")
            user_messages = app_workflows.configured_bot_messages(config_path, "user")

        self.assertEqual([message["name"] for message in webhook_messages], ["Auto webhook"])
        self.assertEqual([message["name"] for message in app_messages], ["Auto app"])
        self.assertEqual([message["name"] for message in user_messages], ["Explicit user"])

    def test_validates_the_target_required_by_the_selected_mode(self):
        cases = [
            ("webhook", {"name": "Missing hook", "send_as": "webhook"}, "Webhook 地址"),
            ("app", {"name": "Missing app receiver", "send_as": "app"}, "接收 ID"),
            ("user", {"name": "Missing user receiver", "send_as": "user"}, "接收 ID"),
        ]
        for send_as, message, expected_error in cases:
            with self.subTest(send_as=send_as), tempfile.TemporaryDirectory() as temp_dir:
                config_path = self._write_config(temp_dir, [message])

                with self.assertRaisesRegex(RuntimeError, expected_error):
                    app_workflows.configured_bot_messages(config_path, send_as)


class CenterWaybillFreshnessTests(unittest.TestCase):
    @staticmethod
    def _file_with_modified_date(folder, modified_date):
        path = Path(folder) / "中心运单查询.xlsx"
        path.touch()
        timestamp = datetime.combine(modified_date, time(12, 30)).timestamp()
        os.utime(path, (timestamp, timestamp))
        return path

    def test_today_file_has_no_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._file_with_modified_date(temp_dir, date(2026, 8, 20))

            warning = app_workflows.center_waybill_file_freshness_warning(
                path,
                current_date=date(2026, 8, 20),
            )

        self.assertIsNone(warning)

    def test_yesterday_file_warning_names_file_and_modified_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._file_with_modified_date(temp_dir, date(2026, 8, 19))

            warning = app_workflows.center_waybill_file_freshness_warning(
                path,
                current_date=date(2026, 8, 20),
            )

        self.assertIn("最后修改时间是昨天", warning)
        self.assertIn("中心运单查询.xlsx", warning)
        self.assertIn("2026-08-19 12:30", warning)

    def test_older_file_warning_reports_age(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._file_with_modified_date(temp_dir, date(2026, 8, 17))

            warning = app_workflows.center_waybill_file_freshness_warning(
                path,
                current_date=date(2026, 8, 20),
            )

        self.assertIn("最后修改时间是3 天前", warning)

    def test_future_dated_file_also_warns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._file_with_modified_date(temp_dir, date(2026, 8, 21))

            warning = app_workflows.center_waybill_file_freshness_warning(
                path,
                current_date=date(2026, 8, 20),
            )

        self.assertIn("最后修改时间是未来日期", warning)

    def test_run_report_blocks_old_file_before_any_send_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._file_with_modified_date(temp_dir, date(2000, 1, 1))
            with mock.patch.object(app_workflows, "configured_bot_messages") as configured:
                with self.assertRaisesRegex(RuntimeError, "为防止误发，操作已停止"):
                    app_workflows.run_report(path, send_as="webhook")

        configured.assert_not_called()

    def test_run_report_updates_from_the_exact_explicitly_allowed_old_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            source = app_dir / "中心运单查询 (new).xlsx"
            source.write_bytes(b"selected workbook")
            timestamp = datetime.combine(date(2000, 1, 1), time(12)).timestamp()
            os.utime(source, (timestamp, timestamp))
            update_module = mock.Mock()
            build_module = mock.Mock()
            sender_module = mock.Mock()
            sender_argv = []
            sender_module.main.side_effect = lambda: sender_argv.append(app_workflows.sys.argv[:])

            def import_module(name):
                return {
                    "update_report_data": update_module,
                    "build_message_pack": build_module,
                    "send_lark_images": sender_module,
                }[name]

            with (
                mock.patch.object(app_workflows, "APP_DIR", app_dir),
                mock.patch.object(
                    app_workflows,
                    "configured_bot_messages",
                    return_value=[{}],
                ) as configured,
                mock.patch.object(app_workflows.importlib, "import_module", side_effect=import_module),
                mock.patch.object(app_workflows.importlib, "reload", side_effect=lambda module: module),
            ):
                result = app_workflows.run_report(
                    source,
                    allow_old_source=True,
                    send_as="webhook",
                )

            target = app_dir / "中心运单查询.xlsx"
            self.assertEqual(target.read_bytes(), b"selected workbook")
            update_module.main.assert_called_once_with(target, allow_old_source=True)
            build_module.main.assert_called_once_with()
            sender_module.main.assert_called_once_with()
            configured.assert_called_once_with(send_as="webhook")
            self.assertEqual(
                sender_argv,
                [["send_lark_images.py", "--send", "--send-as", "webhook"]],
            )
            self.assertIn("Webhook 机器人", result)

    def test_update_report_guard_can_only_be_bypassed_explicitly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "中心运单查询.xlsx"
            path.touch()
            timestamp = datetime.combine(date(2000, 1, 1), time(12)).timestamp()
            os.utime(path, (timestamp, timestamp))
            valid_frame = update_report_data.pd.DataFrame(
                {
                    "运单号": ["TEST-1"],
                    "路由码": ["301"],
                    "派件网点简码": ["AKL"],
                    "商家编号": ["C2103951401"],
                }
            )

            with mock.patch.object(update_report_data, "read_source_xlsx", return_value=valid_frame.copy()):
                with self.assertRaisesRegex(RuntimeError, "--allow-old-source"):
                    update_report_data.load_source_data(path)

            with (
                mock.patch.object(update_report_data, "read_source_xlsx", return_value=valid_frame.copy()),
                mock.patch.object(update_report_data, "find_latest_source_file") as find_latest,
            ):
                loaded = update_report_data.load_source_data(path, allow_old_source=True)

            self.assertEqual(loaded["运单号"].tolist(), ["TEST-1"])
            find_latest.assert_not_called()

    def test_daily_workflow_forwards_explicit_old_source_override(self):
        normal_update = run_daily_report.build_steps("app")[0][1]
        override_update = run_daily_report.build_steps("app", allow_old_source=True)[0][1]

        self.assertNotIn("--allow-old-source", normal_update)
        self.assertIn("--allow-old-source", override_update)


if __name__ == "__main__":
    unittest.main()
