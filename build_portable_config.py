import argparse
import json
import os
from pathlib import Path
import tempfile


DEFAULT_OPEN_PLATFORM_DOMAIN = "open.larksuite.com"
MESSAGE_KEYS = ("name", "send_as", "webhook", "secret", "image")
DESTINATION_KEYS = ("name", "send_as", "webhook", "secret")


class PortableConfigError(ValueError):
    """The local configuration cannot produce a safe portable configuration."""


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _effective_send_as(entry, default_send_as):
    send_as = str(entry.get("send_as") or default_send_as).strip().lower()
    if send_as == "auto":
        webhook = str(entry.get("webhook", "")).strip().lower()
        return "webhook" if webhook.startswith("https://") else "app"
    return send_as


def _is_webhook_entry(entry, default_send_as):
    if not isinstance(entry, dict):
        return False
    if _effective_send_as(entry, default_send_as) != "webhook":
        return False
    webhook = entry.get("webhook")
    return _nonempty_string(webhook) and webhook.strip().lower().startswith("https://")


def _copy_whitelisted(entry, keys):
    copied = {
        key: entry[key].strip()
        for key in keys
        if isinstance(entry.get(key), str)
    }
    copied["send_as"] = "webhook"
    return copied


def _portable_messages(config, default_send_as):
    messages = []
    for entry in config.get("messages") or []:
        if not _is_webhook_entry(entry, default_send_as):
            continue
        if not _nonempty_string(entry.get("name")):
            continue
        if not _nonempty_string(entry.get("image")):
            continue
        messages.append(_copy_whitelisted(entry, MESSAGE_KEYS))
    return messages


def _portable_destinations(config, messages, default_send_as):
    source = config.get("text_destinations") or config.get("messages") or []
    destinations = []
    for entry in source:
        if not _is_webhook_entry(entry, default_send_as):
            continue
        if not _nonempty_string(entry.get("name")):
            continue
        destinations.append(_copy_whitelisted(entry, DESTINATION_KEYS))

    if not destinations:
        destinations = [_copy_whitelisted(message, DESTINATION_KEYS) for message in messages]
    return destinations


def _valid_destination_groups(config, destinations):
    groups = []
    consumed_indexes = set()

    for group in config.get("text_destination_groups") or []:
        if not isinstance(group, dict):
            continue
        name = str(group.get("name", "")).strip()
        if not isinstance(group.get("members"), list):
            continue
        members = [
            str(member).strip()
            for member in group.get("members") or []
            if str(member).strip()
        ]
        if not name or not members:
            continue

        member_indexes = []
        missing_member = False
        for member in members:
            matches = [
                index
                for index, destination in enumerate(destinations)
                if destination.get("name") == member
            ]
            if not matches:
                missing_member = True
                break
            member_indexes.extend(matches)
        if missing_member or any(index in consumed_indexes for index in member_indexes):
            continue

        identities = {
            (destination.get("webhook", ""), destination.get("secret", ""))
            for index, destination in enumerate(destinations)
            if index in member_indexes
        }
        if len(identities) != 1:
            continue

        groups.append({"name": name, "members": members})
        consumed_indexes.update(member_indexes)

    return groups


def build_portable_config(config):
    if not isinstance(config, dict):
        raise PortableConfigError("lark_config.json 的顶层必须是 JSON 对象。")

    app_id = config.get("app_id")
    app_secret = config.get("app_secret")
    if not _nonempty_string(app_id) or not _nonempty_string(app_secret):
        raise PortableConfigError("lark_config.json 缺少有效的 app_id 或 app_secret。")

    default_send_as = str(config.get("send_as", "auto")).strip().lower()
    messages = _portable_messages(config, default_send_as)
    if not messages:
        raise PortableConfigError("lark_config.json 中没有有效的 Webhook 日报消息配置。")

    destinations = _portable_destinations(config, messages, default_send_as)
    groups = _valid_destination_groups(config, destinations)
    domain = config.get("open_platform_domain", DEFAULT_OPEN_PLATFORM_DOMAIN)
    if not _nonempty_string(domain):
        domain = DEFAULT_OPEN_PLATFORM_DOMAIN

    portable = {
        "app_id": app_id.strip(),
        "app_secret": app_secret.strip(),
        "open_platform_domain": domain.strip(),
        "send_as": "webhook",
        "messages": messages,
        "text_destinations": destinations,
    }
    if groups:
        portable["text_destination_groups"] = groups
    return portable


def load_source_config(path):
    path = Path(path)
    if not path.is_file():
        raise PortableConfigError("找不到 lark_config.json，便携版构建已停止。")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PortableConfigError("无法读取有效的 lark_config.json，便携版构建已停止。") from error


def write_portable_config(path, config):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def create_portable_config(source_path, output_path):
    source = load_source_config(source_path)
    portable = build_portable_config(source)
    write_portable_config(output_path, portable)
    return portable


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Create a restricted Webhook-only configuration for the portable release."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        create_portable_config(args.source, args.output)
    except PortableConfigError as error:
        parser.exit(1, f"错误：{error}\n")
    print("便携版共享配置已生成。")
    return 0


if __name__ == "__main__":
    main()
