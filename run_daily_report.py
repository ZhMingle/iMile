import argparse
from pathlib import Path
import subprocess
import sys


REPORT_PATH_FILE = Path("output/.last_report_path")


def build_steps(
    send_as,
    allow_old_source=False,
    report_file="当日数据统计.xlsx",
    send=True,
):
    update_command = [
        sys.executable,
        "update_report_data.py",
        "--result-path-file",
        str(REPORT_PATH_FILE),
    ]
    if allow_old_source:
        update_command.append("--allow-old-source")

    send_command = [sys.executable, "send_lark_images.py", "--send"]
    if send_as != "all":
        send_command.extend(["--send-as", send_as])

    steps = [
        ("Update workbook", update_command),
        (
            "Build message pack",
            [sys.executable, "build_message_pack.py", "--report-file", str(report_file)],
        ),
    ]
    if send:
        steps.append(("Send Lark images", send_command))
    return steps


def main():
    parser = argparse.ArgumentParser(description="Run the daily report workflow.")
    parser.add_argument(
        "--send-as",
        choices=["all", "webhook", "app", "user"],
        default="webhook",
        help="Only send messages that resolve to this delivery mode",
    )
    parser.add_argument(
        "--allow-old-source",
        action="store_true",
        help="Allow a center waybill query file whose modified date is not today",
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Update the workbook and generate images without sending them",
    )
    args = parser.parse_args()

    REPORT_PATH_FILE.unlink(missing_ok=True)
    update_label, update_command = build_steps(
        args.send_as,
        args.allow_old_source,
        send=not args.no_send,
    )[0]
    print(f"\n== {update_label} ==", flush=True)
    subprocess.run(update_command, check=True)

    if not REPORT_PATH_FILE.is_file():
        raise RuntimeError("Workbook update did not report its output path.")
    report_file = Path(REPORT_PATH_FILE.read_text(encoding="utf-8").strip())
    if not report_file.is_file():
        raise FileNotFoundError(f"Generated report workbook not found: {report_file}")

    for label, command in build_steps(
        args.send_as,
        args.allow_old_source,
        report_file,
        send=not args.no_send,
    )[1:]:
        print(f"\n== {label} ==", flush=True)
        subprocess.run(command, check=True)

    if args.no_send:
        print("\nDone: report updated and images generated; nothing was sent.", flush=True)
    else:
        print("\nDone: report updated, images generated, and Lark messages sent.", flush=True)


if __name__ == "__main__":
    main()
