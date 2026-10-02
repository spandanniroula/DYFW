"""Windows integration: single instance, startup, tray icon, flashing, sounds, app icon."""

import ctypes
import os
import sys

try:
    import winreg
except ImportError:  # non-Windows
    winreg = None

try:
    import winsound
except ImportError:
    winsound = None

APP_NAME = "DYFW"
OLD_APP_NAME = "StickyNote"
TAGLINE = "Do Your Fucken Work"
_MUTEX_NAME = "Local\\DYFW_SingleInstance"
_SHOW_EVENT_NAME = "Local\\DYFW_Show"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

try:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateMutexW.restype = ctypes.c_void_p
    _k32.CreateEventW.restype = ctypes.c_void_p
    _k32.OpenEventW.restype = ctypes.c_void_p
    _k32.SetEvent.argtypes = [ctypes.c_void_p]
    _k32.CloseHandle.argtypes = [ctypes.c_void_p]
    _k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _k32.WaitForSingleObject.restype = ctypes.c_uint32
except (AttributeError, OSError):
    _k32 = None


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


# ---------------------------------------------------------------- single instance

_mutex = None


def already_running():
    global _mutex
    if not _k32:
        return False
    _mutex = _k32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def signal_existing_instance():
    """Ask the already-running copy to show its note."""
    if not _k32:
        return
    h = _k32.OpenEventW(0x0002, False, _SHOW_EVENT_NAME)  # EVENT_MODIFY_STATE
    if h:
        _k32.SetEvent(h)
        _k32.CloseHandle(h)


class ShowSignal:
    """Auto-reset event that a second launch sets to bring this instance forward."""

    def __init__(self):
        self.handle = _k32.CreateEventW(None, False, False, _SHOW_EVENT_NAME) if _k32 else None

    def poll(self):
        return bool(self.handle) and _k32.WaitForSingleObject(self.handle, 0) == 0


# ---------------------------------------------------------------- start with Windows

def _startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    script = os.path.abspath(sys.argv[0])
    return f'"{pythonw}" "{script}"'


def is_startup_enabled():
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_startup(enabled):
    if not winreg:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def migrate_old_startup():
    """Carry 'Start with Windows' over from the old StickyNote name to this exe."""
    if not winreg:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
            winreg.QueryValueEx(key, OLD_APP_NAME)
            winreg.DeleteValue(key, OLD_APP_NAME)
    except OSError:
        return
    set_startup(True)


# ---------------------------------------------------------------- screen / attention

def virtual_screen():
    try:
        u32 = ctypes.windll.user32
        return tuple(u32.GetSystemMetrics(i) for i in (76, 77, 78, 79))
    except Exception:
        return None


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT), ("rcWork", _RECT),
                ("dwFlags", ctypes.c_ulong)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def work_area(x, y):
    """(left, top, right, bottom) of the usable area (no taskbar) of the monitor at x, y."""
    try:
        u32 = ctypes.windll.user32
        u32.MonitorFromPoint.restype = ctypes.c_void_p
        u32.MonitorFromPoint.argtypes = [_POINT, ctypes.c_ulong]
        u32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        hmon = u32.MonitorFromPoint(_POINT(int(x), int(y)), 2)  # MONITOR_DEFAULTTONEAREST
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if hmon and u32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcWork
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- per-pixel alpha windows

class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


_GWL_EXSTYLE, _WS_EX_LAYERED = -20, 0x80000


def _toplevel_hwnd(widget):
    u32 = ctypes.windll.user32
    u32.GetParent.restype = ctypes.c_void_p
    u32.GetParent.argtypes = [ctypes.c_void_p]
    u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    return u32.GetParent(widget.winfo_id())


def begin_layered(widget):
    """Switch a window to per-pixel-alpha mode (resets any Tk -alpha/-transparentcolor)."""
    try:
        u32 = ctypes.windll.user32
        hwnd = _toplevel_hwnd(widget)
        ex = u32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
        u32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, ex & ~_WS_EX_LAYERED)
        u32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_LAYERED)
        return True
    except Exception:
        return False


def end_layered(widget):
    """Leave per-pixel-alpha mode so Tk can manage the window's transparency again."""
    try:
        u32 = ctypes.windll.user32
        hwnd = _toplevel_hwnd(widget)
        ex = u32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
        u32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, ex & ~_WS_EX_LAYERED)
    except Exception:
        pass


def update_layered(widget, image):
    """Show a PIL RGBA image as the window, with smooth (anti-aliased) per-pixel transparency.

    Fully transparent pixels are click-through. Returns False if Windows refused.
    """
    try:
        from PIL import Image, ImageChops
        u32, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        hwnd = _toplevel_hwnd(widget)
        w, h = image.size
        r, g, b, a = image.split()
        # Windows wants premultiplied BGRA
        r, g, b = (ImageChops.multiply(ch, a) for ch in (r, g, b))
        data = Image.merge("RGBA", (b, g, r, a)).tobytes()

        u32.GetDC.restype = ctypes.c_void_p
        u32.GetDC.argtypes = [ctypes.c_void_p]
        u32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        gdi.CreateDIBSection.restype = ctypes.c_void_p
        gdi.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                         ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                         ctypes.c_uint32]
        gdi.SelectObject.restype = ctypes.c_void_p
        gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi.DeleteDC.argtypes = [ctypes.c_void_p]
        u32.UpdateLayeredWindow.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_SIZE),
            ctypes.c_void_p, ctypes.POINTER(_POINT), ctypes.c_uint32,
            ctypes.POINTER(_BLENDFUNCTION), ctypes.c_uint32]

        screen = u32.GetDC(None)
        mem = gdi.CreateCompatibleDC(screen)
        header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bmp = gdi.CreateDIBSection(mem, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, data, len(data))
        old = gdi.SelectObject(mem, bmp)
        ok = u32.UpdateLayeredWindow(hwnd, screen, None, ctypes.byref(_SIZE(w, h)), mem,
                                     ctypes.byref(_POINT(0, 0)), 0,
                                     ctypes.byref(_BLENDFUNCTION(0, 0, 255, 1)), 2)  # ULW_ALPHA
        gdi.SelectObject(mem, old)
        gdi.DeleteObject(bmp)
        gdi.DeleteDC(mem)
        u32.ReleaseDC(None, screen)
        return bool(ok)
    except Exception:
        return False


def style_window(widget, rounded=True, border=None):
    """Windows 11: rounded corners and a thin border in `border` ('#rrggbb' or None = no border).

    Returns False on systems without these DWM options (Windows 10), so callers can fall back.
    """
    try:
        u32 = ctypes.windll.user32
        u32.GetParent.restype = ctypes.c_void_p
        u32.GetParent.argtypes = [ctypes.c_void_p]
        hwnd = ctypes.c_void_p(u32.GetParent(widget.winfo_id()))
        dwm = ctypes.windll.dwmapi
        pref = ctypes.c_int(2 if rounded else 1)  # DWMWCP_ROUND / DWMWCP_DONOTROUND
        ok = dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4) == 0
        if border:
            r, g, b = (int(border[i:i + 2], 16) for i in (1, 3, 5))
            color = ctypes.c_uint(r | (g << 8) | (b << 16))
        else:
            color = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(color), 4)
        return ok
    except Exception:
        return False


def hide_from_taskbar(widget):
    """Make a mapped Tk window a tool window: no taskbar button, not in Alt+Tab."""
    try:
        u32 = ctypes.windll.user32
        u32.GetParent.restype = ctypes.c_void_p
        u32.GetParent.argtypes = [ctypes.c_void_p]
        u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        hwnd = u32.GetParent(widget.winfo_id())
        ex = u32.GetWindowLongPtrW(hwnd, -20)  # GWL_EXSTYLE
        new = (ex | 0x80) & ~0x40000  # +WS_EX_TOOLWINDOW, -WS_EX_APPWINDOW
        if new != ex:
            u32.SetWindowLongPtrW(hwnd, -20, new)
            # The taskbar only re-reads the style when the window is shown again.
            u32.ShowWindow(hwnd, 0)  # SW_HIDE
            u32.ShowWindow(hwnd, 8)  # SW_SHOWNA
    except Exception:
        pass


def beep():
    if winsound:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass


def pick_font(families, candidates, fallback="Segoe UI"):
    return next((c for c in candidates if c in families), fallback)


# ---------------------------------------------------------------- icon + tray

def make_icon_image(size=64):
    from PIL import Image, ImageDraw

    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m, fold = 18, 70
    d.polygon([(m, m), (s - m, m), (s - m, s - m - fold), (s - m - fold, s - m), (m, s - m)],
              fill="#f9d949", outline="#b8941a", width=8)
    d.rectangle((m + 4, m + 4, s - m - 4, m + 44), fill="#f2c418")
    d.polygon([(s - m, s - m - fold), (s - m - fold, s - m - fold), (s - m - fold, s - m)],
              fill="#d9b12a", outline="#b8941a", width=6)
    for i, right in enumerate((s - m - 36, s - m - 36, s - m - fold - 20)):
        y = 112 + i * 40
        d.line((m + 32, y, right, y), fill="#7a5c00", width=12)
    return img.resize((size, size), Image.LANCZOS)


def make_icon_photo(master):
    try:
        from PIL import ImageTk
        return ImageTk.PhotoImage(make_icon_image(64), master=master)
    except Exception:
        return None


class Tray:
    """System-tray icon. `post(cmd)` is called from the tray thread with a command string."""

    def __init__(self, post, startup_checked):
        import pystray

        item = pystray.MenuItem
        menu = pystray.Menu(
            item("Show / hide note", lambda: post("toggle"), default=True),
            item("Sync calendars now", lambda: post("sync")),
            item("Start with Windows", lambda: post("startup"),
                 checked=lambda _i: startup_checked()),
            pystray.Menu.SEPARATOR,
            item("Quit DYFW", lambda: post("quit")),
        )
        self.icon = pystray.Icon(APP_NAME, make_icon_image(64), f"DYFW · {TAGLINE}", menu)
        self.icon.run_detached()

    def notify(self, message, title="DYFW"):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def refresh(self):
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass
