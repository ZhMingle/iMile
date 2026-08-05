import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app_workflows
import send_lark_images


class SendLarkTextTests(unittest.TestCase):
    def test_route_names_select_the_matching_route_groups_only(self):
        destinations = [
            {"name": "HMT各线路预测"},
            {"name": "TRG各线路预测"},
            {"name": "Send as me HMT各线路预测"},
            {"name": "NPL_HST各线路预测"},
            {"name": "本地管理团队"},
        ]

        codes, indexes = app_workflows.route_group_destination_indexes(
            destinations,
            "今天 HMT - TRG 有更新",
        )

        self.assertEqual(codes, ["HMT", "TRG"])
        self.assertEqual(indexes, [0, 1])

    def test_route_group_search_handles_a_shared_npl_hst_group(self):
        destinations = [{"name": "NPL_HST各线路预测"}]
        codes, indexes = app_workflows.route_group_destination_indexes(destinations, "HST")

        self.assertEqual(codes, ["HST"])
        self.assertEqual(indexes, [0])

    def test_webhook_text_payload(self):
        with mock.patch.object(
            send_lark_images,
            "post_json",
            return_value={"code": 0},
        ) as post_json:
            send_lark_images.send_text_with_retry(
                "https://example.test/hook",
                "Hello 群",
            )

        post_json.assert_called_once_with(
            "https://example.test/hook",
            {"msg_type": "text", "content": {"text": "Hello 群"}},
        )

    def test_api_text_payload(self):
        config = {"open_platform_domain": "open.feishu.cn"}
        with mock.patch.object(
            send_lark_images,
            "post_json",
            return_value={"code": 0, "data": {"message_id": "om_123"}},
        ) as post_json:
            send_lark_images.send_text_to_receiver_with_retry(
                "chat_id",
                "oc_123",
                "同一条消息",
                "token",
                config,
            )

        _, payload = post_json.call_args.args
        self.assertEqual(payload["receive_id"], "oc_123")
        self.assertEqual(payload["msg_type"], "text")
        self.assertEqual(json.loads(payload["content"]), {"text": "同一条消息"})

    def test_one_text_is_dispatched_to_multiple_destinations(self):
        destinations = [
            {
                "name": "Webhook group",
                "send_as": "webhook",
                "webhook": "https://example.test/hook",
            },
            {
                "name": "App group",
                "send_as": "app",
                "receive_id_type": "chat_id",
                "receive_id": "oc_123",
            },
        ]
        config = {"send_as": "auto"}
        with (
            mock.patch.object(send_lark_images, "get_tokens", return_value={"app": "token"}),
            mock.patch.object(send_lark_images, "send_text_with_retry") as send_webhook,
            mock.patch.object(
                send_lark_images,
                "send_text_to_receiver_with_retry",
                return_value={"code": 0, "data": {"message_id": "om_123"}},
            ) as send_api,
            mock.patch.object(send_lark_images, "append_sent_log") as append_log,
        ):
            count = send_lark_images.send_text_to_destinations(
                "Broadcast",
                destinations,
                config,
                delay=0,
            )

        self.assertEqual(count, 2)
        send_webhook.assert_called_once()
        send_api.assert_called_once()
        self.assertEqual(append_log.call_args.args[1]["msg_type"], "text")

    def test_workflow_selects_only_requested_group_indexes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "lark_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "messages": [
                            {"name": "A", "send_as": "webhook", "webhook": "https://a"},
                            {"name": "B", "send_as": "webhook", "webhook": "https://b"},
                            {"name": "C", "send_as": "webhook", "webhook": "https://c"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                send_lark_images,
                "send_text_to_destinations",
                return_value=2,
            ) as send:
                result = app_workflows.run_text_message(
                    "Notice",
                    [0, 2],
                    config_path=config_path,
                )

        selected = send.call_args.args[1]
        self.assertEqual([item["name"] for item in selected], ["A", "C"])
        self.assertEqual(result, "文字消息已发送到 2 个群。")


if __name__ == "__main__":
    unittest.main()
