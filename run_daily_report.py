import argparse
import subprocess
import sys


def build_steps(send_as):
    send_command = [sys.executable, "send_lark_images.py", "--send"]
    if send_as != "all":
        send_command.extend(["--send-as", send_as])

    return [
        ("Update workbook", [sys.executable, "update_report_data.py"]),
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
    args = parser.parse_args()

    for label, command in build_steps(args.send_as):
        print(f"\n== {label} ==", flush=True)
        subprocess.run(command, check=True)

    print("\nDone: report updated, images generated, and Lark messages sent.", flush=True)


if __name__ == "__main__":
    main()
