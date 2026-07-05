"""pywebview penceresi ve windows ikon ayarı."""

from __future__ import annotations

import ctypes
import os
import threading
import time
import webview
from ctypes import wintypes

from onlyfans_plus.app.api import Api

APP_TITLE = "OnlyFans+"
APP_ID = "kynarix.OnlyFansPlus"


def png_to_ico(png_path: str, ico_path: str) -> bool:
    # pillow ile çok boyutlu ico üret
    try:
        from PIL import Image
        img = Image.open(png_path).convert("RGBA")
        sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save(ico_path, format="ICO", sizes=sizes)
        return True
    except Exception:
        return False


def _set_app_user_model_id() -> None:
    # taskbar'ın python.exe altında gruplayıp python ikonunu göstermesini engeller
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def apply_window_icon(window_title: str, ico_path: str) -> None:
    # pencere açılınca hwnd'yi bulup caption + taskbar ikonunu set eder
    try:
        user32 = ctypes.windll.user32

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_BIG = 1
        ICON_SMALL = 0

        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = wintypes.LPARAM
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL

        hbig = user32.LoadImageW(0, ico_path, IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
        hsmall = user32.LoadImageW(0, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if not hbig and not hsmall:
            return

        found = 0

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _):
            nonlocal found
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == window_title:
                found = hwnd
                return False
            return True

        def find_and_set():
            nonlocal found
            found = 0
            user32.EnumWindows(ctypes.cast(enum_cb, ctypes.c_void_p), 0)
            if found:
                if hbig:
                    user32.SendMessageW(found, WM_SETICON, ICON_BIG, hbig)
                if hsmall:
                    user32.SendMessageW(found, WM_SETICON, ICON_SMALL, hsmall)
                return True
            return False

        # pencere açılmasını bekle, webview2 bazen ikonu sıfırladığı için birkaç kez yenile
        for _ in range(40):
            if find_and_set():
                break
            time.sleep(0.15)
        for _ in range(6):
            find_and_set()
            time.sleep(0.4)
    except Exception:
        pass


def _setup_icon() -> None:
    # png -> ico (logo değişirse tazele), sonra ikonu arka planda set et
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    png = os.path.join(base, "web", "logo.png")
    ico = os.path.join(base, "web", "logo.ico")
    if not os.path.exists(png):
        return
    # exe modunda ico zaten paketlendi, yeniden üretmeye gerek yok
    need = (not os.path.exists(ico)) or (
        not getattr(__import__("sys"), "frozen", False)
        and os.path.getmtime(png) > os.path.getmtime(ico)
    )
    if need:
        png_to_ico(png, ico)
    if os.path.exists(ico):
        threading.Thread(target=apply_window_icon, args=(APP_TITLE, ico), daemon=True).start()


def run() -> None:
    _set_app_user_model_id()
    _setup_icon()

    api = Api()
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = os.path.join(base, "web", "index.html")

    window = webview.create_window(
        APP_TITLE,
        url=html,
        js_api=api,
        width=1180,
        height=780,
        min_size=(960, 640),
        text_select=False,
    )
    api.set_window(window)
    # windows 11'de edgechromium (webview2) varsayılan
    webview.start(debug=False)
