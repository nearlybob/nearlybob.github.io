# -*- coding: utf-8 -*-
"""Command Centre - context menu entry point.

Registered against kodi.context.item in addon.xml with visible=true, so it appears in
every context menu, on any screen or item type. It does not read the selected item -
the popup never adapts its contents to what was clicked.
"""
import sys

import xbmcaddon

ADDON_PATH = xbmcaddon.Addon().getAddonInfo('path')
if ADDON_PATH not in sys.path:
    sys.path.insert(0, ADDON_PATH)

from resources.lib.dialog import open_command_center  # noqa: E402

if __name__ == '__main__':
    open_command_center()
