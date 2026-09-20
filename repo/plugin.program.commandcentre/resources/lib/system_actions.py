# -*- coding: utf-8 -*-
"""The System section: a short, fixed list of Kodi built-ins.

Every action string was checked against Kodi's built-in function and window-id
documentation (notably ActivateWindow(FavouritesBrowser) - not "Favourites" - on
Kodi 20+, and Action(togglefullscreen) rather than a bare ToggleFullScreen()).
Icons are Kodi's stock Default*.png textures; the skin falls back to
DefaultAddonProgram.png for any the active skin doesn't provide.

'name' is a string id (see label()); 'confirm' entries ask before running.
"""
from .common import DEFAULT_ICON, tr
from .strings import S

SYSTEM_KEY = 'system'


def _a(action_id, name, icon, action, confirm=None):
    return {'id': action_id, 'name': name, 'icon': icon, 'action': action, 'confirm': confirm}


SYSTEM_ACTIONS = [
    _a('activate_screensaver', S.SYS_SCREENSAVER, 'DefaultAddonScreensaver.png', 'ActivateScreensaver()'),
    _a('window_addon_browser', S.SYS_ADDONS, 'DefaultAddon.png', 'ActivateWindow(AddonBrowser)'),
    _a('toggle_debug_logging', S.SYS_DEBUG, 'DefaultIconInfo.png', 'ToggleDebug()'),
    _a('window_favourites', S.SYS_FAVOURITES, 'DefaultFavourites.png', 'ActivateWindow(FavouritesBrowser)'),
    _a('window_file_manager', S.SYS_FILE_MANAGER, 'DefaultHardDisk.png', 'ActivateWindow(FileManager)'),
    _a('window_home', S.SYS_HOME, 'DefaultFolder.png', 'ActivateWindow(Home)'),
    _a('minimize_kodi', S.SYS_MINIMISE, DEFAULT_ICON, 'Minimize()'),
    _a('window_visualisation', S.SYS_VISUALISATION, 'DefaultAddonVisualization.png', 'ActivateWindow(Visualisation)'),
    _a('weather_next_location', S.SYS_WEATHER_NEXT, 'DefaultAddonWeather.png', 'Weather.LocationNext()'),
    _a('weather_refresh', S.SYS_WEATHER_REFRESH, 'DefaultAddonWeather.png', 'Weather.Refresh()'),
    _a('reload_skin', S.SYS_RELOAD_SKIN, 'DefaultAddonLookAndFeel.png', 'ReloadSkin()'),
    _a('restart_kodi', S.SYS_RESTART, 'DefaultAddonService.png', 'RestartApp()', confirm=S.CONFIRM_RESTART),
    _a('window_screen_calibration', S.SYS_SCREEN_CAL, DEFAULT_ICON, 'ActivateWindow(ScreenCalibration)'),
    _a('window_settings', S.SYS_SETTINGS, 'DefaultAddonService.png', 'ActivateWindow(Settings)'),
    _a('window_shutdown_menu', S.SYS_SHUTDOWN, DEFAULT_ICON, 'ActivateWindow(ShutdownMenu)', confirm=S.CONFIRM_SHUTDOWN),
    _a('toggle_fullscreen', S.SYS_FULLSCREEN, DEFAULT_ICON, 'Action(togglefullscreen)'),
    _a('update_addon_repos', S.SYS_UPDATE_REPOS, 'DefaultAddonRepository.png', 'UpdateAddonRepos()'),
]


def label(entry):
    """Localised display name of a system action."""
    return tr(entry['name'])


def confirm_text(entry):
    """Localised confirmation prompt for an entry, or '' if it needs none."""
    return tr(entry['confirm']) if entry.get('confirm') else ''
