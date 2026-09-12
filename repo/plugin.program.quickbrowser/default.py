# -*- coding: utf-8 -*-
"""
plugin.program.quickbrowser

Launches a configured website fullscreen in Chrome (kiosk mode) and
lets you drive the real Windows mouse cursor using Kodi's remote
directional buttons - e.g. the official Kodi Remote app on iPhone.

Windows only. See README.md for setup notes and known limitations.
"""

import ctypes
import os
import subprocess
import sys

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.controlwindow import MouseControlWindow
from resources.lib import soundtoggle
from resources.lib import fullscreentoggle
from resources.lib import navdepthserver

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')

# A dedicated, isolated Chrome profile for this addon's kiosk
# sessions, entirely separate from the user's own regular Chrome
# profile. Confirmed necessary from a real device: without this,
# Chrome merges a --kiosk launch into an already-running Chrome
# window for the same profile (standard Chrome behaviour when a
# window is already open), meaning the "kiosk session" was never
# actually isolated - the navigation-tracking extension's listeners
# fire for ANY tab in the profile, not just the kiosk one, so
# ordinary browsing in other tabs was contaminating the depth
# counter and potentially causing chrome.tabs.goBack() to target the
# wrong tab entirely. --user-data-dir gives every launch its own
# separate Chrome instance, guaranteed, regardless of whether the
# user's regular Chrome is already open.
#
# Lives under this addon's Kodi profile/addon_data folder (persists
# across addon updates - the addon's own install folder does not,
# it gets replaced wholesale on every update), not the addon's
# install directory.
CHROME_PROFILE_DIR = os.path.join(
    xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), 'chrome_profile'
)

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
    toggle_fullscreen_window = ADDON.getSettingBool('toggle_fullscreen_window')
    use_real_navigation_tracking = ADDON.getSettingBool('use_real_navigation_tracking')

    return (
        chrome_path,
        step_size,
        launch_wait_ms,
        max_speed_multiplier,
        scroll_notches,
        silence_ui_sounds,
        toggle_fullscreen_window,
        use_real_navigation_tracking,
    )


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
    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)

    args = [
        chrome_path,
        '--user-data-dir={}'.format(CHROME_PROFILE_DIR),
        # Suppress Chrome's normal first-run experience (sign-in
        # prompt, "set as default browser" prompt, etc.) that a
        # brand-new, never-used profile would otherwise show -
        # standard practice for kiosk deployments, confirmed via
        # multiple real-world kiosk setup guides during research.
        '--no-first-run',
        '--no-default-browser-check',
        '--kiosk',
        url,
    ]

    xbmc.log(
        '[plugin.program.quickbrowser] Launching: {}'.format(' '.join(args)),
        xbmc.LOGINFO,
    )
    try:
        return subprocess.Popen(args)
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


def show_setup_info():
    """
    Shows the exact, resolved paths needed for the one-time manual
    Chrome extension setup (see README.md) - these vary by install
    (drive letter, Kodi portable vs installed, etc.) and can't be
    given as fixed instructions. Triggered via a settings.xml action
    button (RunScript(plugin.program.quickbrowser, show_setup_info)),
    not part of the normal launch flow.

    See create_desktop_shortcuts() below for a much less error-prone
    alternative to typing/copying these paths off a Kodi dialog by
    hand - confirmed as a real, repeated source of friction (a long
    path retyped from a TV screen into Command Prompt, and a Chrome
    folder-picker dialog that rejected a correctly-typed folder name
    until it was entered rather than just highlighted). This dialog
    is kept as a fallback for anyone who'd rather see the raw paths
    or can't run the shortcuts for some reason.
    """
    chrome_path_setting = ADDON.getSetting('chrome_path').strip()
    chrome_path = resolve_chrome_path(chrome_path_setting)
    if chrome_path is None:
        chrome_path = '<Chrome not found - set the correct path in settings first>'

    extension_path = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'chrome_extension')
    readme_path = os.path.join(ADDON.getAddonInfo('path'), 'README.md')
    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    command = '"{}" --user-data-dir="{}"'.format(chrome_path, CHROME_PROFILE_DIR)

    message = (
        'EASIER OPTION: Settings -> Setup -> "Create desktop shortcuts" '
        'creates a set of files on your Desktop that avoid typing or '
        'copying these paths by hand at all - see the README for the '
        'exact steps. The instructions here are the manual fallback.\n\n'
        'Full setup instructions and details: see\n{}\n\n'
        'One-time Chrome extension setup (needed for accurate Back navigation):\n\n'
        '1. Open Command Prompt\n\n'
        '2. Paste this exact command and press Enter - it opens a normal '
        'Chrome window using this addon\'s own isolated profile, not your '
        'regular Chrome profile:\n\n'
        '{}\n\n'
        '3. In that window, go to chrome://extensions\n\n'
        '4. Turn on Developer mode (top right)\n\n'
        '5. Click "Load unpacked" and select this folder:\n\n'
        '{}\n\n'
        'This only needs doing once. If Chrome or this addon is ever '
        'reinstalled, or the profile folder above is deleted, it needs '
        'redoing.'
    ).format(readme_path, command, extension_path)

    xbmcgui.Dialog().textviewer('{} - Setup Instructions'.format(ADDON_NAME), message)


# The actual, physical file-system folder for the desktop - NOT to be
# confused with CSIDL_DESKTOP (0), which is a virtual shell-namespace
# concept, not a real path suitable for saving a file into. Verified
# against a real, widely-used Python package (platformdirs) rather
# than a less careful example that conflated the two.
_CSIDL_DESKTOPDIRECTORY = 0x0010


def _get_desktop_path():
    """
    Resolves the real Desktop folder via the Windows Shell API rather
    than assuming %USERPROFILE%\\Desktop - that guess can be wrong on
    systems where OneDrive (or Group Policy) redirects the Desktop
    folder elsewhere. Returns None if the call fails for any reason.
    """
    try:
        buf = ctypes.create_unicode_buffer(260)  # MAX_PATH
        result = ctypes.windll.shell32.SHGetFolderPathW(
            None, _CSIDL_DESKTOPDIRECTORY, None, 0, buf
        )
        if result != 0:  # S_OK is 0; anything else is a failure HRESULT
            xbmc.log(
                '[plugin.program.quickbrowser] SHGetFolderPathW failed with code {}'.format(
                    result
                ),
                xbmc.LOGWARNING,
            )
            return None
        if not buf.value:
            # Defensive: a success code (0) with an empty path has
            # never actually been observed, but treating this as
            # success would mean os.path.join('', filename) silently
            # produces a bare relative filename instead of a real
            # Desktop path - the shortcuts would land wherever Kodi's
            # current working directory happens to be, with no error
            # shown at all. Fail loudly instead.
            xbmc.log(
                '[plugin.program.quickbrowser] SHGetFolderPathW reported success '
                'but returned an empty path',
                xbmc.LOGWARNING,
            )
            return None
        return buf.value
    except OSError as exc:
        xbmc.log(
            '[plugin.program.quickbrowser] Could not resolve Desktop path: {}'.format(exc),
            xbmc.LOGWARNING,
        )
        return None


def create_desktop_shortcuts():
    """
    Writes shortcuts to the Desktop with the exact resolved paths
    already baked in - confirmed as a real, repeated source of
    friction otherwise: a long path has to be read off a Kodi dialog
    on a TV screen and retyped exactly, with no clipboard bridging
    the two screens, into either Command Prompt or a Chrome
    folder-picker dialog that's proven finicky about how a folder is
    selected.

    Not a genuine Windows .lnk shortcut - that requires COM
    (IShellLink), which needs pywin32, not guaranteed to be bundled
    with Kodi's Python (the same reason mouserelay.py uses plain
    ctypes throughout rather than pywin32). A .bat file achieves the
    same practical outcome (double-click to run a specific command)
    using only the standard library.

    - "Quick Browser - Open Chrome Profile.bat": launches Chrome with
      --user-data-dir already set to this addon's isolated profile -
      no command to type or copy.
    - "Quick Browser - Extension Folder Path.txt" +
      "Quick Browser - Open Extension Folder Path.bat": the path
      itself is written to the .txt file once, here, with clean
      content (no trailing newline to accidentally select and paste
      along with it) - the .bat file just opens that .txt in Notepad,
      ready for Ctrl+A, Ctrl+C, then Ctrl+V directly into Chrome's
      "Load unpacked" folder-picker's own path field. This sidesteps
      that dialog's folder-tree navigation entirely, which is exactly
      the interaction that produced a real "folder name is not valid"
      error during testing.
    """
    desktop_path = _get_desktop_path()
    if desktop_path is None:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Could not find your Desktop folder - see kodi.log for details',
            xbmcgui.NOTIFICATION_ERROR,
        )
        return

    chrome_path_setting = ADDON.getSetting('chrome_path').strip()
    chrome_path = resolve_chrome_path(chrome_path_setting)
    if chrome_path is None:
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Chrome not found - set the correct path in addon settings first',
            xbmcgui.NOTIFICATION_ERROR,
        )
        return

    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    extension_path = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'chrome_extension')

    profile_bat_path = os.path.join(desktop_path, 'Quick Browser - Open Chrome Profile.bat')
    profile_bat_content = (
        '@echo off\r\n'
        'start "" "{}" --user-data-dir="{}"\r\n'
    ).format(chrome_path, CHROME_PROFILE_DIR)

    # Written once, directly, with exactly the path and nothing else -
    # no trailing newline, so selecting all of Notepad's content
    # (Ctrl+A) copies only the path itself, cleanly.
    path_txt_path = os.path.join(desktop_path, 'Quick Browser - Extension Folder Path.txt')
    path_txt_content = extension_path

    folder_bat_path = os.path.join(
        desktop_path, 'Quick Browser - Open Extension Folder Path.bat'
    )
    folder_bat_content = (
        '@echo off\r\n'
        'start "" notepad.exe "{}"\r\n'
    ).format(path_txt_path)

    try:
        with open(profile_bat_path, 'w') as f:
            f.write(profile_bat_content)
        with open(path_txt_path, 'w') as f:
            f.write(path_txt_content)
        with open(folder_bat_path, 'w') as f:
            f.write(folder_bat_content)
    except OSError as exc:
        xbmc.log(
            '[plugin.program.quickbrowser] Could not write desktop shortcuts: {}'.format(exc),
            xbmc.LOGERROR,
        )
        xbmcgui.Dialog().notification(
            ADDON_NAME, 'Could not create shortcuts - see kodi.log for details',
            xbmcgui.NOTIFICATION_ERROR,
        )
        return

    xbmcgui.Dialog().ok(
        '{} - Shortcuts Created'.format(ADDON_NAME),
        'Added to your Desktop:\n\n'
        '- "Quick Browser - Open Chrome Profile" - opens Chrome using '
        "this addon's isolated profile\n\n"
        '- "Quick Browser - Open Extension Folder Path" - opens a '
        'text file containing just the extension folder path, ready '
        'to Ctrl+A, Ctrl+C, then Ctrl+V into Chrome\'s "Load unpacked" '
        'dialog\n\n'
        'Use the profile shortcut first, then in that Chrome window go '
        'to chrome://extensions, turn on Developer mode, click '
        '"Load unpacked", paste the copied path into the dialog\'s own '
        'path field, and confirm.'
    )


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
    (
        chrome_path_setting,
        step_size,
        launch_wait_ms,
        max_speed_multiplier,
        scroll_notches,
        silence_ui_sounds,
        toggle_fullscreen_window,
        use_real_navigation_tracking,
    ) = get_settings()

    sites = get_sites()
    if not sites:
        xbmcgui.Dialog().notification(
            ADDON_NAME, 'No websites configured - check addon settings', xbmcgui.NOTIFICATION_ERROR
        )
        return

    url = choose_site(sites)
    if url is None:
        return

    # Switched before Chrome even launches (not just before the
    # mouse-control window) so Kodi has already relinquished true
    # exclusive fullscreen by the time Chrome tries to claim the
    # screen. Wraps the ENTIRE rest of this function, including the
    # early-return failure paths below, so it's always restored no
    # matter how this session ends.
    original_fakefullscreen = (
        fullscreentoggle.enable_fullscreen_window() if toggle_fullscreen_window else None
    )
    try:
        chrome_path = resolve_chrome_path(chrome_path_setting)
        if chrome_path is None:
            xbmcgui.Dialog().notification(
                ADDON_NAME,
                'Chrome not found - set the correct path in addon settings',
                xbmcgui.NOTIFICATION_ERROR,
            )
            return

        # Started before Chrome launches so the extension can report
        # as soon as it loads. If the setting is off, or the server
        # can't bind its port, nav_server stays None and
        # MouseControlWindow falls back to its own click-counting
        # depth logic entirely - this must never be the only way Back
        # can work.
        #
        # NOTE: this no longer passes --load-extension. Confirmed via
        # a real device test (extension didn't appear in
        # chrome://extensions at all, even without --kiosk) and
        # Google's own official announcement: Chrome removed
        # --load-extension support from official/branded builds
        # starting at Chrome 137 - the flag is now silently ignored,
        # logged only at a verbosity level Kodi's log doesn't capture
        # ("--load-extension is not allowed in Google Chrome,
        # ignoring"). The extension must instead be loaded ONCE
        # manually via chrome://extensions -> Developer mode ->
        # "Load unpacked" (see README), into this addon's own isolated
        # Chrome profile (CHROME_PROFILE_DIR above). Confirmed on a
        # real device across multiple sessions: it does persist there
        # and does report correctly on subsequent --kiosk launches
        # without needing to be redone.
        nav_server = None
        if use_real_navigation_tracking:
            candidate_server = navdepthserver.NavDepthServer()
            if candidate_server.start():
                nav_server = candidate_server

        try:
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
                        nav_depth_server=nav_server,
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
        finally:
            if nav_server is not None:
                nav_server.stop()
    finally:
        if toggle_fullscreen_window:
            fullscreentoggle.restore(original_fakefullscreen)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'show_setup_info':
        show_setup_info()
    elif len(sys.argv) > 1 and sys.argv[1] == 'create_desktop_shortcuts':
        create_desktop_shortcuts()
    else:
        main()
