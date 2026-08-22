import importlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

from report_source_freshness import center_waybill_file_freshness_warning


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
os.chdir(APP_DIR)

ROUTE_GROUP_CODES = ("WLTV2", "HMT", "TRG", "NPL", "HST", "PMN", "TPO", "RTR", "WGR")


def load_lark_config(config_path=None):
    config_path = Path(config_path or APP_DIR / "lark_config.json")
    if not config_path.exists():
        raise RuntimeError("找不到 lark_config.json，请先完成飞书配置。")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    return config_path, config


def _resolved_bot_send_as(message, default_send_as):
    send_as = str(message.get("send_as") or default_send_as).strip().lower()
    if send_as == "auto":
        webhook = str(message.get("webhook") or "").strip()
        return "webhook" if webhook.startswith("https://") else "app"
    return send_as


def _normalize_bot_send_as(send_as):
    send_as = str(send_as).strip().lower()
    if send_as not in {"app", "webhook", "user"}:
        raise RuntimeError("发送模式必须是 app、webhook 或 user。")
    return send_as


def configured_bot_messages(config_path=None, send_as="app"):
    send_as = _normalize_bot_send_as(send_as)
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
        if _resolved_bot_send_as(message, default_send_as) == send_as
    ]
    if not messages:
        raise RuntimeError(f"lark_config.json 中没有 send_as={send_as} 的机器人消息配置。")

    if send_as == "webhook":
        incomplete = [
            message.get("name", "未命名图片")
            for message in messages
            if not str(message.get("webhook") or "").strip().startswith("https://")
        ]
        missing_target = "有效的 Webhook 地址"
    else:
        incomplete = [
            message.get("name", "未命名图片")
            for message in messages
            if not message.get("receive_id_type") or not message.get("receive_id")
        ]
        missing_target = "接收 ID"
    if incomplete:
        names = "、".join(incomplete[:5])
        suffix = " 等" if len(incomplete) > 5 else ""
        raise RuntimeError(f"以下 {send_as} 机器人消息缺少{missing_target}：{names}{suffix}")
    return messages


def configured_text_destinations(config_path=None):
    _, config = load_lark_config(config_path)
    destinations = list(config.get("text_destinations") or config.get("messages") or [])
    destinations = [destination for destination in destinations if destination.get("name")]
    return group_text_destinations(
        destinations,
        config.get("text_destination_groups") or [],
        config.get("send_as", "auto"),
    )


def _text_destination_identity(destination, default_send_as):
    send_as = str(destination.get("send_as") or default_send_as).strip().lower()
    if send_as == "auto":
        send_as = "webhook" if str(destination.get("webhook", "")).startswith("https://") else "app"
    if send_as == "webhook":
        return (
            send_as,
            str(destination.get("webhook", "")).strip(),
            str(destination.get("secret", "")).strip(),
        )
    if send_as in {"app", "user"}:
        return (
            send_as,
            str(destination.get("receive_id_type", "")).strip(),
            str(destination.get("receive_id", "")).strip(),
        )
    return None


def group_text_destinations(destinations, group_specs, default_send_as="auto"):
    destinations = list(destinations)
    replacements = {}
    consumed_indexes = set()

    for group_spec in group_specs:
        group_name = str(group_spec.get("name", "")).strip()
        member_names = [
            str(name).strip()
            for name in group_spec.get("members", [])
            if str(name).strip()
        ]
        if not group_name or not member_names:
            raise RuntimeError("text_destination_groups 中的每一组都必须填写 name 和 members。")

        member_indexes = []
        missing_names = []
        for member_name in member_names:
            matches = [
                index
                for index, destination in enumerate(destinations)
                if str(destination.get("name", "")).strip() == member_name
            ]
            if not matches:
                missing_names.append(member_name)
            else:
                member_indexes.extend(matches)
        if missing_names:
            raise RuntimeError(
                f"文字群组“{group_name}”找不到配置项：{'、'.join(missing_names)}"
            )
        if any(index in consumed_indexes for index in member_indexes):
            raise RuntimeError(f"文字群组“{group_name}”与其他群组重复使用了同一个配置项。")

        identities = {
            _text_destination_identity(destinations[index], default_send_as)
            for index in member_indexes
        }
        if None in identities or len(identities) != 1:
            raise RuntimeError(
                f"文字群组“{group_name}”中的配置不是同一个接收群，已停止合并。"
            )

        first_index = min(member_indexes)
        grouped_destination = dict(destinations[first_index])
        grouped_destination["name"] = group_name
        grouped_destination.pop("image", None)
        replacements[first_index] = grouped_destination
        consumed_indexes.update(member_indexes)

    grouped = []
    for index, destination in enumerate(destinations):
        if index in replacements:
            grouped.append(replacements[index])
        elif index not in consumed_indexes:
            grouped.append(destination)
    return grouped


def route_group_destination_indexes(destinations, text):
    normalized_text = str(text).upper()
    requested_codes = [
        code
        for code in ROUTE_GROUP_CODES
        if re.search(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", normalized_text)
    ]
    if not requested_codes:
        return [], []

    matched_indexes = []
    for index, destination in enumerate(destinations):
        name = str(destination.get("name", "")).strip()
        normalized_name = name.upper()
        if normalized_name.startswith("SEND AS ME "):
            continue
        if any(code in normalized_name for code in requested_codes):
            matched_indexes.append(index)
    return requested_codes, matched_indexes


def run_text_message(text, destination_indexes, config_path=None):
    config_path, config = load_lark_config(config_path)
    destinations = configured_text_destinations(config_path)
    indexes = sorted(set(int(index) for index in destination_indexes))
    if not indexes:
        raise RuntimeError("请至少选择一个群。")
    if any(index < 0 or index >= len(destinations) for index in indexes):
        raise RuntimeError("群列表已经变化，请重新打开程序后再试。")

    selected = [destinations[index] for index in indexes]
    sender = importlib.import_module("send_lark_images")
    sent_count = sender.send_text_to_destinations(
        text,
        selected,
        config,
        config_path=config_path,
    )
    return f"文字消息已发送到 {sent_count} 个群。"


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
    return module.dispatch_batch(route_code, driver_spec)


def run_auto_dispatch_manifest(manifest):
    module = importlib.import_module("imile_dispatcher")
    return module.dispatch_manifest(manifest)


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


def run_report(source_file, allow_old_source=False, send_as="app"):
    freshness_warning = center_waybill_file_freshness_warning(source_file)
    if freshness_warning and not allow_old_source:
        raise RuntimeError(
            f"{freshness_warning}\n\n"
            "为防止误发，操作已停止。请重新选择今天更新的文件。"
        )

    send_as = _normalize_bot_send_as(send_as)
    messages = configured_bot_messages(send_as=send_as)
    print(f"Robot destinations configured for {send_as}: {len(messages)}")

    target = APP_DIR / "中心运单查询.xlsx"
    source_file = Path(source_file)
    if source_file.resolve() != target.resolve():
        shutil.copy2(source_file, target)
        print(f"Selected source: {source_file.name}")

    update_module = importlib.import_module("update_report_data")
    update_module.main(target, allow_old_source=allow_old_source)

    build_module = importlib.reload(importlib.import_module("build_message_pack"))
    build_module.main()

    sender = importlib.import_module("send_lark_images")
    original_argv = sys.argv[:]
    try:
        sys.argv = ["send_lark_images.py", "--send", "--send-as", send_as]
        sender.main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError("机器人发送失败，请查看运行记录。") from exc
    finally:
        sys.argv = original_argv
    mode_label = {
        "app": "应用机器人",
        "webhook": "Webhook 机器人",
        "user": "用户身份",
    }[send_as]
    return f"报表已生成，并通过{mode_label}发送到 {len(messages)} 个目标。"
