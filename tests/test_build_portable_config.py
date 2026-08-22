import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import build_portable_config


class PortableConfigTests(unittest.TestCase):
    def test_keeps_only_webhook_delivery_fields(self):
        source = {
            "app_id": " app-id ",
            "app_secret": " app-secret ",
            "open_platform_domain": " open.example.test ",
            "send_as": "auto",
            "redirect_uri": "http://localhost/callback",
            "user_scope": "user-scope",
            "user_refresh_token": "refresh-token",
            "access_token": "access-token",
            "token_cache": {"token": "cached-token"},
            "sent_log": "output/sent.jsonl",
            "messages": [
                {
                    "name": "Webhook report",
                    "webhook": "https://example.test/report",
                    "secret": "hook-secret",
                    "image": "output/report.png",
                    "receive_id": "must-not-survive",
                    "extra": "must-not-survive",
                },
                {
                    "name": "Send as user",
                    "send_as": "user",
                    "receive_id_type": "chat_id",
                    "receive_id": "user-chat",
                    "image": "output/user.png",
                },
                {
                    "name": "Send as app",
                    "send_as": "app",
                    "receive_id_type": "chat_id",
                    "receive_id": "app-chat",
                    "image": "output/app.png",
                },
            ],
            "text_destinations": [
                {
                    "name": "Webhook text",
                    "send_as": "webhook",
                    "webhook": "https://example.test/text",
                    "secret": "text-secret",
                    "receive_id": "must-not-survive",
                },
                {
                    "name": "User text",
                    "send_as": "user",
                    "receive_id_type": "chat_id",
                    "receive_id": "user-chat",
                },
            ],
        }

        portable = build_portable_config.build_portable_config(source)

        self.assertEqual(
            set(portable),
            {
                "app_id",
                "app_secret",
                "open_platform_domain",
                "send_as",
                "messages",
                "text_destinations",
            },
        )
        self.assertEqual(portable["app_id"], "app-id")
        self.assertEqual(portable["app_secret"], "app-secret")
        self.assertEqual(portable["send_as"], "webhook")
        self.assertEqual(len(portable["messages"]), 1)
        self.assertEqual(len(portable["text_destinations"]), 1)
        self.assertEqual(
            set(portable["messages"][0]),
            {"name", "send_as", "webhook", "secret", "image"},
        )
        self.assertEqual(
            set(portable["text_destinations"][0]),
            {"name", "send_as", "webhook", "secret"},
        )
        serialized = json.dumps(portable)
        for forbidden in (
            "user_refresh_token",
            "access_token",
            "token_cache",
            "sent_log",
            "receive_id",
            "user-chat",
            "app-chat",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_derives_text_targets_and_keeps_only_runtime_valid_groups(self):
        source = {
            "app_id": "app-id",
            "app_secret": "app-secret",
            "messages": [
                {
                    "name": "A",
                    "send_as": "webhook",
                    "webhook": "https://example.test/shared",
                    "secret": "same-secret",
                    "image": "output/a.png",
                },
                {
                    "name": "B",
                    "send_as": "webhook",
                    "webhook": "https://example.test/shared",
                    "secret": "same-secret",
                    "image": "output/b.png",
                },
                {
                    "name": "C",
                    "send_as": "webhook",
                    "webhook": "https://example.test/other",
                    "image": "output/c.png",
                },
                {
                    "name": "Personal",
                    "send_as": "user",
                    "receive_id": "personal-chat",
                    "image": "output/personal.png",
                },
            ],
            "text_destination_groups": [
                {"name": "Shared", "members": ["A", "B"]},
                {"name": "Missing", "members": ["Personal"]},
                {"name": "Mixed", "members": ["B", "C"]},
                {"name": "Overlap", "members": ["A"]},
                {"name": "", "members": ["C"]},
            ],
        }

        portable = build_portable_config.build_portable_config(source)

        self.assertEqual(
            [destination["name"] for destination in portable["text_destinations"]],
            ["A", "B", "C"],
        )
        self.assertEqual(
            portable["text_destination_groups"],
            [{"name": "Shared", "members": ["A", "B"]}],
        )

    def test_requires_app_credentials_and_a_webhook_report(self):
        with self.assertRaisesRegex(build_portable_config.PortableConfigError, "app_id"):
            build_portable_config.build_portable_config({"messages": []})

        with self.assertRaisesRegex(build_portable_config.PortableConfigError, "Webhook"):
            build_portable_config.build_portable_config(
                {
                    "app_id": "app-id",
                    "app_secret": "app-secret",
                    "messages": [
                        {
                            "name": "Personal",
                            "send_as": "user",
                            "image": "output/personal.png",
                        }
                    ],
                }
            )

    def test_cli_missing_source_fails_without_creating_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "release" / "lark_config.json"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    build_portable_config.main(
                        [
                            "--source",
                            str(Path(temp_dir) / "missing.json"),
                            "--output",
                            str(output_path),
                        ]
                    )

            self.assertFalse(output_path.exists())

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("找不到 lark_config.json", stderr.getvalue())

    def test_cli_output_never_prints_credentials_or_webhook(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            source_path = temp_dir / "lark_config.json"
            output_path = temp_dir / "release" / "lark_config.json"
            source_path.write_text(
                json.dumps(
                    {
                        "app_id": "private-app-id",
                        "app_secret": "private-app-secret",
                        "messages": [
                            {
                                "name": "Daily",
                                "send_as": "webhook",
                                "webhook": "https://private.example.test/hook",
                                "image": "output/daily.png",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = build_portable_config.main(
                    ["--source", str(source_path), "--output", str(output_path)]
                )

            console_output = stdout.getvalue() + stderr.getvalue()
            self.assertEqual(result, 0)
            self.assertTrue(output_path.is_file())
            self.assertNotIn("private-app-id", console_output)
            self.assertNotIn("private-app-secret", console_output)
            self.assertNotIn("https://", console_output)


class PortableBuildScriptTests(unittest.TestCase):
    def test_standard_build_does_not_copy_real_local_configs(self):
        script = Path("build_windows_app.bat").read_text(encoding="utf-8")

        self.assertNotIn('copy /Y "lark_config.json"', script)
        self.assertNotIn('copy /Y "wecom_download_config.json"', script)

    def test_portable_build_uses_restricted_config_and_creates_zip(self):
        script = Path("build_portable_release.bat").read_text(encoding="utf-8")

        self.assertIn("build_portable_config.py", script)
        self.assertIn("Compress-Archive", script)
        self.assertIn("PORTABLE_README.md", script)
        self.assertIn('if not exist "lark_config.json"', script)
        self.assertNotIn('copy /Y "lark_config.json"', script)
        self.assertNotIn('copy /Y "wecom_download_config.json"', script)


if __name__ == "__main__":
    unittest.main()
