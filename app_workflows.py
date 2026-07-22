import importlib
import json
import os
from pathlib import Path
import shutil
import sys


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
os.chdir(APP_DIR)


def configured_bot_messages(config_path=None):
    config_path = Path(config_path or APP_DIR / "lark_config.json")
    if not config_path.exists():
        raise RuntimeError("找不到 lark_config.json，请先完成机器人配置。")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not config.get("app_id") or not config.get("app_secret"):
        raise RuntimeError("lark_config.json 缺少 app_id 或 app_secret。")

    default_send_as = str(config.get("send_as", "auto")).strip().lower()
    messages = [
        message
        for message in config.get("messages", [])
        if str(message.get("send_as") or default_send_as).strip().lower() == "app"
    ]
    if not messages:
        raise RuntimeError("lark_config.json 中没有 send_as=app 的机器人消息配置。")

    incomplete = [
        message.get("name", "未命名图片")
        for message in messages
        if not message.get("receive_id_type") or not message.get("receive_id")
    ]
    if incomplete:
        names = "、".join(incomplete[:5])
        suffix = " 等" if len(incomplete) > 5 else ""
        raise RuntimeError(f"以下机器人消息缺少群 ID：{names}{suffix}")
    return messages


def run_tracking(files):
    module = importlib.import_module("getTrakingNum")
    output_file = module.main(files)
    count = len([line for line in output_file.read_text(encoding="utf-8").splitlines() if line.strip()])
    return f"已提取 {count} 个唯一运单号，并复制到剪贴板。"


def run_wecom_download():
    print("自动收件任务已启动。")
    module = importlib.import_module("wecom_downloader")
    return module.download_temu_files()


def run_dc_export():
    module = importlib.import_module("imile_dc_downloader")
    target = module.download_center_waybill_query()
    return f"中心运单查询已下载并校验：{target.name}"


def run_auto_dispatch(route_code, driver_spec):
    module = importlib.import_module("imile_dispatcher")
    return module.dispatch_route(route_code, driver_spec)


def open_wecom_config():
    module = importlib.import_module("wecom_downloader")
    if not module.CONFIG_PATH.exists():
        if not module.EXAMPLE_CONFIG_PATH.exists():
            raise RuntimeError("找不到企业微信配置模板。")
        shutil.copy2(module.EXAMPLE_CONFIG_PATH, module.CONFIG_PATH)
    if sys.platform != "win32":
        raise RuntimeError(f"请编辑配置文件：{module.CONFIG_PATH}")
    os.startfile(module.CONFIG_PATH)
    return module.CONFIG_PATH


def run_report(source_file):
    messages = configured_bot_messages()
    print(f"Robot destinations configured: {len(messages)}")

    target = APP_DIR / "中心运单查询.xlsx"
    source_file = Path(source_file)
    if source_file.resolve() != target.resolve():
        shutil.copy2(source_file, target)
        print(f"Selected source: {source_file.name}")

    update_module = importlib.import_module("update_report_data")
    update_module.main()

    build_module = importlib.reload(importlib.import_module("build_message_pack"))
    build_module.main()

    sender = importlib.import_module("send_lark_images")
    original_argv = sys.argv[:]
    try:
        sys.argv = ["send_lark_images.py", "--send", "--send-as", "app"]
        sender.main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError("机器人发送失败，请查看运行记录。") from exc
    finally:
        sys.argv = original_argv
    return f"报表已生成，并发送到 {len(messages)} 个机器人目标。"
