# -*- coding: utf-8 -*-
"""
Command Centre — context menu entry point.

Registered against kodi.context.item in addon.xml with visible=true,
so this fires from any right-click / long-press context menu, on any
screen or item type. It does not read the selected ListItem — the
popup does not adapt its contents based on what was clicked.
"""
import sys
import os
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo('path')

# Make resources/lib importable when invoked as a context script
LIB_PATH = os.path.join(ADDON_PATH, 'resources', 'lib')
if LIB_PATH not in sys.path:
    sys.path.append(LIB_PATH)

from dialog import open_command_center  # noqa: E402


if __name__ == '__main__':
    open_command_center()
