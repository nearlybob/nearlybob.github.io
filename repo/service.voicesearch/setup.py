# -*- coding: utf-8 -*-
"""
Kodi Program addon entry point.

Two ways this gets invoked:
  - RunScript(service.voicesearch,mode=help) -- from the Help button
    in this addon's Settings screen. Shows resources/help.txt in
    Kodi's native text viewer. See show_help() below.
  - RunScript(service.voicesearch) with no arguments -- manually
    re-runs the Windows setup .bat. This is NOT required for normal
    use -- the background service (service.py) already runs setup
    automatically the first time it can't find Python. This exists
    only as a troubleshooting fallback: e.g. if automatic setup
    failed once and gave up (see setup_failed.flag), running this
    clears that flag and tries again, with a visible console window
    so you can see exactly what happens.

IMPORTANT: the setup path only fixes the underlying Python/package
setup -- it does NOT itself start the watcher. service.py's startup
logic (which launches the watcher) runs exactly once, at Kodi
startup, not in a loop watching for retries. So after this finishes
successfully, Kodi must be restarted for voice search to actually
start.
"""

import os
import subprocess
import sys

import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
BAT_PATH = os.path.join(ADDON_PATH, "resources", "setup_kodi_voice_search.bat")
FAILED_FLAG = os.path.join(PROFILE_PATH, "setup_failed.flag")
HELP_PATH = os.path.join(ADDON_PATH, "resources", "help.txt")


def show_help():
    """Invoked via the Settings screen's Help button:
    RunScript(service.voicesearch,mode=help). Shows help.txt in Kodi's
    native scrollable read-only text viewer."""
    if not xbmcvfs.exists(HELP_PATH):
        xbmcgui.Dialog().ok("Kodi Voice Search Help", "Help file not found.")
        return
    with open(HELP_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    xbmcgui.Dialog().textviewer("Kodi Voice Search - Help", text)


def main():
    # RunScript(service.voicesearch,mode=help) from the Settings
    # screen's Help button routes here instead of the setup flow below.
    if len(sys.argv) > 1 and sys.argv[1] == "mode=help":
        show_help()
        return

    dialog = xbmcgui.Dialog()

    if not xbmcvfs.exists(BAT_PATH):
        dialog.ok(
            "Kodi Voice Search Setup",
            f"Setup file not found:\n{BAT_PATH}\n\nReinstall this addon.",
        )
        return

    proceed = dialog.yesno(
        "Kodi Voice Search Setup",
        "The background service normally installs everything it needs "
        "automatically on first startup -- you shouldn't normally need "
        "this.\n\n"
        "This opens a visible Command Prompt window and (re-)installs "
        "Python and the required packages, for troubleshooting.\n\n"
        "IMPORTANT: this only fixes the underlying Python setup -- it "
        "does not itself start voice search. Once the window finishes "
        "successfully, restart Kodi for voice search to actually start "
        "(the background service that starts it only runs once, at "
        "Kodi startup).\n\n"
        "Continue?",
    )
    if not proceed:
        return

    if xbmcvfs.exists(FAILED_FLAG):
        try:
            os.remove(FAILED_FLAG)
        except OSError:
            pass

    # Same fix as service.py -- shell=True on Windows already adds its
    # own outer "cmd /c "..."" wrapping, so plain single-layer quoting
    # here is correct (an extra layer on top, tried in 1.3.2, breaks
    # parsing instead of fixing it).
    #
    # PROFILE_PATH is passed here (as "interactive", not "silent") so
    # the .bat still writes python_path.txt when run manually -- that
    # write is NOT gated behind silent mode (see the .bat's Step 4),
    # but it still needs the directory to write to.
    command = f'"{BAT_PATH}" interactive "{PROFILE_PATH}"'

    try:
        subprocess.Popen(
            command,
            shell=True,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    except Exception as e:
        dialog.ok("Kodi Voice Search Setup", f"Failed to launch setup:\n{e}")
        return

    dialog.notification(
        "Kodi Voice Search",
        "Setup window opened. When it finishes, restart Kodi.",
        xbmcgui.NOTIFICATION_INFO,
        8000,
    )


if __name__ == "__main__":
    main()

