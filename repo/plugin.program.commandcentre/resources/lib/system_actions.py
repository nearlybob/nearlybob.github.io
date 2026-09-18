# -*- coding: utf-8 -*-
"""
The System section's built-in functions, kept separate from
Shortcuts (which is for user-defined links to specific addon pages,
not system commands). Each entry has a stable 'id' so the user can
choose which ones show and set their order, the same way addon
visibility/order works.

This list is deliberately short and fixed — these are the only
entries Command Centre offers under System, on request, rather than
the previous broader set drawn from every System/Skin/Library/Add-on
built-in category.

Every action string here was checked against Kodi's own official
built-in-functions and window-IDs documentation, not assumed:
- The six ActivateWindow(...) targets use the exact window names from
  https://kodi.wiki/view/Window_IDs — notably "FavouritesBrowser",
  not "Favourites" (that window was removed and replaced in Kodi v20
  Nexus), and "Settings" for the settings *menu* specifically (not
  one of the SettingsCategory/SettingsSystem sub-windows).
- Toggle Fullscreen uses Action(togglefullscreen) rather than a bare
  "ToggleFullScreen()" builtin: "togglefullscreen" is documented as
  an Action ID (https://kodi.wiki/view/Action_IDs), not as its own
  built-in function, and Action(action[,window]) is the documented
  built-in for invoking an Action ID from a script/onclick.
- ToggleDebug() (debug logging) is a distinct, real Application
  built-in from Skin.ToggleDebug() (skin debug overlay) — the two
  are easy to conflate but toggle different things.
"""
import os
import xbmcaddon
import xbmcvfs

import addon_discovery

SYSTEM_KEY = 'system'
_ICON = 'DefaultAddonProgram.png'

_ADDON = xbmcaddon.Addon()
_PROFILE_PATH = xbmcvfs.translatePath(_ADDON.getAddonInfo('profile'))
_MIGRATION_MARKER = os.path.join(_PROFILE_PATH, 'system_actions_schema.txt')

# Bumped because the System list was replaced wholesale (kept to a fixed,
# short set of ActivateWindow targets and built-ins on request), so a
# previously saved visibility choice made against the old, much larger list
# would otherwise leave most or all of the new entries hidden by default —
# same problem, and same fix, as shortcuts_manager.SCHEMA_VERSION.
_SCHEMA_VERSION = '2'

SYSTEM_ACTIONS = [
    {'id': 'activate_screensaver', 'name': 'Activate Screensaver', 'icon': _ICON, 'action': 'ActivateScreensaver()'},
    {'id': 'window_addon_browser', 'name': 'Addons', 'icon': _ICON, 'action': 'ActivateWindow(AddonBrowser)'},
    {'id': 'toggle_debug_logging', 'name': 'Enable/Disable Debug Logging', 'icon': _ICON, 'action': 'ToggleDebug()'},
    {'id': 'window_favourites', 'name': 'Favourites', 'icon': _ICON, 'action': 'ActivateWindow(FavouritesBrowser)'},
    {'id': 'window_file_manager', 'name': 'File Manager', 'icon': _ICON, 'action': 'ActivateWindow(FileManager)'},
    {'id': 'window_home', 'name': 'Home', 'icon': _ICON, 'action': 'ActivateWindow(Home)'},
    {'id': 'minimize_kodi', 'name': 'Minimize Kodi', 'icon': _ICON, 'action': 'Minimize()'},
    {'id': 'reload_skin', 'name': 'Reload Skin', 'icon': _ICON, 'action': 'ReloadSkin()'},
    {'id': 'restart_kodi', 'name': 'Restart Kodi', 'icon': _ICON, 'action': 'RestartApp()'},
    {'id': 'window_settings', 'name': 'Settings', 'icon': _ICON, 'action': 'ActivateWindow(Settings)'},
    {'id': 'window_shutdown_menu', 'name': 'Shutdown Menu', 'icon': _ICON, 'action': 'ActivateWindow(ShutdownMenu)'},
    {'id': 'toggle_fullscreen', 'name': 'Toggle Fullscreen', 'icon': _ICON, 'action': 'Action(togglefullscreen)'},
    {'id': 'update_addon_repos', 'name': 'Update Addon Repositories', 'icon': _ICON, 'action': 'UpdateAddonRepos()'},
]


def _ensure_migrated():
    current = None
    if xbmcvfs.exists(_MIGRATION_MARKER):
        with open(_MIGRATION_MARKER, 'r', encoding='utf-8') as f:
            current = f.read().strip()
    if current == _SCHEMA_VERSION:
        return
    addon_discovery.clear_visible_addon_ids(SYSTEM_KEY)
    if not xbmcvfs.exists(_PROFILE_PATH):
        xbmcvfs.mkdirs(_PROFILE_PATH)
    with open(_MIGRATION_MARKER, 'w', encoding='utf-8') as f:
        f.write(_SCHEMA_VERSION)


_ensure_migrated()


def get_visible_system_actions():
    chosen_ids = addon_discovery.get_chosen_ids(SYSTEM_KEY)
    if chosen_ids is None:
        return SYSTEM_ACTIONS
    return [a for a in SYSTEM_ACTIONS if a['id'] in chosen_ids]


def set_visible_system_ids(ids):
    addon_discovery.set_visible_addon_ids(SYSTEM_KEY, ids)
