# -*- coding: utf-8 -*-
"""Shared constants and small helpers used across Command Centre.

One ``xbmcaddon.Addon()`` and one set of paths/action ids live here instead of
being repeated in every module.
"""
import contextlib
import traceback

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON_ID = 'plugin.program.commandcentre'
# Explicit id (not Addon()) so the same code also works when it is run from another
# addon's script, e.g. the separate "add to shortcuts" context-menu addon.
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_PATH = ADDON.getAddonInfo('path')
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

# Kodi action ids (https://kodi.wiki/view/Action_IDs)
ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2
ACTION_MOVE_UP = 3
ACTION_MOVE_DOWN = 4
ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
ACTION_MOUSE_RIGHT_CLICK = 101
ACTION_MOUSE_LONG_CLICK = 108
ACTION_CONTEXT_MENU = 117
CLOSE_ACTIONS = (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK)
CONTEXT_ACTIONS = (ACTION_CONTEXT_MENU, ACTION_MOUSE_RIGHT_CLICK, ACTION_MOUSE_LONG_CLICK)

DEFAULT_ICON = 'DefaultAddonProgram.png'
DEFAULT_NAV_COLOR = 'FFFFFFFF'
LIGHT_LUMINANCE_THRESHOLD = 128  # 0-255; ITU-R BT.601 perceptual luma


def tr(string_id):
    """Localised string for an id from resources/lib/strings.py (S.*)."""
    return ADDON.getLocalizedString(string_id)


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[{}] {}'.format(ADDON_ID, message), level)


def log_exception(context=''):
    log('{}\n{}'.format(context, traceback.format_exc()), xbmc.LOGERROR)


def notify(message, icon=xbmcgui.NOTIFICATION_INFO):
    xbmcgui.Dialog().notification(ADDON_NAME, message, icon)


def focus_id(window):
    """Id of the focused control, or -1 when nothing has focus.
    Window.getFocusId() raises RuntimeError in that case."""
    try:
        return window.getFocusId()
    except RuntimeError:
        return -1


@contextlib.contextmanager
def busy():
    """Kodi's busy spinner around a slow call (JSON-RPC directory listing...)."""
    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    try:
        yield
    finally:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')


def get_bool_setting(setting_id, default=True):
    value = ADDON.getSetting(setting_id)
    if value == '':
        return default
    return value.lower() == 'true'


def get_int_setting(setting_id, default):
    try:
        return int(float(ADDON.getSetting(setting_id)))
    except (TypeError, ValueError):
        return default


def normalize_color(value):
    """RRGGBB or AARRGGBB (optionally with '#') -> upper-case AARRGGBB, else None.
    Kodi reads an 8-digit value as AARRGGBB, so a bare 6-digit value would be
    fully transparent - always store the normalised form."""
    s = (value or '').strip().lstrip('#')
    if len(s) not in (6, 8):
        return None
    try:
        int(s, 16)
    except ValueError:
        return None
    return ('FF' + s if len(s) == 6 else s).upper()


def get_nav_color():
    return normalize_color(ADDON.getSetting('nav_highlight_color')) or DEFAULT_NAV_COLOR


def is_light_color(hex_color):
    """True if black text reads better than white on this colour (perceptual luma)."""
    s = normalize_color(hex_color)
    if s is None:
        return False
    r, g, b = int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16)
    return (r * 299 + g * 587 + b * 114) / 1000 >= LIGHT_LUMINANCE_THRESHOLD
