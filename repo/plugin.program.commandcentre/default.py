# -*- coding: utf-8 -*-
"""Command Centre - script entry point.

RunScript(plugin.program.commandcentre[, mode]) passes the mode through sys.argv.
The buttons in the addon settings call it with a mode to reach a configuration flow;
with no mode (Programs list, a keymap binding...) the popup opens, exactly like the
context-menu entry (context.py).
"""
import sys

import xbmcaddon

ADDON_PATH = xbmcaddon.Addon().getAddonInfo('path')
if ADDON_PATH not in sys.path:
    sys.path.insert(0, ADDON_PATH)

# mode -> name of the function in resources/lib/settings_actions.py
MODES = {
    'configure': 'configure_main',
    'configure_video_addons': 'configure_video_addons',
    'configure_music_addons': 'configure_music_addons',
    'configure_picture_addons': 'configure_picture_addons',
    'configure_program_addons': 'configure_program_addons',
    'configure_system_functions': 'configure_system_functions',
    'configure_shortcuts': 'configure_shortcuts',
    'configure_favourites': 'configure_favourites',
    'configure_nav_color': 'configure_nav_color',
    'configure_menu_order': 'configure_menu_order',
    'configure_backup': 'configure_backup',
}


def main():
    mode = sys.argv[1].strip() if len(sys.argv) > 1 else ''
    if mode in MODES:
        from resources.lib import settings_actions
        getattr(settings_actions, MODES[mode])()
    else:
        from resources.lib.dialog import open_command_center
        open_command_center()


if __name__ == '__main__':
    main()
