# -*- coding: utf-8 -*-
"""
Command Centre — default entry point.

RunScript(addonid[,args]) passes extra params through sys.argv (this
is documented, real Kodi behaviour — see the built-in function
reference for RunScript). settings.xml's action buttons call this
with a mode argument to reach the configuration flows instead of the
popup dialog; a bare RunScript(plugin.program.commandcentre) — e.g.
from a future keymap binding — opens the popup, same as the context
menu entry in resources/lib/context.py.
"""
import sys
import os
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo('path')

LIB_PATH = os.path.join(ADDON_PATH, 'resources', 'lib')
if LIB_PATH not in sys.path:
    sys.path.append(LIB_PATH)

from dialog import open_command_center  # noqa: E402
import settings_actions  # noqa: E402

MODE_HANDLERS = {
    'configure_video_addons': settings_actions.configure_video_addons,
    'configure_program_addons': settings_actions.configure_program_addons,
    'configure_system_functions': settings_actions.configure_system_functions,
    'configure_shortcuts': settings_actions.configure_shortcuts,
    'configure_nav_color': settings_actions.configure_nav_color,
    'configure_menu_order': settings_actions.configure_menu_order,
}


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else None
    handler = MODE_HANDLERS.get(mode)
    if handler:
        handler()
    else:
        open_command_center()
