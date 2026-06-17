import argparse
import base64
import hashlib
import hmac
import http.server
import json
import mimetypes
import secrets
import time
import urllib.parse
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


CONFIG_FILE = Path("lark_config.json")
DEFAULT_OPEN_PLATFORM_DOMAIN = "open.larksuite.com"
TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
USER_TOKEN_PATH = "/open-apis/authen/v2/oauth/token"
USER_AUTH_PATH = "/open-apis/authen/v1/index"
UPLOAD_IMAGE_PATH = "/open-apis/im/v1/images"
SEND_MESSAGE_PATH = "/open-apis/im/v1/messages"
RATE_LIMIT_CODE = 11232
MISSING_PERMISSION_CODE = 99991679
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
DEFAULT_USER_SCOPE = "im:message im:message.send_as_user"


def api_url(config, path):
    domain = config.get("open_platform_domain", DEFAULT_OPEN_PLATFORM_DOMAIN).strip()
    domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
    return f"https://{domain}{path}"


def post_json(url, payload, headers=None, timeout=20):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} from {url}: {body}") from error


def load_config(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Copy lark_config.example.json to {path} and fill in real values."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path, config):
    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sign(secret, timestamp):
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def get_tenant_access_token(config):
    data = post_json(
        api_url(config, TOKEN_PATH),
        {"app_id": config["app_id"], "app_secret": config["app_secret"]},
    )
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to get tenant_access_token: {data}")
    return data["tenant_access_token"]


def request_user_access_token(config, payload):
    data = post_json(
        api_url(config, USER_TOKEN_PATH),
        payload,
    )
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to get user_access_token: {data}")
    token_data = data.get("data") or data
    access_token = token_data.get("access_token") or token_data.get("user_access_token")
    if not access_token:
        raise RuntimeError(f"Missing user access token in response: {data}")
    return access_token, token_data.get("refresh_token")


def refresh_user_access_token(config, refresh_token):
    return request_user_access_token(
        config,
        {
            "grant_type": "refresh_token",
            "client_id": config["app_id"],
            "client_secret": config["app_secret"],
            "refresh_token": refresh_token,
        },
    )


def exchange_authorization_code(config, code, redirect_uri):
    return request_user_access_token(
        config,
        {
            "grant_type": "authorization_code",
            "client_id": config["app_id"],
            "client_secret": config["app_secret"],
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )


def get_authorization_code(config, redirect_uri):
    state = secrets.token_urlsafe(16)
    scope = config.get("user_scope", DEFAULT_USER_SCOPE).strip()
    query = urllib.parse.urlencode(
        {
            "app_id": config["app_id"],
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scope,
        }
    )
    auth_url = f"{api_url(config, USER_AUTH_PATH)}?{query}"
    parsed_redirect = urllib.parse.urlparse(redirect_uri)
    result = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            result["code"] = params.get("code", [""])[0]
            result["state"] = params.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Authorization complete. You can close this page.".encode("utf-8"))

        def log_message(self, format, *args):
            return

    port = parsed_redirect.port or 80
    if parsed_redirect.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("redirect_uri must use localhost or 127.0.0.1 for automatic authorization.")

    with http.server.HTTPServer(("127.0.0.1", port), CallbackHandler) as server:
        print("Opening Lark/Feishu authorization page...")
        print(f"If the browser does not open, paste this URL manually:\n{auth_url}")
        webbrowser.open(auth_url)
        server.handle_request()

    if result.get("state") != state:
        raise RuntimeError("Authorization state mismatch.")
    if not result.get("code"):
        raise RuntimeError("Authorization did not return a code.")
    return result["code"]


def upload_image(image_path, access_token, config):
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
        api_url(config, UPLOAD_IMAGE_PATH),
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} uploading image {image_path}: {body}") from error
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


def send_image_with_retry(webhook, image_key, secret="", max_attempts=5):
    waits = [10, 20, 40, 80]
    for attempt in range(max_attempts):
        payload = {
            "msg_type": "image",
            "content": {"image_key": image_key},
        }
        if secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = sign(secret, timestamp)

        data = post_json(webhook, payload)
        if data.get("code") == 0:
            return data
        if data.get("code") == RATE_LIMIT_CODE and attempt < max_attempts - 1:
            wait_seconds = waits[min(attempt, len(waits) - 1)]
            print(f"Rate limited by Lark; waiting {wait_seconds}s before retry...")
            time.sleep(wait_seconds)
            continue
        raise RuntimeError(f"Failed to send image: {data}")


def send_image_to_receiver(receive_id_type, receive_id, image_key, access_token, config):
    url = f"{api_url(config, SEND_MESSAGE_PATH)}?receive_id_type={receive_id_type}"
    data = post_json(
        url,
        {
            "receive_id": receive_id,
            "msg_type": "image",
            "content": json.dumps({"image_key": image_key}, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to send image to receiver: {data}")
    return data


def send_image_to_receiver_with_retry(receive_id_type, receive_id, image_key, access_token, config, max_attempts=5):
    waits = [10, 20, 40, 80]
    for attempt in range(max_attempts):
        url = f"{api_url(config, SEND_MESSAGE_PATH)}?receive_id_type={receive_id_type}"
        try:
            data = post_json(
                url,
                {
                    "receive_id": receive_id,
                    "msg_type": "image",
                    "content": json.dumps({"image_key": image_key}, ensure_ascii=False),
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except RuntimeError as error:
            message = str(error)
            if str(MISSING_PERMISSION_CODE) in message and "im:message:send" in message:
                raise RuntimeError(
                    "The Feishu /im/v1/messages endpoint did not receive a user token with "
                    "the required message scope. For user-identity sending, the app needs both "
                    "im:message and im:message.send_as_user, and the user must authorize both."
                ) from error
            raise
        if data.get("code") == 0:
            return data
        if data.get("code") == RATE_LIMIT_CODE and attempt < max_attempts - 1:
            wait_seconds = waits[min(attempt, len(waits) - 1)]
            print(f"Rate limited by Lark; waiting {wait_seconds}s before retry...")
            time.sleep(wait_seconds)
            continue
        raise RuntimeError(f"Failed to send image to receiver: {data}")


def message_send_as(message, default_send_as):
    send_as = (message.get("send_as") or default_send_as).strip().lower()
    if send_as == "auto":
        return "webhook" if message.get("webhook", "").startswith("https://") else "app"
    return send_as


def validate_messages(messages, default_send_as):
    errors = []
    for index, message in enumerate(messages, start=1):
        image_path = Path(message["image"])
        if not image_path.exists():
            errors.append(f"{index}. image not found: {image_path}")
        send_as = message_send_as(message, default_send_as)
        has_webhook = message.get("webhook", "").startswith("https://")
        has_receiver = message.get("receive_id_type") and message.get("receive_id")
        if send_as not in {"auto", "webhook", "app", "user"}:
            errors.append(
                f"{index}. invalid send_as for {message.get('name', '<unnamed>')}: {send_as}"
            )
        elif send_as == "webhook" and not has_webhook:
            errors.append(
                f"{index}. configure webhook for {message.get('name', '<unnamed>')}"
            )
        elif send_as in {"app", "user"} and not has_receiver:
            errors.append(
                f"{index}. configure receive_id_type+receive_id for "
                f"{message.get('name', '<unnamed>')}"
            )
    return errors


def print_plan(messages, default_send_as):
    print("Send plan:")
    for index, message in enumerate(messages, start=1):
        image_path = Path(message["image"])
        send_as = message_send_as(message, default_send_as)
        print(f"{index:02d}. {message.get('name', '<unnamed>')}")
        print(f"    image: {image_path}")
        print(f"    send_as: {send_as}")
        if send_as == "webhook":
            print(f"    webhook: {message.get('webhook', '')[:58]}...")
        else:
            print(f"    receiver: {message.get('receive_id_type')}:{message.get('receive_id')}")


def filter_messages_by_send_as(messages, default_send_as, send_as_filter):
    if send_as_filter == "all":
        return messages
    return [
        message
        for message in messages
        if message_send_as(message, default_send_as) == send_as_filter
    ]


def main():
    parser = argparse.ArgumentParser(description="Preview or send generated PNG reports to Lark groups.")
    parser.add_argument("--config", default=str(CONFIG_FILE), help="Path to lark_config.json")
    parser.add_argument("--send", action="store_true", help="Actually upload images and send them")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds to wait between messages")
    parser.add_argument(
        "--send-as",
        choices=["all", "webhook", "app", "user"],
        default="webhook",
        help="Only send messages that resolve to this delivery mode",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    messages = config.get("messages", [])
    if not messages:
        raise RuntimeError("No messages configured.")
    default_send_as = config.get("send_as", "auto")
    messages = filter_messages_by_send_as(messages, default_send_as, args.send_as)
    if not messages:
        raise RuntimeError(f"No messages matched --send-as {args.send_as}.")

    print_plan(messages, default_send_as)

    errors = validate_messages(messages, default_send_as)
    if errors:
        print("\nConfig/image errors:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    if not args.send:
        print("\nPreview only. Nothing was sent.")
        print("Run with --send when you are ready.")
        return
    if args.send_as == "all":
        print("\nWarning: --send-as all will send every configured delivery mode.")

    tokens = {}
    required_modes = {
        message_send_as(message, default_send_as)
        for message in messages
        if message_send_as(message, default_send_as) in {"app", "user"}
    }
    if required_modes:
        tokens["app"] = get_tenant_access_token(config)
    if "user" in required_modes:
        if config.get("user_refresh_token"):
            tokens["user"], new_refresh_token = refresh_user_access_token(
                config,
                config["user_refresh_token"],
            )
        else:
            redirect_uri = config.get("redirect_uri", DEFAULT_REDIRECT_URI)
            code = get_authorization_code(config, redirect_uri)
            tokens["user"], new_refresh_token = exchange_authorization_code(config, code, redirect_uri)
        if new_refresh_token and new_refresh_token != config.get("user_refresh_token"):
            config["user_refresh_token"] = new_refresh_token
            save_config(config_path, config)
            print("Updated user_refresh_token in config.")

    image_key_cache = {}
    for message in messages:
        image_path = Path(message["image"])
        send_as = message_send_as(message, default_send_as)
        if image_path not in image_key_cache:
            image_key_cache[image_path] = upload_image(image_path, tokens["app"], config)
        if send_as == "webhook":
            send_image_with_retry(message["webhook"], image_key_cache[image_path], message.get("secret", ""))
        else:
            send_image_to_receiver_with_retry(
                message["receive_id_type"],
                message["receive_id"],
                image_key_cache[image_path],
                tokens[send_as],
                config,
            )
        print(f"Sent: {message.get('name', image_path.name)}")
        time.sleep(args.delay)

    print("Done.")


if __name__ == "__main__":
    main()
