import contextlib
import ctypes
from ctypes import wintypes
from pathlib import Path
import queue
import sys
import threading
import traceback

from app_workflows import (
    center_waybill_file_freshness_warning,
    configured_text_destinations,
    open_wecom_config,
    route_group_destination_indexes,
    run_auto_dispatch_manifest,
    run_dc_export,
    run_report,
    run_text_message,
    run_tracking,
    run_wecom_download,
)


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
comdlg32 = ctypes.windll.comdlg32

WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_SIZE = 0x0005
WM_COMMAND = 0x0111
WM_DRAWITEM = 0x002B
WM_CTLCOLOREDIT = 0x0133
WM_CTLCOLORLISTBOX = 0x0134
WM_CTLCOLORSTATIC = 0x0138
WM_SETFONT = 0x0030
WM_APP_UPDATE = 0x8001
SW_SHOW = 5
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_CLIPCHILDREN = 0x02000000
WS_TABSTOP = 0x00010000
WS_BORDER = 0x00800000
WS_VSCROLL = 0x00200000
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
ES_AUTOHSCROLL = 0x0080
ES_WANTRETURN = 0x1000
ES_READONLY = 0x0800
BS_PUSHBUTTON = 0x00000000
BS_OWNERDRAW = 0x0000000B
LBS_MULTIPLESEL = 0x0008
LBS_NOINTEGRALHEIGHT = 0x0100
SS_LEFT = 0x00000000
EM_SETSEL = 0x00B1
EM_REPLACESEL = 0x00C2
EM_SETCUEBANNER = 0x1501
LB_ADDSTRING = 0x0180
LB_RESETCONTENT = 0x0184
LB_SETSEL = 0x0185
LB_GETSELCOUNT = 0x0190
LB_GETSELITEMS = 0x0191
EN_CHANGE = 0x0300
LBN_SELCHANGE = 1
OFN_EXPLORER = 0x00080000
OFN_FILEMUSTEXIST = 0x00001000
OFN_PATHMUSTEXIST = 0x00000800
OFN_ALLOWMULTISELECT = 0x00000200
COLOR_WINDOW = 5
IDC_ARROW = 32512
ODT_BUTTON = 4
ODS_SELECTED = 0x0001
ODS_DISABLED = 0x0004
PS_SOLID = 0
TRANSPARENT = 1
OPAQUE = 2
DT_CENTER = 0x00000001
DT_VCENTER = 0x00000004
DT_SINGLELINE = 0x00000020
DT_END_ELLIPSIS = 0x00008000


def rgb(red, green, blue):
    return red | (green << 8) | (blue << 16)


COLOR_APP_BACKGROUND = rgb(246, 248, 252)
COLOR_CARD = rgb(255, 255, 255)
COLOR_CARD_BORDER = rgb(226, 232, 240)
COLOR_HEADER = rgb(15, 23, 42)
COLOR_HEADER_MUTED = rgb(191, 219, 254)
COLOR_TEXT = rgb(30, 41, 59)
COLOR_TEXT_MUTED = rgb(100, 116, 139)
COLOR_PRIMARY = rgb(37, 99, 235)
COLOR_PRIMARY_HOVER = rgb(29, 78, 216)
COLOR_SECONDARY = rgb(239, 246, 255)
COLOR_SECONDARY_HOVER = rgb(219, 234, 254)
COLOR_SECONDARY_TEXT = rgb(30, 64, 175)
COLOR_GHOST = rgb(255, 255, 255)
COLOR_GHOST_HOVER = rgb(248, 250, 252)

ID_TRACKING = 1001
ID_REPORT = 1002
ID_WECOM_DOWNLOAD = 1003
ID_WECOM_SETTINGS = 1004
ID_DC_EXPORT = 1005
ID_DISPATCH_ROUTE = 1006
ID_DISPATCH_DRIVER = 1007
ID_AUTO_DISPATCH = 1008
ID_TEXT_MESSAGE = 1009
ID_TEXT_TARGETS = 1010
ID_SEND_TEXT = 1011
ID_TEXT_TARGET_SEARCH = 1012
ID_AUTO_SELECT_ROUTE_GROUPS = 1013


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


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class DRAWITEMSTRUCT(ctypes.Structure):
    _fields_ = [
        ("CtlType", wintypes.UINT),
        ("CtlID", wintypes.UINT),
        ("itemID", wintypes.UINT),
        ("itemAction", wintypes.UINT),
        ("itemState", wintypes.UINT),
        ("hwndItem", wintypes.HWND),
        ("hDC", wintypes.HDC),
        ("rcItem", wintypes.RECT),
        ("itemData", ctypes.c_size_t),
    ]


def _configure_win32_api():
    lresult = ctypes.c_ssize_t
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.WORD
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HANDLE,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = lresult
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = lresult
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.UpdateWindow.restype = wintypes.BOOL
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.BeginPaint.restype = wintypes.HDC
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.EndPaint.restype = wintypes.BOOL
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    user32.FillRect.restype = ctypes.c_int
    user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
    user32.InvalidateRect.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    user32.DrawTextW.restype = ctypes.c_int
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = lresult
    user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.SetWindowTextW.restype = wintypes.BOOL
    user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.MoveWindow.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.BOOL,
    ]
    user32.MoveWindow.restype = wintypes.BOOL
    user32.EnableWindow.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None

    gdi32.CreateFontW.restype = wintypes.HANDLE
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
    gdi32.CreatePen.restype = wintypes.HPEN
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.RoundRect.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    gdi32.RoundRect.restype = wintypes.BOOL
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.SetTextColor.restype = wintypes.COLORREF
    gdi32.SetBkColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.SetBkColor.restype = wintypes.COLORREF
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetBkMode.restype = ctypes.c_int
    comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(OPENFILENAMEW)]
    comdlg32.GetOpenFileNameW.restype = wintypes.BOOL


_configure_win32_api()


class QueueWriter:
    def __init__(self, app):
        self.app = app

    def write(self, text):
        if text:
            text = str(text).replace("\x1b[32m", "").replace("\x1b[0m", "")
            self.app.events.put(("log", text))
            user32.PostMessageW(self.app.hwnd, WM_APP_UPDATE, 0, 0)
        return len(text)

    def flush(self):
        return None


class IMileWin32App:
    def __init__(self):
        self.hwnd = None
        self.title = None
        self.subtitle = None
        self.tracking_button = None
        self.report_button = None
        self.text_label = None
        self.text_message_edit = None
        self.text_targets_label = None
        self.text_target_search_edit = None
        self.text_targets_list = None
        self.text_selection_status = None
        self.text_auto_select_button = None
        self.text_send_button = None
        self.text_destinations = []
        self.text_visible_destination_indexes = []
        self.selected_text_destination_indexes = set()
        self.text_destination_error = None
        self.wecom_button = None
        self.wecom_settings_button = None
        self.dc_export_button = None
        self.dispatch_label = None
        self.dispatch_route_edit = None
        self.dispatch_driver_edit = None
        self.dispatch_button = None
        self.status = None
        self.log_label = None
        self.log = None
        self.busy = False
        self.events = queue.Queue()
        self.button_variants = {}
        self.cue_buffers = []
        self.theme_rects = {}
        self.app_background_brush = gdi32.CreateSolidBrush(COLOR_APP_BACKGROUND)
        self.card_brush = gdi32.CreateSolidBrush(COLOR_CARD)
        self.header_brush = gdi32.CreateSolidBrush(COLOR_HEADER)
        self.wndproc = WNDPROC(self._wndproc)
        self.font = gdi32.CreateFontW(
            -16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Microsoft YaHei UI"
        )
        self.button_font = gdi32.CreateFontW(
            -16, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, "Microsoft YaHei UI"
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
        wc.hbrBackground = None
        wc.lpszClassName = class_name
        if not user32.RegisterClassW(ctypes.byref(wc)) and kernel32.GetLastError() != 1410:
            raise ctypes.WinError()

        self.hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "iMile 报表助手",
            WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
            100,
            20,
            1080,
            1020,
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

    def _create_control(self, cls, text, style, x, y, width, height, control_id=0, variant="secondary"):
        is_button = cls == "BUTTON"
        if is_button:
            style = (style & ~0x000F) | BS_OWNERDRAW
        ex_style = 0x00000200 if cls in {"EDIT", "LISTBOX"} else 0
        if cls in {"EDIT", "LISTBOX"}:
            style &= ~WS_BORDER
        handle = user32.CreateWindowExW(
            ex_style,
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
        user32.SendMessageW(handle, WM_SETFONT, self.button_font if is_button else self.font, True)
        if is_button:
            self.button_variants[int(handle)] = variant
        return handle

    def _set_cue_banner(self, handle, text):
        buffer = ctypes.create_unicode_buffer(text)
        self.cue_buffers.append(buffer)
        user32.SendMessageW(handle, EM_SETCUEBANNER, True, ctypes.addressof(buffer))

    def _get_control_text(self, handle):
        length = user32.GetWindowTextLengthW(handle)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, len(buffer))
        return buffer.value.strip()

    def _selected_text_destination_indexes(self):
        self._sync_selected_text_destinations()
        return sorted(self.selected_text_destination_indexes)

    def _sync_selected_text_destinations(self):
        if not self.text_targets_list:
            return
        count = user32.SendMessageW(self.text_targets_list, LB_GETSELCOUNT, 0, 0)
        selected_rows = []
        if count > 0:
            selected = (ctypes.c_int * count)()
            user32.SendMessageW(
                self.text_targets_list,
                LB_GETSELITEMS,
                count,
                ctypes.addressof(selected),
            )
            selected_rows = list(selected)

        selected_indexes = {
            self.text_visible_destination_indexes[row]
            for row in selected_rows
            if row < len(self.text_visible_destination_indexes)
        }
        self.selected_text_destination_indexes.difference_update(self.text_visible_destination_indexes)
        self.selected_text_destination_indexes.update(selected_indexes)
        self._update_text_selection_status()

    def _update_text_selection_status(self):
        if self.text_selection_status:
            user32.SetWindowTextW(
                self.text_selection_status,
                f"已选 {len(self.selected_text_destination_indexes)} 个群",
            )

    def _refresh_text_destination_list(self, sync_selection=True):
        if sync_selection:
            self._sync_selected_text_destinations()
        if not self.text_targets_list:
            return

        query = self._get_control_text(self.text_target_search_edit).casefold()
        user32.SendMessageW(self.text_targets_list, LB_RESETCONTENT, 0, 0)
        self.text_visible_destination_indexes = []
        for index, destination in enumerate(self.text_destinations):
            name = str(destination.get("name", "未命名群"))
            if query and query not in name.casefold():
                continue
            row = len(self.text_visible_destination_indexes)
            self.text_visible_destination_indexes.append(index)
            label = ctypes.create_unicode_buffer(name)
            user32.SendMessageW(self.text_targets_list, LB_ADDSTRING, 0, ctypes.addressof(label))
            if index in self.selected_text_destination_indexes:
                user32.SendMessageW(self.text_targets_list, LB_SETSEL, True, row)
        self._update_text_selection_status()

    def _auto_select_route_groups(self):
        text = self._get_control_text(self.text_message_edit)
        requested_codes, matched_indexes = route_group_destination_indexes(
            self.text_destinations,
            text,
        )
        if not requested_codes:
            user32.MessageBoxW(
                self.hwnd,
                "请先在文字内容中填写线路名，例如：HMT - TRG。",
                "未识别到线路名",
                0x30,
            )
            return
        if not matched_indexes:
            user32.MessageBoxW(
                self.hwnd,
                f"已识别线路：{'、'.join(requested_codes)}，但没有找到对应群。",
                "未找到对应群",
                0x30,
            )
            return

        self.selected_text_destination_indexes = set(matched_indexes)
        self._refresh_text_destination_list(sync_selection=False)
        names = [self.text_destinations[index].get("name", "未命名群") for index in matched_indexes]
        user32.MessageBoxW(
            self.hwnd,
            f"已按线路 {'、'.join(requested_codes)} 自动选中：\n" + "\n".join(names),
            "已自动选择群",
            0x40,
        )

    @staticmethod
    def _rounded_rect(hdc, bounds, fill_color, border_color=COLOR_CARD_BORDER, radius=14):
        left, top, right, bottom = bounds
        brush = gdi32.CreateSolidBrush(fill_color)
        pen = gdi32.CreatePen(PS_SOLID, 1, border_color)
        old_brush = gdi32.SelectObject(hdc, brush)
        old_pen = gdi32.SelectObject(hdc, pen)
        gdi32.RoundRect(hdc, left, top, right, bottom, radius, radius)
        gdi32.SelectObject(hdc, old_brush)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.DeleteObject(brush)
        gdi32.DeleteObject(pen)

    def _draw_theme(self, hdc):
        client = wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(client))
        user32.FillRect(hdc, ctypes.byref(client), self.app_background_brush)
        header = wintypes.RECT(client.left, client.top, client.right, min(client.bottom, 108))
        user32.FillRect(hdc, ctypes.byref(header), self.header_brush)
        for bounds in self.theme_rects.values():
            self._rounded_rect(hdc, bounds, COLOR_CARD)

    def _draw_button(self, draw_item):
        variant = self.button_variants.get(int(draw_item.hwndItem), "secondary")
        disabled = bool(draw_item.itemState & ODS_DISABLED)
        pressed = bool(draw_item.itemState & ODS_SELECTED)
        if disabled:
            fill_color = rgb(226, 232, 240)
            border_color = fill_color
            text_color = rgb(148, 163, 184)
        elif variant == "primary":
            fill_color = COLOR_PRIMARY_HOVER if pressed else COLOR_PRIMARY
            border_color = fill_color
            text_color = COLOR_CARD
        elif variant == "ghost":
            fill_color = COLOR_GHOST_HOVER if pressed else COLOR_GHOST
            border_color = COLOR_CARD_BORDER
            text_color = COLOR_TEXT_MUTED
        else:
            fill_color = COLOR_SECONDARY_HOVER if pressed else COLOR_SECONDARY
            border_color = rgb(191, 219, 254)
            text_color = COLOR_SECONDARY_TEXT

        rect = draw_item.rcItem
        offset = 1 if pressed else 0
        self._rounded_rect(
            draw_item.hDC,
            (rect.left, rect.top + offset, rect.right, rect.bottom + offset),
            fill_color,
            border_color,
            radius=12,
        )
        gdi32.SetBkMode(draw_item.hDC, TRANSPARENT)
        gdi32.SetTextColor(draw_item.hDC, text_color)
        text = self._get_control_text(draw_item.hwndItem)
        text_rect = wintypes.RECT(rect.left + 12, rect.top + offset, rect.right - 12, rect.bottom + offset)
        user32.DrawTextW(
            draw_item.hDC,
            text,
            len(text),
            ctypes.byref(text_rect),
            DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS,
        )

    def _control_color(self, message, hdc, control):
        control = int(control)
        if message == WM_CTLCOLORSTATIC:
            header_controls = {int(item) for item in (self.title, self.subtitle) if item}
            muted_controls = {int(item) for item in (self.text_selection_status, self.status) if item}
            if control in header_controls:
                gdi32.SetBkMode(hdc, OPAQUE)
                gdi32.SetBkColor(hdc, COLOR_HEADER)
                gdi32.SetTextColor(hdc, COLOR_CARD if control == int(self.title) else COLOR_HEADER_MUTED)
                return self.header_brush
            gdi32.SetBkMode(hdc, OPAQUE)
            gdi32.SetBkColor(hdc, COLOR_CARD)
            if control in muted_controls:
                gdi32.SetTextColor(hdc, COLOR_TEXT_MUTED)
            else:
                gdi32.SetTextColor(hdc, COLOR_TEXT)
            return self.card_brush

        # EDIT controls repaint changed text without erasing the whole window.
        # An opaque background clears old glyphs when deleting or replacing text.
        gdi32.SetBkMode(hdc, OPAQUE)
        gdi32.SetBkColor(hdc, COLOR_CARD)
        gdi32.SetTextColor(hdc, COLOR_TEXT)
        return self.card_brush

    def _move_control(self, handle, x, y, width, height):
        if handle:
            user32.MoveWindow(
                handle,
                int(x),
                int(y),
                max(1, int(width)),
                max(1, int(height)),
                True,
            )

    def _layout_controls(self, client_width, client_height):
        if not self.log or client_width <= 0 or client_height <= 0:
            return

        content_width = min(1360, max(520, client_width - 64))
        left = max(32, (client_width - content_width) // 2)
        row_gap = 18
        settings_width = 144
        first_width = max(260, content_width - settings_width - row_gap)
        half_gap = 32
        half_width = max(230, (content_width - half_gap) // 2)

        text_label_y = 356
        text_y = 382
        text_height = 230
        target_width = min(640, max(380, int(content_width * 0.42)))
        text_gap = 20
        text_width = max(280, content_width - target_width - text_gap)
        target_x = left + text_width + text_gap
        target_search_height = 30
        target_list_y = text_y + target_search_height + 8
        target_list_height = text_height - target_search_height - 8
        target_status_y = target_list_y + target_list_height + 5
        target_action_y = target_status_y + 26
        target_action_gap = 10
        target_auto_width = (target_width - target_action_gap) // 2
        text_send_x = target_x + target_auto_width + target_action_gap
        text_send_width = target_width - target_auto_width - target_action_gap
        text_send_y = target_action_y

        dispatch_label_y = text_send_y + 66
        manifest_y = dispatch_label_y + 26
        available_height = max(180, client_height - manifest_y - 36)
        target_manifest_height = max(128, int(available_height * 0.42))
        max_manifest_height = max(80, client_height - manifest_y - 219)
        manifest_height = min(target_manifest_height, max_manifest_height)
        manifest_width = max(300, content_width - 222)
        action_x = left + manifest_width + 20
        action_y = manifest_y + max(0, (manifest_height - 52) // 2)

        status_y = manifest_y + manifest_height + 18
        log_label_y = status_y + 35
        log_y = log_label_y + 30
        log_height = max(40, client_height - log_y - 36)

        self.theme_rects = {
            "workflow": (left - 16, 112, left + content_width + 16, 350),
            "message": (left - 16, text_label_y - 14, left + content_width + 16, text_send_y + 62),
            "dispatch": (left - 16, dispatch_label_y - 14, left + content_width + 16, manifest_y + manifest_height + 16),
            "activity": (left - 16, status_y - 12, left + content_width + 16, log_y + log_height + 16),
        }
        user32.InvalidateRect(self.hwnd, None, True)

        self._move_control(self.title, left, 22, content_width, 44)
        self._move_control(self.subtitle, left, 68, content_width, 28)
        self._move_control(self.wecom_button, left, 120, first_width, 62)
        self._move_control(
            self.wecom_settings_button,
            left + first_width + row_gap,
            120,
            settings_width,
            62,
        )
        self._move_control(self.tracking_button, left, 200, half_width, 62)
        self._move_control(
            self.dc_export_button,
            left + half_width + half_gap,
            200,
            content_width - half_width - half_gap,
            62,
        )
        self._move_control(self.report_button, left, 280, content_width, 62)
        self._move_control(self.text_label, left, text_label_y, text_width, 24)
        self._move_control(self.text_targets_label, target_x, text_label_y, target_width, 24)
        self._move_control(self.text_message_edit, left, text_y, text_width, text_height)
        self._move_control(self.text_target_search_edit, target_x, text_y, target_width, target_search_height)
        self._move_control(self.text_targets_list, target_x, target_list_y, target_width, target_list_height)
        self._move_control(self.text_selection_status, target_x, target_status_y, target_width, 20)
        self._move_control(
            self.text_auto_select_button,
            target_x,
            target_action_y,
            target_auto_width,
            48,
        )
        self._move_control(
            self.text_send_button,
            text_send_x,
            text_send_y,
            text_send_width,
            48,
        )
        self._move_control(self.dispatch_label, left, dispatch_label_y, content_width, 24)
        self._move_control(
            self.dispatch_route_edit,
            left,
            manifest_y,
            manifest_width,
            manifest_height,
        )
        self._move_control(self.dispatch_button, action_x, action_y, 202, 52)
        self._move_control(self.status, left, status_y, content_width, 28)
        self._move_control(self.log_label, left, log_label_y, 120, 24)
        self._move_control(self.log, left, log_y, content_width, log_height)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_PAINT:
            paint = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(paint))
            try:
                self._draw_theme(hdc)
            finally:
                user32.EndPaint(hwnd, ctypes.byref(paint))
            return 0
        if msg == WM_DRAWITEM:
            draw_item = DRAWITEMSTRUCT.from_address(int(lparam))
            if draw_item.CtlType == ODT_BUTTON and int(draw_item.hwndItem) in self.button_variants:
                self._draw_button(draw_item)
                return 1
        if msg in {WM_CTLCOLORSTATIC, WM_CTLCOLOREDIT, WM_CTLCOLORLISTBOX}:
            return self._control_color(msg, wparam, lparam)
        if msg == 1:  # WM_CREATE
            self.hwnd = hwnd
            self.title = self._create_control("STATIC", "iMile 报表助手", SS_LEFT, 34, 22, 500, 44)
            user32.SendMessageW(self.title, WM_SETFONT, self.title_font, True)
            self.subtitle = self._create_control(
                "STATIC",
                "每日运营工作台 · 便携运行，无需命令行",
                SS_LEFT,
                36,
                68,
                650,
                28,
            )
            self.wecom_button = self._create_control(
                "BUTTON",
                "自动收件",
                BS_PUSHBUTTON | WS_TABSTOP,
                36,
                120,
                650,
                62,
                ID_WECOM_DOWNLOAD,
                variant="primary",
            )
            self.wecom_settings_button = self._create_control(
                "BUTTON",
                "设置",
                BS_PUSHBUTTON | WS_TABSTOP,
                704,
                120,
                144,
                62,
                ID_WECOM_SETTINGS,
                variant="ghost",
            )
            self.tracking_button = self._create_control(
                "BUTTON",
                "提取运单号并复制",
                BS_PUSHBUTTON | WS_TABSTOP,
                36,
                200,
                390,
                62,
                ID_TRACKING,
                variant="secondary",
            )
            self.dc_export_button = self._create_control(
                "BUTTON",
                "中心运单导出",
                BS_PUSHBUTTON | WS_TABSTOP,
                458,
                200,
                390,
                62,
                ID_DC_EXPORT,
                variant="secondary",
            )
            self.report_button = self._create_control(
                "BUTTON",
                "Webhook 一键日报",
                BS_PUSHBUTTON | WS_TABSTOP,
                36,
                280,
                812,
                62,
                ID_REPORT,
                variant="primary",
            )
            self.text_label = self._create_control(
                "STATIC",
                "群发消息",
                SS_LEFT,
                36,
                356,
                560,
                24,
            )
            self.text_targets_label = self._create_control(
                "STATIC",
                "接收群",
                SS_LEFT,
                616,
                356,
                232,
                24,
            )
            self.text_message_edit = self._create_control(
                "EDIT",
                "",
                WS_BORDER | WS_TABSTOP | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN,
                36,
                382,
                560,
                116,
                ID_TEXT_MESSAGE,
            )
            self._set_cue_banner(self.text_message_edit, "输入消息内容，例如：HMT - TRG 今日到件更新")
            self.text_target_search_edit = self._create_control(
                "EDIT",
                "",
                WS_BORDER | WS_TABSTOP | ES_AUTOHSCROLL,
                616,
                382,
                232,
                30,
                ID_TEXT_TARGET_SEARCH,
            )
            self._set_cue_banner(self.text_target_search_edit, "搜索群名")
            self.text_targets_list = self._create_control(
                "LISTBOX",
                "",
                WS_BORDER | WS_TABSTOP | WS_VSCROLL | LBS_MULTIPLESEL | LBS_NOINTEGRALHEIGHT,
                616,
                420,
                232,
                78,
                ID_TEXT_TARGETS,
            )
            self.text_selection_status = self._create_control(
                "STATIC",
                "已选 0 个群",
                SS_LEFT,
                616,
                538,
                232,
                20,
            )
            try:
                self.text_destinations = configured_text_destinations()
            except Exception as exc:
                self.text_destination_error = str(exc)
                self.text_destinations = []
            self._refresh_text_destination_list()
            self.text_auto_select_button = self._create_control(
                "BUTTON",
                "按线路自动选群",
                BS_PUSHBUTTON | WS_TABSTOP,
                616,
                562,
                232,
                34,
                ID_AUTO_SELECT_ROUTE_GROUPS,
                variant="ghost",
            )
            self.text_send_button = self._create_control(
                "BUTTON",
                "发送消息",
                BS_PUSHBUTTON | WS_TABSTOP,
                616,
                604,
                232,
                48,
                ID_SEND_TEXT,
                variant="primary",
            )
            self.dispatch_label = self._create_control(
                "STATIC",
                "自动分单",
                SS_LEFT,
                36,
                356,
                610,
                24,
            )
            self.dispatch_route_edit = self._create_control(
                "EDIT",
                "",
                WS_BORDER | WS_TABSTOP | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN,
                36,
                382,
                590,
                128,
                ID_DISPATCH_ROUTE,
            )
            self._set_cue_banner(self.dispatch_route_edit, "每行输入：线路 - 司机；例如 301所有 - 张三")
            self.dispatch_button = self._create_control(
                "BUTTON",
                "自动合并并选司机",
                BS_PUSHBUTTON | WS_TABSTOP,
                646,
                415,
                202,
                52,
                ID_AUTO_DISPATCH,
                variant="primary",
            )
            self.status = self._create_control(
                "STATIC",
                "就绪 · 日常请先打开 iMile x WISEWAY 主群",
                SS_LEFT,
                36,
                528,
                812,
                28,
            )
            self.log_label = self._create_control("STATIC", "运行记录", SS_LEFT, 36, 563, 120, 24)
            self.log = self._create_control(
                "EDIT",
                "",
                WS_BORDER | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY,
                36,
                593,
                812,
                155,
            )
            return 0
        if msg == WM_SIZE:
            client_width = int(lparam) & 0xFFFF
            client_height = (int(lparam) >> 16) & 0xFFFF
            self._layout_controls(client_width, client_height)
            return 0
        if msg == WM_COMMAND:
            command_id = int(wparam) & 0xFFFF
            notification = (int(wparam) >> 16) & 0xFFFF
            if command_id == ID_TEXT_TARGET_SEARCH and notification == EN_CHANGE and not self.busy:
                self._refresh_text_destination_list()
            elif command_id == ID_TEXT_TARGETS and notification == LBN_SELCHANGE:
                self._sync_selected_text_destinations()
            elif command_id == ID_WECOM_DOWNLOAD and not self.busy:
                self._start("正在识别当前群并下载对应附件…", run_wecom_download)
            elif command_id == ID_WECOM_SETTINGS and not self.busy:
                try:
                    path = open_wecom_config()
                    user32.SetWindowTextW(self.status, f"已打开收件配置：{path.name}")
                except Exception as exc:
                    user32.MessageBoxW(self.hwnd, str(exc), "无法打开配置", 0x10)
            elif command_id == ID_TRACKING and not self.busy:
                files = self._file_dialog(
                    True,
                    "选择需要提取运单号的 Excel 或 CSV 文件",
                    "Excel / CSV 文件\0*.xls;*.xlsx;*.csv\0所有文件\0*.*\0",
                )
                if files:
                    self._start("正在提取运单号并复制到剪贴板…", run_tracking, files)
            elif command_id == ID_DC_EXPORT and not self.busy:
                self._start("正在查询并下载中心运单查询…", run_dc_export)
            elif command_id == ID_REPORT and not self.busy:
                files = self._file_dialog(False, "选择中心运单查询 Excel", "Excel 文件\0*.xlsx\0所有文件\0*.*\0")
                if files:
                    allow_old_source = False
                    try:
                        freshness_warning = center_waybill_file_freshness_warning(files[0])
                    except OSError as exc:
                        user32.MessageBoxW(
                            self.hwnd,
                            f"无法读取所选文件：\n{files[0]}\n\n{exc}",
                            "无法检查中心运单查询文件",
                            0x10,
                        )
                        user32.SetWindowTextW(self.status, "已取消发送：无法读取所选文件。")
                        return 0
                    if freshness_warning:
                        result = user32.MessageBoxW(
                            self.hwnd,
                            f"{freshness_warning}\n\n"
                            "请确认是不是忘记下载或替换今天的文件。\n\n"
                            "选择“是”：仍用这个文件生成并通过 Webhook 发送日报\n"
                            "选择“否”：取消发送，返回更新文件\n\n"
                            "是否仍要继续？",
                            "中心运单查询文件可能未更新",
                            0x00000004 | 0x00000030 | 0x00000100,
                        )
                        if result != 6:
                            user32.SetWindowTextW(
                                self.status,
                                "已取消发送：请重新选择今天更新的中心运单查询文件。",
                            )
                            return 0
                        allow_old_source = True
                    self._start(
                        "正在生成并通过 Webhook 发送日报…",
                        run_report,
                        files[0],
                        allow_old_source,
                        "webhook",
                    )
            elif command_id == ID_AUTO_SELECT_ROUTE_GROUPS and not self.busy:
                if self.text_destination_error:
                    user32.MessageBoxW(
                        self.hwnd,
                        self.text_destination_error,
                        "无法读取飞书群配置",
                        0x10,
                    )
                else:
                    self._auto_select_route_groups()
            elif command_id == ID_SEND_TEXT and not self.busy:
                text = self._get_control_text(self.text_message_edit)
                selected_indexes = self._selected_text_destination_indexes()
                if self.text_destination_error:
                    user32.MessageBoxW(
                        self.hwnd,
                        self.text_destination_error,
                        "无法读取飞书群配置",
                        0x10,
                    )
                elif not text:
                    user32.MessageBoxW(self.hwnd, "请先输入要发送的文字。", "无法发送", 0x30)
                elif not selected_indexes:
                    user32.MessageBoxW(self.hwnd, "请至少选择一个接收群。", "无法发送", 0x30)
                else:
                    names = [
                        self.text_destinations[index].get("name", "未命名群")
                        for index in selected_indexes
                    ]
                    preview = "\n".join(f"• {name}" for name in names[:10])
                    if len(names) > 10:
                        preview += f"\n• 以及另外 {len(names) - 10} 个群"
                    confirmation = (
                        f"同一条文字将发送到 {len(names)} 个群：\n\n"
                        f"{preview}\n\n"
                        "发送后会立即出现在这些群中。是否继续？"
                    )
                    result = user32.MessageBoxW(
                        self.hwnd,
                        confirmation,
                        "确认群发文字",
                        0x00000004 | 0x00000030 | 0x00000100,
                    )
                    if result == 6:
                        self._start(
                            f"正在向 {len(names)} 个群发送文字…",
                            run_text_message,
                            text,
                            selected_indexes,
                        )
            elif command_id == ID_AUTO_DISPATCH and not self.busy:
                manifest = self._get_control_text(self.dispatch_route_edit)
                if not manifest:
                    user32.MessageBoxW(
                        self.hwnd,
                        "请先粘贴分单清单，每行填写线路和司机。",
                        "无法自动分单",
                        0x30,
                    )
                else:
                    task_count = len([line for line in manifest.splitlines() if line.strip()])
                    confirmation = (
                        f"已粘贴 {task_count} 行分单清单。\n\n"
                        "每行开头的线路属于同一组，后面的文字是司机。\n"
                        "404B、404S 会自动转换为 404 B、404 S。\n"
                        "301所有表示 301 及其所有单字母后缀。\n"
                        "每组选好司机后，最后的“确定”仍由你在网页中手动点击；\n"
                        "确认成功后程序会自动继续下一组。\n"
                        "是否继续？"
                    )
                    result = user32.MessageBoxW(
                        self.hwnd,
                        confirmation,
                        "确认自动分单",
                        0x00000004 | 0x00000030 | 0x00000100,
                    )
                    if result == 6:
                        self._start(
                            f"正在处理 {task_count} 组分单任务…",
                            run_auto_dispatch_manifest,
                            manifest,
                        )
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

    def _set_task_controls_enabled(self, enabled):
        controls = (
            self.wecom_button,
            self.wecom_settings_button,
            self.tracking_button,
            self.dc_export_button,
            self.report_button,
            self.text_message_edit,
            self.text_target_search_edit,
            self.text_targets_list,
            self.text_auto_select_button,
            self.text_send_button,
            self.dispatch_route_edit,
            self.dispatch_driver_edit,
            self.dispatch_button,
        )
        for control in controls:
            if control:
                user32.EnableWindow(control, enabled)

    def _start(self, status, function, *args):
        self.busy = True
        self._set_task_controls_enabled(False)
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
                self._set_task_controls_enabled(True)
                prefix = "完成 · " if kind == "success" else "失败 · "
                user32.SetWindowTextW(self.status, prefix + payload)
                icon = 0x40 if kind == "success" else 0x10
                user32.MessageBoxW(self.hwnd, payload, "完成" if kind == "success" else "操作失败", icon)

    def _append_log(self, text):
        length = user32.GetWindowTextLengthW(self.log)
        user32.SendMessageW(self.log, EM_SETSEL, length, length)
        text_buffer = ctypes.create_unicode_buffer(text)
        user32.SendMessageW(
            self.log,
            EM_REPLACESEL,
            False,
            ctypes.addressof(text_buffer),
        )


if __name__ == "__main__":
    IMileWin32App().run()
