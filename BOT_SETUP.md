# Lark 机器人配置

1. 在飞书开放平台创建企业自建应用，并启用机器人能力。
2. 为应用开通发送消息和上传图片所需权限，并发布应用版本。
3. 将机器人加入需要接收报表的群。
4. 复制 `lark_bot_config.example.json` 为 `lark_config.json`。
5. 填写 `app_id`、`app_secret`，以及每张图片对应群的 `chat_id`。

应用仅发送 `send_as: "app"` 的消息，不使用个人账号授权。

