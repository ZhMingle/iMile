import contextlib
import ctypes
from ctypes import wintypes
from pathlib import Path
import queue
import sys
import threading
import traceback

from app_workflows import run_report, run_tracking


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
comdlg32 = ctypes.windll.comdlg32

WM_DESTROY = 0x0002
WM_SIZE = 0x0005
WM_COMMAND = 0x0111
WM_SETFONT = 0x0030
WM_APP_UPDATE = 0x8001
SW_SHOW = 5
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_TABSTOP = 0x00010000
WS_BORDER = 0x00800000
WS_VSCROLL = 0x00200000
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
ES_READONLY = 0x0800
BS_PUSHBUTTON = 0x00000000
SS_LEFT = 0x00000000
EM_SETSEL = 0x00B1
EM_REPLACESEL = 0x00C2
OFN_EXPLORER = 0x00080000
OFN_FILEMUSTEXIST = 0x00001000
OFN_PATHMUSTEXIST = 0x00000800
OFN_ALLOWMULTISELECT = 0x00000200
COLOR_WINDOW = 5
IDC_ARROW = 32512

ID_TRACKING = 1001
ID_REPORT = 1002


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


class QueueWriter:
    def __init__(self, app):
        self.app = app

    def write(self, text):
        if text:
            self.app.events.put(("log", text))
            user32.PostMessageW(self.app.hwnd, WM_APP_UPDATE, 0, 0)
        return len(text)

    def flush(self):
        return None


class IMileWin32App:
    def __init__(self):
        self.hwnd = None
        self.tracking_button = None
        self.report_button = None
        self.status = None
        self.log = None
        self.busy = False
        self.events = queue.Queue()
        self.wndproc = WNDPROC(self._wndproc)
        self.font = gdi32.CreateFontW(
            -18, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Microsoft YaHei UI"
        )
        self.title_font = gdi32.CreateFontW(
            -30, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 5, 0, "Microsoft YaHei UI"
        )

    def run(self):
        instance = kernel32.GetModuleHandleW(None)
        class_name = "IMileReportAssistantWindow"
        wc = WNDCLASSW()
        wc.lpfnWndProc = self.wndproc
        wc.hInstance = instance
        wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
        wc.hbrBackground = ctypes.cast(COLOR_WINDOW + 1, wintypes.HBRUSH)
        wc.lpszClassName = class_name
        if not user32.RegisterClassW(ctypes.byref(wc)) and kernel32.GetLastError() != 1410:
            raise ctypes.WinError()

        self.hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "iMile 报表助手",
            WS_OVERLAPPEDWINDOW,
            100,
            80,
            920,
            650,
            None,
            None,
            instance,
            None,
        )
        if not self.hwnd:
            raise ctypes.WinError()
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def _create_control(self, cls, text, style, x, y, width, height, control_id=0):
        handle = user32.CreateWindowExW(
            0,
            cls,
            text,
            WS_CHILD | WS_VISIBLE | style,
            x,
            y,
            width,
            height,
            self.hwnd,
            control_id,
            kernel32.GetModuleHandleW(None),
            None,
        )
        user32.SendMessageW(handle, WM_SETFONT, self.font, True)
        return handle

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == 1:  # WM_CREATE
            title = self._create_control("STATIC", "iMile 报表助手", SS_LEFT, 34, 22, 500, 44)
            user32.SendMessageW(title, WM_SETFONT, self.title_font, True)
            self._create_control(
                "STATIC",
                "提取运单号 · 生成并通过 Lark 机器人发送报表",
                SS_LEFT,
                36,
                68,
                650,
                28,
            )
            self.tracking_button = self._create_control(
                "BUTTON",
                "Get Tracking Num  |  选择文件并提取",
                BS_PUSHBUTTON | WS_TABSTOP,
                36,
                120,
                390,
                62,
                ID_TRACKING,
            )
            self.report_button = self._create_control(
                "BUTTON",
                "发送报表  |  生成并由机器人发送",
                BS_PUSHBUTTON | WS_TABSTOP,
                458,
                120,
                390,
                62,
                ID_REPORT,
            )
            self.status = self._create_control(
                "STATIC",
                "就绪 · 机器人模式，不使用个人 Lark 身份",
                SS_LEFT,
                36,
                205,
                812,
                28,
            )
            self._create_control("STATIC", "运行记录", SS_LEFT, 36, 240, 120, 24)
            self.log = self._create_control(
                "EDIT",
                "",
                WS_BORDER | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY,
                36,
                270,
                812,
                305,
            )
            return 0
        if msg == WM_COMMAND:
            command_id = int(wparam) & 0xFFFF
            if command_id == ID_TRACKING and not self.busy:
                files = self._file_dialog(True, "选择需要提取运单号的 Excel 文件", "Excel 文件\0*.xls;*.xlsx\0所有文件\0*.*\0")
                if files:
                    self._start("正在提取运单号…", run_tracking, files)
            elif command_id == ID_REPORT and not self.busy:
                files = self._file_dialog(False, "选择中心运单查询 Excel", "Excel 文件\0*.xlsx\0所有文件\0*.*\0")
                if files:
                    self._start("正在生成并发送报表…", run_report, files[0])
            return 0
        if msg == WM_APP_UPDATE:
            self._drain_events()
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _file_dialog(self, multi, title, file_filter):
        buffer = ctypes.create_unicode_buffer(65536)
        dialog = OPENFILENAMEW()
        dialog.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        dialog.hwndOwner = self.hwnd
        dialog.lpstrFilter = file_filter
        dialog.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
        dialog.nMaxFile = len(buffer)
        dialog.lpstrTitle = title
        dialog.Flags = OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST
        if multi:
            dialog.Flags |= OFN_ALLOWMULTISELECT
        if not comdlg32.GetOpenFileNameW(ctypes.byref(dialog)):
            return []
        parts = "".join(buffer).split("\0")
        parts = [part for part in parts if part]
        if len(parts) == 1:
            return [parts[0]]
        folder = Path(parts[0])
        return [str(folder / name) for name in parts[1:]]

    def _start(self, status, function, *args):
        self.busy = True
        user32.EnableWindow(self.tracking_button, False)
        user32.EnableWindow(self.report_button, False)
        user32.SetWindowTextW(self.status, status)
        self._append_log("\r\n" + "=" * 64 + "\r\n")
        threading.Thread(target=self._worker, args=(function, args), daemon=True).start()

    def _worker(self, function, args):
        writer = QueueWriter(self)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                result = function(*args)
            self.events.put(("success", result or "操作完成。"))
        except BaseException as exc:
            self.events.put(("log", traceback.format_exc()))
            self.events.put(("error", str(exc) or exc.__class__.__name__))
        user32.PostMessageW(self.hwnd, WM_APP_UPDATE, 0, 0)

    def _drain_events(self):
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                return
            if kind == "log":
                self._append_log(payload.replace("\n", "\r\n"))
            elif kind in {"success", "error"}:
                self.busy = False
                user32.EnableWindow(self.tracking_button, True)
                user32.EnableWindow(self.report_button, True)
                prefix = "完成 · " if kind == "success" else "失败 · "
                user32.SetWindowTextW(self.status, prefix + payload)
                icon = 0x40 if kind == "success" else 0x10
                user32.MessageBoxW(self.hwnd, payload, "完成" if kind == "success" else "操作失败", icon)

    def _append_log(self, text):
        length = user32.GetWindowTextLengthW(self.log)
        user32.SendMessageW(self.log, EM_SETSEL, length, length)
        user32.SendMessageW(self.log, EM_REPLACESEL, False, text)


if __name__ == "__main__":
    IMileWin32App().run()

