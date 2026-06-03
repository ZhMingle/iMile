import subprocess
import sys


STEPS = [
    ("Update workbook", [sys.executable, "update_report_data.py"]),
    ("Build message pack", [sys.executable, "build_message_pack.py"]),
    ("Send Lark images", [sys.executable, "send_lark_images.py", "--send"]),
]


def main():
    for label, command in STEPS:
        print(f"\n== {label} ==", flush=True)
        subprocess.run(command, check=True)

    print("\nDone: report updated, images generated, and Lark messages sent.", flush=True)


if __name__ == "__main__":
    main()
