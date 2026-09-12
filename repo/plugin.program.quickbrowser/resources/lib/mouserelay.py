# -*- coding: utf-8 -*-
"""
Thin wrapper around the Windows user32 API for moving the real OS
mouse cursor and sending click events.

Uses ctypes (part of the Python standard library) rather than pywin32,
since pywin32 is not guaranteed to be present in Kodi's bundled Python
and addons cannot easily pip-install extra packages.

Windows only.
"""

import ctypes
import ctypes.wintypes as wintypes

import xbmc

user32 = ctypes.windll.user32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120  # one "notch" of a standard mouse wheel, per the Windows API

# Windows virtual screen bounds (SM_XVIRTUALSCREEN etc.) so cursor
# movement can be clamped and doesn't get "lost" off multi-monitor
# setups.
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


def _get_virtual_screen_bounds():
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return x, y, x + w - 1, y + h - 1


def get_cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_cursor_relative(dx, dy):
    """
    Move the real OS cursor by (dx, dy) pixels, clamped to the screen.

    Returns True if the move was blocked by the screen edge in the
    direction of travel - i.e. the cursor was already at that edge
    and didn't actually move - so callers can trigger a scroll
    instead of a no-op move.
    """
    x, y = get_cursor_pos()
    min_x, min_y, max_x, max_y = _get_virtual_screen_bounds()
    target_x = x + dx
    target_y = y + dy
    new_x = max(min_x, min(max_x, target_x))
    new_y = max(min_y, min(max_y, target_y))
    result = user32.SetCursorPos(new_x, new_y)

    # Diagnostic: confirms whether SetCursorPos actually took effect
    # at the OS level, rather than assuming it did just because the
    # call didn't raise. Logged at DEBUG since this fires on every
    # single directional press - would flood the log at a higher
    # level. SetCursorPos returns a nonzero value on success (BOOL);
    # a genuine mismatch between requested and actual position after
    # the call points at something blocking the move at the OS level
    # (e.g. another process/driver holding cursor control) rather
    # than a bug in this addon's own arithmetic.
    actual_x, actual_y = get_cursor_pos()
    xbmc.log(
        '[plugin.program.quickbrowser] move_cursor_relative: requested ({},{}) -> target ({},{}), '
        'SetCursorPos returned {}, actual position after call: ({},{})'.format(
            dx, dy, new_x, new_y, result, actual_x, actual_y
        ),
        xbmc.LOGDEBUG,
    )

    hit_edge = (dx != 0 and new_x == x and target_x != x) or (
        dy != 0 and new_y == y and target_y != y
    )
    return hit_edge


def left_click():
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def right_click():
    user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)


def scroll(notches):
    """Positive notches scroll up, negative scroll down (standard Windows wheel convention)."""
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(WHEEL_DELTA * notches), 0)


def scroll_up(notches=3):
    scroll(notches)


def scroll_down(notches=3):
    scroll(-notches)


# Keyboard - used for the browser-back shortcut (Alt+Left), which is
# a standard Chrome/Windows convention. Sent via keybd_event, which
# (unlike SetCursorPos) goes to whichever window currently has OS
# focus - that's Chrome while it's fullscreen on top, which is what
# we want here.
VK_MENU = 0x12  # Alt
VK_LEFT = 0x25
KEYEVENTF_KEYUP = 0x0002


def browser_back():
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_LEFT, 0, 0, 0)
    user32.keybd_event(VK_LEFT, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
