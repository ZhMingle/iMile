import argparse
import subprocess
import sys


def build_steps(send_as, allow_old_source=False):
    update_command = [sys.executable, "update_report_data.py"]
    if allow_old_source:
        update_command.append("--allow-old-source")

    send_command = [sys.executable, "send_lark_images.py", "--send"]
    if send_as != "all":
        send_command.extend(["--send-as", send_as])

    return [
        ("Update workbook", update_command),
        ("Build message pack", [sys.executable, "build_message_pack.py"]),
        ("Send Lark images", send_command),
    ]


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
    args = parser.parse_args()

    for label, command in build_steps(args.send_as, args.allow_old_source):
        print(f"\n== {label} ==", flush=True)
        subprocess.run(command, check=True)

    print("\nDone: report updated, images generated, and Lark messages sent.", flush=True)


if __name__ == "__main__":
    main()
