import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import time
import urllib.error
import urllib.request
from pathlib import Path


CONFIG_FILE = Path("lark_config.json")
TOKEN_URL = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
UPLOAD_IMAGE_URL = "https://open.larksuite.com/open-apis/im/v1/images"
SEND_MESSAGE_URL = "https://open.larksuite.com/open-apis/im/v1/messages"


def post_json(url, payload, headers=None, timeout=20):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_config(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Copy lark_config.example.json to {path} and fill in real values."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def sign(secret, timestamp):
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def get_tenant_access_token(app_id, app_secret):
    data = post_json(
        TOKEN_URL,
        {"app_id": app_id, "app_secret": app_secret},
    )
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to get tenant_access_token: {data}")
    return data["tenant_access_token"]


def upload_image(image_path, tenant_access_token):
    boundary = f"----codex-lark-{int(time.time() * 1000)}"
    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="image_type"\r\n\r\n'
        "message\r\n".encode("utf-8"),
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
        image_path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    body = b"".join(parts)
    request = urllib.request.Request(
        UPLOAD_IMAGE_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {tenant_access_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to upload image {image_path}: {data}")
    return data["data"]["image_key"]


def send_image(webhook, image_key, secret=""):
    payload = {
        "msg_type": "image",
        "content": {"image_key": image_key},
    }
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = sign(secret, timestamp)

    data = post_json(webhook, payload)
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to send image: {data}")
    return data


def send_image_to_receiver(receive_id_type, receive_id, image_key, tenant_access_token):
    url = f"{SEND_MESSAGE_URL}?receive_id_type={receive_id_type}"
    data = post_json(
        url,
        {
            "receive_id": receive_id,
            "msg_type": "image",
            "content": json.dumps({"image_key": image_key}, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {tenant_access_token}"},
    )
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to send image to receiver: {data}")
    return data


def validate_messages(messages):
    errors = []
    for index, message in enumerate(messages, start=1):
        image_path = Path(message["image"])
        if not image_path.exists():
            errors.append(f"{index}. image not found: {image_path}")
        has_webhook = message.get("webhook", "").startswith("https://")
        has_receiver = message.get("receive_id_type") and message.get("receive_id")
        if not has_webhook and not has_receiver:
            errors.append(
                f"{index}. configure either webhook or receive_id_type+receive_id for "
                f"{message.get('name', '<unnamed>')}"
            )
    return errors


def print_plan(messages):
    print("Send plan:")
    for index, message in enumerate(messages, start=1):
        image_path = Path(message["image"])
        print(f"{index:02d}. {message.get('name', '<unnamed>')}")
        print(f"    image: {image_path}")
        if message.get("webhook"):
            print(f"    webhook: {message.get('webhook', '')[:58]}...")
        else:
            print(f"    receiver: {message.get('receive_id_type')}:{message.get('receive_id')}")


def main():
    parser = argparse.ArgumentParser(description="Preview or send generated PNG reports to Lark groups.")
    parser.add_argument("--config", default=str(CONFIG_FILE), help="Path to lark_config.json")
    parser.add_argument("--send", action="store_true", help="Actually upload images and send them")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    messages = config.get("messages", [])
    if not messages:
        raise RuntimeError("No messages configured.")

    print_plan(messages)

    errors = validate_messages(messages)
    if errors:
        print("\nConfig/image errors:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    if not args.send:
        print("\nPreview only. Nothing was sent.")
        print("Run with --send when you are ready.")
        return

    confirm = input("\nType SEND to upload images and send to Lark: ").strip()
    if confirm != "SEND":
        print("Cancelled.")
        return

    tenant_access_token = get_tenant_access_token(config["app_id"], config["app_secret"])

    image_key_cache = {}
    for message in messages:
        image_path = Path(message["image"])
        if image_path not in image_key_cache:
            image_key_cache[image_path] = upload_image(image_path, tenant_access_token)
        if message.get("webhook"):
            send_image(message["webhook"], image_key_cache[image_path], message.get("secret", ""))
        else:
            send_image_to_receiver(
                message["receive_id_type"],
                message["receive_id"],
                image_key_cache[image_path],
                tenant_access_token,
            )
        print(f"Sent: {message.get('name', image_path.name)}")
        time.sleep(0.4)

    print("Done.")


if __name__ == "__main__":
    main()
