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
DEFAULT_USER_SCOPE = "im:message im:message.send_as_user im:message:recall"
DEFAULT_SENT_LOG = Path("output/sent_messages.jsonl")
DEFAULT_USER_TOKEN_CACHE = Path("output/lark_user_token.json")


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


def delete_json(url, headers=None, timeout=20):
    request = urllib.request.Request(
        url,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="DELETE",
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
    return {
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in"),
    }


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


def get_message_id(data):
    payload = data.get("data") or {}
    return payload.get("message_id")


def append_sent_log(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), **record}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_sent_log(path):
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Invalid JSON in {path} line {line_number}: {line}") from error
    return records


def load_user_token_cache(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_user_token_cache(path, token_data):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_user_token_cache(path)
    expires_in = int(token_data.get("expires_in") or 7200)
    cached = {
        "access_token": token_data["access_token"],
        "expires_at": int(time.time()) + max(expires_in - 300, 60),
    }
    refresh_token = token_data.get("refresh_token") or existing.get("refresh_token")
    if refresh_token:
        cached["refresh_token"] = refresh_token
    path.write_text(json.dumps(cached, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cached_access_token(path):
    cache = load_user_token_cache(path)
    if cache.get("access_token") and int(cache.get("expires_at") or 0) > int(time.time()):
        return cache["access_token"]
    return None


def select_recent_messages_for_recall(path, send_as, count):
    records = load_sent_log(path)
    recalled = {
        record.get("message_id")
        for record in records
        if record.get("action") == "recall" and record.get("message_id")
    }
    candidates = [
        record
        for record in records
        if record.get("action") == "send"
        and record.get("send_as") == send_as
        and record.get("message_id")
        and record.get("message_id") not in recalled
    ]
    return list(reversed(candidates[-count:]))


def recall_message(message_id, access_token, config):
    url = f"{api_url(config, SEND_MESSAGE_PATH)}/{urllib.parse.quote(message_id, safe='')}"
    data = delete_json(url, headers={"Authorization": f"Bearer {access_token}"})
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to recall message {message_id}: {data}")
    return data


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


def get_tokens(config, config_path, modes, user_token_cache_path=DEFAULT_USER_TOKEN_CACHE):
    tokens = {}
    if modes:
        tokens["app"] = get_tenant_access_token(config)
    if "user" in modes:
        access_token = cached_access_token(user_token_cache_path)
        if access_token:
            tokens["user"] = access_token
            return tokens

        cache = load_user_token_cache(user_token_cache_path)
        refresh_token = config.get("user_refresh_token") or cache.get("refresh_token")
        if refresh_token:
            token_data = refresh_user_access_token(config, refresh_token)
        else:
            redirect_uri = config.get("redirect_uri", DEFAULT_REDIRECT_URI)
            code = get_authorization_code(config, redirect_uri)
            token_data = exchange_authorization_code(config, code, redirect_uri)

        tokens["user"] = token_data["access_token"]
        save_user_token_cache(user_token_cache_path, token_data)
        new_refresh_token = token_data.get("refresh_token")
        if new_refresh_token and new_refresh_token != config.get("user_refresh_token"):
            config["user_refresh_token"] = new_refresh_token
            save_config(config_path, config)
            print("Updated user_refresh_token in config.")
        elif not new_refresh_token:
            print(f"Cached user access token in {user_token_cache_path}.")
    return tokens


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
    parser.add_argument(
        "--sent-log",
        default=str(DEFAULT_SENT_LOG),
        help="Path to store API-sent message IDs for later recall",
    )
    parser.add_argument(
        "--recall-message",
        action="append",
        default=[],
        help="Recall a specific message_id. Use with --send-as app or --send-as user.",
    )
    parser.add_argument(
        "--recall-last",
        nargs="?",
        const=1,
        type=int,
        help="Recall the last N unrecalled API-sent messages for --send-as app/user.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    sent_log_path = Path(args.sent_log)

    if args.recall_message or args.recall_last:
        if args.send_as not in {"app", "user"}:
            raise RuntimeError("Recall needs an API sender. Run with --send-as user or --send-as app.")
        tokens = get_tokens(config, config_path, {args.send_as})
        recall_records = [{"message_id": message_id, "name": message_id} for message_id in args.recall_message]
        if args.recall_last:
            if args.recall_last < 1:
                raise RuntimeError("--recall-last must be at least 1.")
            recall_records.extend(select_recent_messages_for_recall(sent_log_path, args.send_as, args.recall_last))
        if not recall_records:
            raise RuntimeError(f"No unrecalled {args.send_as} messages found in {sent_log_path}.")
        for record in recall_records:
            message_id = record["message_id"]
            recall_message(message_id, tokens[args.send_as], config)
            append_sent_log(
                sent_log_path,
                {
                    "action": "recall",
                    "send_as": args.send_as,
                    "message_id": message_id,
                    "name": record.get("name", message_id),
                },
            )
            print(f"Recalled: {record.get('name', message_id)} ({message_id})")
        print("Done.")
        return

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

    # Uploading an image to Lark always needs the app token, even when the
    # final delivery is through an incoming webhook.
    required_modes = {"app"}
    required_modes.update(
        message_send_as(message, default_send_as)
        for message in messages
        if message_send_as(message, default_send_as) == "user"
    )
    tokens = get_tokens(config, config_path, required_modes)

    image_key_cache = {}
    for message in messages:
        image_path = Path(message["image"])
        send_as = message_send_as(message, default_send_as)
        if image_path not in image_key_cache:
            image_key_cache[image_path] = upload_image(image_path, tokens["app"], config)
        if send_as == "webhook":
            send_image_with_retry(message["webhook"], image_key_cache[image_path], message.get("secret", ""))
        else:
            data = send_image_to_receiver_with_retry(
                message["receive_id_type"],
                message["receive_id"],
                image_key_cache[image_path],
                tokens[send_as],
                config,
            )
            message_id = get_message_id(data)
            if message_id:
                append_sent_log(
                    sent_log_path,
                    {
                        "action": "send",
                        "send_as": send_as,
                        "message_id": message_id,
                        "name": message.get("name", image_path.name),
                        "image": str(image_path),
                        "receive_id_type": message["receive_id_type"],
                        "receive_id": message["receive_id"],
                    },
                )
            else:
                print(f"Warning: sent {message.get('name', image_path.name)} but response had no message_id.")
        print(f"Sent: {message.get('name', image_path.name)}")
        time.sleep(args.delay)

    print("Done.")


if __name__ == "__main__":
    main()
