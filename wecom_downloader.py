import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import zipfile


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "wecom_download_config.json"
EXAMPLE_CONFIG_PATH = APP_DIR / "wecom_download_config.example.json"
MANIFEST_NAME = ".downloaded_files.json"


def _load_config(config_path=CONFIG_PATH):
    config_path = Path(config_path)
    if not config_path.exists():
        if EXAMPLE_CONFIG_PATH.exists():
            shutil.copy2(EXAMPLE_CONFIG_PATH, config_path)
        raise RuntimeError(
            "已创建 wecom_download_config.json。请先填写企业微信 TEMU 会话名称和下载目录，再重新开始。"
        )
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    chat_name = str(config.get("chat_name", "")).strip()
    if not chat_name or chat_name == "TEMU 文件群":
        raise RuntimeError("请在 wecom_download_config.json 中填写真实的 TEMU 会话名称。")
    download_dir = Path(os.path.expandvars(str(config.get("download_dir", "")))).expanduser()
    if not download_dir.is_dir():
        raise RuntimeError(f"企业微信下载目录不存在：{download_dir}")
    archive_dir = Path(os.path.expandvars(str(config.get("archive_dir", "input/TEMU")))).expanduser()
    if not archive_dir.is_absolute():
        archive_dir = APP_DIR / archive_dir
    extensions = {
        str(extension).lower() if str(extension).startswith(".") else "." + str(extension).lower()
        for extension in config.get("allowed_extensions", [".xls", ".xlsx", ".csv", ".zip"])
    }
    return config, chat_name, download_dir, archive_dir, extensions


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(archive_root):
    path = archive_root / MANIFEST_NAME
    if not path.exists():
        return path, {}
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path, {}


def _unique_destination(folder, name):
    destination = folder / name
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    counter = 2
    while True:
        candidate = folder / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _safe_extract_zip(zip_path, destination):
    extracted = []
    destination = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            target = (destination / Path(member.filename).name).resolve()
            if target.parent != destination:
                continue
            if target.suffix.lower() not in {".xls", ".xlsx", ".csv"}:
                continue
            target = _unique_destination(destination, target.name)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    return extracted


def archive_downloads(files, archive_root):
    archive_root.mkdir(parents=True, exist_ok=True)
    day_folder = archive_root / time.strftime("%Y-%m-%d")
    day_folder.mkdir(parents=True, exist_ok=True)
    manifest_path, manifest = _load_manifest(archive_root)
    archived = []
    duplicates = []

    for source in files:
        source = Path(source)
        digest = _sha256(source)
        if digest in manifest:
            duplicates.append(source)
            continue
        destination = _unique_destination(day_folder, source.name)
        shutil.copy2(source, destination)
        manifest[digest] = {
            "source": str(source),
            "archived": str(destination.relative_to(APP_DIR)) if destination.is_relative_to(APP_DIR) else str(destination),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        archived.append(destination)
        if destination.suffix.lower() == ".zip":
            archived.extend(_safe_extract_zip(destination, day_folder))

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return archived, duplicates


def _download_snapshot(folder, extensions):
    result = {}
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() in extensions:
            try:
                result[path.resolve()] = (path.stat().st_size, path.stat().st_mtime_ns)
            except OSError:
                pass
    return result


def _wait_for_downloads(folder, extensions, before, timeout):
    deadline = time.monotonic() + timeout
    stable = {}
    completed = []
    while time.monotonic() < deadline:
        current = _download_snapshot(folder, extensions)
        candidates = [path for path, state in current.items() if before.get(path) != state]
        for path in candidates:
            size = current[path][0]
            previous_size, count = stable.get(path, (-1, 0))
            stable[path] = (size, count + 1 if size == previous_size else 0)
            if stable[path][1] >= 2 and size > 0 and path not in completed:
                completed.append(path)
        if completed and all(stable.get(path, (0, 0))[1] >= 2 for path in candidates):
            return completed
        time.sleep(1)
    return completed


def _find_wecom_window():
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("缺少 Windows 自动化组件 pywinauto，请重新构建或安装 requirements.txt。") from exc

    candidates = []
    for window in Desktop(backend="uia").windows():
        try:
            title = window.window_text().strip()
            if window.is_visible() and re.search(r"企业微信|WeCom", title, re.IGNORECASE):
                candidates.append(window)
        except Exception:
            continue
    if not candidates:
        raise RuntimeError("没有找到企业微信窗口。请先登录并打开企业微信桌面端。")
    return max(candidates, key=lambda window: window.rectangle().width() * window.rectangle().height())


def _open_chat(window, chat_name):
    from pywinauto.keyboard import send_keys
    import win32clipboard

    window.restore()
    window.set_focus()
    send_keys("^f")
    time.sleep(0.7)
    send_keys("^a{BACKSPACE}")
    previous_clipboard = None
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                previous_clipboard = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(chat_name, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        send_keys("^v")
    finally:
        if previous_clipboard is not None:
            time.sleep(0.2)
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(previous_clipboard, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
    time.sleep(1.5)
    send_keys("{ENTER}")
    time.sleep(1.5)


def _visible_attachment_names(window, extensions):
    names = []
    for control in window.descendants():
        try:
            text = control.window_text().strip()
            if text and Path(text).suffix.lower() in extensions and text not in names:
                names.append(text)
        except Exception:
            continue
    return names


def _click_attachment(window, name):
    matches = []
    for control in window.descendants():
        try:
            if control.window_text().strip() == name and control.is_visible():
                matches.append(control)
        except Exception:
            continue
    if not matches:
        return False
    control = matches[-1]
    try:
        control.scroll_into_view()
    except Exception:
        pass
    control.double_click_input()
    return True


def download_temu_files(config_path=CONFIG_PATH):
    if sys.platform != "win32":
        raise RuntimeError("企业微信桌面自动下载只能在 Windows 电脑上运行。")
    config, chat_name, download_dir, archive_root, extensions = _load_config(config_path)
    before = _download_snapshot(download_dir, extensions)
    window = _find_wecom_window()
    print(f"已找到企业微信，正在打开会话：{chat_name}")
    _open_chat(window, chat_name)

    names = _visible_attachment_names(window, extensions)
    if not names:
        raise RuntimeError("当前会话画面中没有找到可下载的 Excel、CSV 或 ZIP 附件。请先滚动到附件附近。")
    print(f"当前画面发现 {len(names)} 个附件：{', '.join(names)}")
    clicked = 0
    for name in names:
        if _click_attachment(window, name):
            clicked += 1
            print(f"已触发下载：{name}")
            time.sleep(0.8)

    timeout = max(10, int(config.get("download_timeout_seconds", 90)))
    downloaded = _wait_for_downloads(download_dir, extensions, before, timeout)
    if not downloaded:
        raise RuntimeError(
            "已点击附件，但没有在下载目录发现新文件。请检查企业微信下载目录配置，或确认附件是否需要额外点击“下载”。"
        )
    archived, duplicates = archive_downloads(downloaded, archive_root)
    tracking_files = [path for path in archived if path.suffix.lower() in {".xls", ".xlsx", ".csv"}]
    tracking_message = ""
    if config.get("auto_extract_tracking", True) and tracking_files:
        from getTrakingNum import main as extract_tracking

        output = extract_tracking(tracking_files)
        tracking_message = f"；已生成 {output.name}"
    return (
        f"TEMU 收件完成：点击 {clicked} 个附件，新增归档 {len(archived)} 个文件，"
        f"跳过 {len(duplicates)} 个重复文件{tracking_message}。"
    )


if __name__ == "__main__":
    print(download_temu_files())
