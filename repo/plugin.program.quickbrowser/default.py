# -*- coding: utf-8 -*-
"""
plugin.program.quickbrowser

Launches a configured website fullscreen in Chrome (kiosk mode) and
lets you drive the real Windows mouse cursor using Kodi's remote
directional buttons - e.g. the official Kodi Remote app on iPhone.

Windows only. See README.md for setup notes and known limitations.
"""

import os
import subprocess

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.controlwindow import MouseControlWindow
from resources.lib import soundtoggle

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')

# Kodi can run more than one invocation of a script addon
# concurrently (e.g. the menu item triggered twice in quick
# succession). Without a guard, a second run would open a second
# invisible WindowDialog and a second Chrome process; Kodi only
# routes onAction() to the newest/topmost dialog, so the FIRST run's
# window and Chrome process would be orphaned - running invisibly,
# uncontrollable, with no way to close them via remote input at all.
# A property on the Home window (ID 10000) is a standard Kodi pattern
# for a session-wide flag readable/writable from any script
# invocation, since it persists independently of which invocation
# set it.
RUNNING_PROPERTY = 'plugin.program.quickbrowser.running'

# Common install locations, checked in order if the configured path
# doesn't exist. Covers the "Program Files" vs "Program Files (x86)"
# split we hit in testing, plus a common per-user install location.
FALLBACK_CHROME_PATHS = [
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
]


def get_sites():
    """
    Build the list of configured sites from the site1..site5
    name/url setting pairs. A slot counts as configured only if both
    its name and URL are non-empty and neither is the literal
    "(unused)" placeholder - Kodi's CSettingString rejects a truly
    empty or whitespace-only <default> (confirmed from a device log:
    "error reading the default value of ..." for every blank slot,
    which silently dropped those settings from the screen entirely),
    so the unused slots ship with a real placeholder default instead.
    Returns a list of (name, url) tuples in slot order.
    """
    UNUSED_PLACEHOLDER = '(unused)'
    sites = []
    for i in range(1, 6):
        name = ADDON.getSetting('site{}_name'.format(i)).strip()
        url = ADDON.getSetting('site{}_url'.format(i)).strip()
        if name and url and name != UNUSED_PLACEHOLDER and url != UNUSED_PLACEHOLDER:
            sites.append((name, url))
    return sites


def get_settings():
    chrome_path = ADDON.getSetting('chrome_path').strip()

    try:
        step_size = int(ADDON.getSetting('step_size'))
    except (TypeError, ValueError):
        step_size = 5

    try:
        launch_wait_ms = int(ADDON.getSetting('launch_wait_ms'))
    except (TypeError, ValueError):
        launch_wait_ms = 2000

    try:
        max_speed_multiplier = int(ADDON.getSetting('max_speed_multiplier'))
    except (TypeError, ValueError):
        max_speed_multiplier = 10

    try:
        scroll_notches = int(ADDON.getSetting('scroll_notches'))
    except (TypeError, ValueError):
        scroll_notches = 2

    silence_ui_sounds = ADDON.getSettingBool('silence_ui_sounds')

    return chrome_path, step_size, launch_wait_ms, max_speed_multiplier, scroll_notches, silence_ui_sounds


def resolve_chrome_path(configured_path):
    """
    Use the configured path if it exists; otherwise try known common
    install locations, logging what happened either way. Returns None
    if nothing is found.
    """
    if configured_path and os.path.isfile(configured_path):
        return configured_path

    if configured_path:
        xbmc.log(
            '[plugin.program.quickbrowser] Configured Chrome path not found: {} - trying fallbacks'.format(
                configured_path
            ),
            xbmc.LOGWARNING,
        )

    for candidate in FALLBACK_CHROME_PATHS:
        if os.path.isfile(candidate):
            xbmc.log(
                '[plugin.program.quickbrowser] Using auto-detected Chrome path: {}'.format(
                    candidate
                ),
                xbmc.LOGINFO,
            )
            return candidate

    return None


def launch_chrome(chrome_path, url):
    xbmc.log(
        '[plugin.program.quickbrowser] Launching: {} --kiosk {}'.format(
            chrome_path, url
        ),
        xbmc.LOGINFO,
    )
    try:
        return subprocess.Popen([chrome_path, '--kiosk', url])
    except OSError as exc:
        xbmc.log(
            '[plugin.program.quickbrowser] Failed to launch Chrome: {}'.format(exc),
            xbmc.LOGERROR,
        )
        return None


def choose_site(sites):
    """
    Show a native Kodi selection menu of configured site names.
    Returns the chosen URL, or None if the user cancelled (Back/Esc).
    Always shows the menu, even for a single configured site, per
    the requested behaviour.
    """
    names = [name for name, _url in sites]
    index = xbmcgui.Dialog().select(ADDON_NAME, names)
    if index == -1:
        xbmc.log(
            '[plugin.program.quickbrowser] Site selection cancelled',
            xbmc.LOGINFO,
        )
        return None
    return sites[index][1]


def main():
    home_window = xbmcgui.Window(10000)
    if home_window.getProperty(RUNNING_PROPERTY) == 'true':
        xbmc.log(
            '[plugin.program.quickbrowser] Already running - refusing second concurrent instance',
            xbmc.LOGINFO,
        )
        xbmcgui.Dialog().notification(
            ADDON_NAME, 'Quick Browser is already running', xbmcgui.NOTIFICATION_WARNING
        )
        return

    home_window.setProperty(RUNNING_PROPERTY, 'true')
    try:
        _run()
    finally:
        # Always clear, even if something above raised - otherwise a
        # crash would permanently lock out every future run until
        # Kodi restarts.
        home_window.clearProperty(RUNNING_PROPERTY)


def _run():
    chrome_path_setting, step_size, launch_wait_ms, max_speed_multiplier, scroll_notches, silence_ui_sounds = get_settings()

    sites = get_sites()
    if not sites:
        xbmcgui.Dialog().notification(
            ADDON_NAME, 'No websites configured - check addon settings', xbmcgui.NOTIFICATION_ERROR
        )
        return

    url = choose_site(sites)
    if url is None:
        return

    chrome_path = resolve_chrome_path(chrome_path_setting)
    if chrome_path is None:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Chrome not found - set the correct path in addon settings',
            xbmcgui.NOTIFICATION_ERROR,
        )
        return

    process = launch_chrome(chrome_path, url)
    if process is None:
        xbmcgui.Dialog().notification(
            ADDON_NAME, 'Could not launch Chrome - see kodi.log for details',
            xbmcgui.NOTIFICATION_ERROR,
        )
        return

    # Give Chrome time to actually open fullscreen before we start
    # relaying input, otherwise early presses have nothing to act on.
    xbmc.sleep(launch_wait_ms)

    original_soundskin = soundtoggle.silence() if silence_ui_sounds else None
    try:
        try:
            window = MouseControlWindow(
                step_size=step_size,
                chrome_process=process,
                max_speed_multiplier=max_speed_multiplier,
                scroll_notches=scroll_notches,
            )
            window.doModal()
            del window
        finally:
            # Safety net: guaranteed to run whether doModal() returned
            # normally or something above raised - otherwise a crash
            # during window setup would leave Chrome running
            # fullscreen with no way to control or close it. Wrapped
            # defensively since Windows-specific behaviour of
            # terminate() on an already-exited process handle hasn't
            # been directly verified - this must never itself raise
            # during cleanup.
            try:
                if process.poll() is None:
                    process.terminate()
            except OSError as exc:
                xbmc.log(
                    '[plugin.program.quickbrowser] process.terminate() raised during cleanup: {}'.format(exc),
                    xbmc.LOGWARNING,
                )
    finally:
        # Always restore, even if something above raised - otherwise
        # a crash would leave the user's Kodi permanently silent.
        if silence_ui_sounds:
            soundtoggle.restore(original_soundskin)


if __name__ == '__main__':
    main()
