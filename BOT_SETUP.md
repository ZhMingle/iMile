# Lark 机器人配置

1. 在飞书开放平台创建企业自建应用，并启用机器人能力。
2. 为应用开通发送消息和上传图片所需权限，并发布应用版本。
3. 将机器人加入需要接收报表的群。
4. 复制 `lark_bot_config.example.json` 为 `lark_config.json`。
5. 填写 `app_id`、`app_secret`，以及每张图片对应群的 `chat_id`。

应用仅发送 `send_as: "app"` 的消息，不使用个人账号授权。

## 企业微信 TEMU 自动收件

1. 安装依赖：`python -m pip install -r requirements.txt`。
2. 重新运行 `build_windows_app.bat`。
3. 打开程序后点击“收件设置”，填写 TEMU 会话名称和企业微信下载目录。
4. 保持企业微信已登录，目标附件在会话当前画面可见，然后点击“开始自动收件”。

程序会将文件按日期归档到 `input/TEMU/`，并在 `.downloaded_files.json` 中记录文件哈希以避免重复处理。
