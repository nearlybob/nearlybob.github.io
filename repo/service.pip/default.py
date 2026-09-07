# -*- coding: utf-8 -*-
import sys

import xbmcgui

from resources.lib import pip_core


def _play_from_listitem():
    listitem = getattr(sys, "listitem", None)
    if listitem is None:
        xbmcgui.Dialog().notification("Picture in Picture", "No item selected")
        return
    pip_core.start_pip(listitem.getPath())


def _install_mpv_windows():
    from resources.lib import mpv_installer
    mpv_installer.install_mpv_windows()


def _download_mpv_android():
    from resources.lib import mpv_installer
    mpv_installer.open_android_download()


DISPATCH = {
    "play": _play_from_listitem,
    "nudge_up": lambda: pip_core.snap_direction("up"),
    "nudge_down": lambda: pip_core.snap_direction("down"),
    "nudge_left": lambda: pip_core.snap_direction("left"),
    "nudge_right": lambda: pip_core.snap_direction("right"),
    "grow": pip_core.grow,
    "shrink": pip_core.shrink,
    "swap": pip_core.swap,
    "swap_audio": pip_core.swap_audio,
    "close": pip_core.close_pip,
    "install_mpv": _install_mpv_windows,
    "download_mpv_android": _download_mpv_android,
}


def main():
    # Context menu items pass their `args` value as sys.argv[1] (Kodi v19+).
    # sys.listitem is set by Kodi whenever invoked from a context menu,
    # regardless of which item was clicked.
    action = sys.argv[1] if len(sys.argv) > 1 else None
    fn = DISPATCH.get(action)
    if fn:
        fn()
        return

    # No recognised args - e.g. launched bare from Program add-ons.
    xbmcgui.Dialog().notification("Picture in Picture", "Use the context menu on a supported video item")


if __name__ == "__main__":
    main()
