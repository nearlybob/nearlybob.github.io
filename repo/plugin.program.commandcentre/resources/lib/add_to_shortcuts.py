# -*- coding: utf-8 -*-
"""Context-menu entry "Add to Command Centre shortcuts" for plugin:// items.

Doesn't change what the popup shows - it only adds a shortcut. Kodi passes the
item the menu was opened on as sys.listitem.
"""
import sys

import xbmc
import xbmcgui

from . import actions, addons, shortcuts
from .common import log_exception, notify, tr
from .strings import S


def _item_details():
    item = getattr(sys, 'listitem', None)
    if item is not None:
        path = item.getPath()
        label = item.getLabel()
        icon = item.getArt('icon') or item.getArt('thumb')
    else:
        path = xbmc.getInfoLabel('ListItem.FolderPath')
        label = xbmc.getInfoLabel('ListItem.Label')
        icon = xbmc.getInfoLabel('ListItem.Icon')
    return path, label, icon


def run():
    try:
        path, label, icon = _item_details()
        if not path or not path.lower().startswith('plugin://'):
            notify(tr(S.CTX_ADD_FAILED), xbmcgui.NOTIFICATION_ERROR)
            return

        if xbmc.getCondVisibility('ListItem.IsFolder'):
            window = addons.window_for(actions.plugin_addon_id(path)) or 'Videos'
            action = actions.open_folder(window, path)
        else:
            what = xbmcgui.Dialog().select(tr(S.PLAY_OR_RUN), [tr(S.OPT_PLAY), tr(S.OPT_RUN)])
            if what < 0:
                return
            action = actions.play(path) if what == 0 else actions.run_plugin(path)

        name = xbmcgui.Dialog().input(tr(S.SHORTCUT_LABEL), defaultt=label)
        if not name:
            return
        if shortcuts.add_shortcut(name, icon or '', action):
            notify(tr(S.SHORTCUT_ADDED))
        else:
            notify(tr(S.SHORTCUT_EXISTS))
    except Exception:
        log_exception('add to shortcuts')
        notify(tr(S.ERROR_GENERIC), xbmcgui.NOTIFICATION_ERROR)
