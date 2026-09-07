# -*- coding: utf-8 -*-
"""
Thin ctypes wrapper around user32 for finding and moving/resizing windows.
Deliberately avoids pywin32 so it doesn't need to be separately installed
into Kodi's bundled Python.

Windows only. Every function fails soft (returns None/False) rather than
raising, since this runs inside Kodi's script sandbox and a crash here
should not take Kodi down.

pip_core.py imports this module unconditionally regardless of platform
(is_android() is only checked afterward, before any of these functions
are actually called) - ctypes.windll itself only exists on Windows, so
accessing it unconditionally at import time crashed the entire addon,
including the background service, for every Android user, confirmed via
a real traceback: AttributeError: module 'ctypes' has no attribute
'windll', raised from this exact line, before any platform check ever
got a chance to run. user32 is set to None on any platform where
windll doesn't exist, and every function below already checks for a
live window handle before touching it - find_window() and
get_screen_size() are the two that didn't, since they don't take a
handle to check, so those two now also guard against user32 being None.
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0
SW_SHOW = 5

if user32 is not None:
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint
    ]

    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]

    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    user32.ShowWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]


def find_window(title):
    """Exact-title window lookup. Returns an HWND int or None."""
    if user32 is None:
        return None
    hwnd = user32.FindWindowW(None, title)
    return hwnd if hwnd else None


def get_pid(hwnd):
    """PID that owns this window, or None. Used to force-terminate mpv
    reliably even if its IPC pipe isn't responding."""
    if not is_alive(hwnd):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def is_alive(hwnd):
    if not hwnd:
        return False
    return bool(user32.IsWindow(hwnd))


def get_rect(hwnd):
    """Returns (x, y, width, height) or None."""
    if not is_alive(hwnd):
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def set_rect(hwnd, x, y, w, h, topmost=False):
    if not is_alive(hwnd):
        return False
    z = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    return bool(user32.SetWindowPos(hwnd, z, int(x), int(y), int(w), int(h), SWP_SHOWWINDOW))


def hide(hwnd):
    """
    Hides the window entirely (SW_HIDE) rather than fighting over z-order,
    which tested correctly (confirmed via debug notifications showing the
    right API calls firing) but didn't visually work in practice. A
    hidden window categorically cannot cover anything, regardless of
    whatever z-order quirk was happening. Deliberately not SW_MINIMIZE -
    minimized windows can report unreliable geometry via GetWindowRect
    while minimized, whereas a hidden window keeps reporting its real
    position/size accurately the whole time, so Grow/Shrink/Move can
    still read and calculate from it correctly even while invisible.
    """
    if not is_alive(hwnd):
        return False
    return bool(user32.ShowWindow(hwnd, SW_HIDE))


def show(hwnd):
    if not is_alive(hwnd):
        return False
    return bool(user32.ShowWindow(hwnd, SW_SHOW))


def swap_rects(hwnd_a, hwnd_b, topmost_a=False, topmost_b=False):
    """Swap the on-screen position/size of two windows. Returns True only
    if both individual moves succeeded - topmost_a/topmost_b let the
    caller keep a specific window (e.g. the mpv PiP window) always-on-top
    regardless of which side of the swap it ends up on."""
    ra, rb = get_rect(hwnd_a), get_rect(hwnd_b)
    if not ra or not rb:
        return False
    ok_a = set_rect(hwnd_a, *rb, topmost=topmost_a)
    ok_b = set_rect(hwnd_b, *ra, topmost=topmost_b)
    return ok_a and ok_b


def get_screen_size():
    if user32 is None:
        return (0, 0)
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
