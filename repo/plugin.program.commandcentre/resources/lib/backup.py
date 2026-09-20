# -*- coding: utf-8 -*-
"""Back up, restore and reset Command Centre's configuration."""
import json
import os

import xbmcgui
import xbmcvfs

from . import order, overrides, shortcuts, state, visibility
from .common import ADDON, DEFAULT_NAV_COLOR, get_nav_color, log_exception, normalize_color, notify, tr
from .strings import S

BACKUP_NAME = 'commandcentre_backup.json'
BACKUP_FORMAT = 1


def collect():
    return {
        'format': BACKUP_FORMAT,
        'addon_version': ADDON.getAddonInfo('version'),
        'shortcuts': shortcuts.load_shortcuts(),
        'hidden': visibility.export(),
        'order': order.export(),
        'overrides': overrides.export(),
        'nav_highlight_color': get_nav_color(),
    }


def is_valid_backup(data):
    if not isinstance(data, dict) or data.get('format') != BACKUP_FORMAT:
        return False
    if not isinstance(data.get('shortcuts'), list) or not isinstance(data.get('hidden'), dict) \
            or not isinstance(data.get('order'), dict):
        return False
    if 'overrides' in data and not isinstance(data['overrides'], dict):   # absent in backups from before addon renaming
        return False
    return all(isinstance(e, dict) and isinstance(e.get('action'), str) for e in data['shortcuts'])


def apply(data):
    shortcuts.replace_all(data['shortcuts'])
    visibility.replace_all(data['hidden'])
    order.replace_all(data['order'])
    overrides.replace_all(data.get('overrides', {}))
    ADDON.setSetting('nav_highlight_color',
                     normalize_color(data.get('nav_highlight_color')) or DEFAULT_NAV_COLOR)


def export_backup():
    folder = xbmcgui.Dialog().browseSingle(3, tr(S.BK_CHOOSE_FOLDER), 'files')
    if not folder:
        return
    target = folder.rstrip('/\\') + ('/' if '://' in folder else os.sep) + BACKUP_NAME
    if xbmcvfs.exists(target) and not xbmcgui.Dialog().yesno(tr(S.BACKUP_TITLE), tr(S.BK_OVERWRITE)):
        return
    payload = bytearray(json.dumps(collect(), indent=2, ensure_ascii=False).encode('utf-8'))
    handle = xbmcvfs.File(target, 'w')
    try:
        ok = handle.write(payload)
    finally:
        handle.close()
    notify(tr(S.BK_SAVED) if ok else tr(S.BK_FAILED),
           xbmcgui.NOTIFICATION_INFO if ok else xbmcgui.NOTIFICATION_ERROR)


def import_backup():
    path = xbmcgui.Dialog().browseSingle(1, tr(S.BK_CHOOSE_FILE), 'files', '.json')
    if not path or not path.lower().endswith('.json'):
        return
    try:
        handle = xbmcvfs.File(path)
        try:
            raw = bytes(handle.readBytes())
        finally:
            handle.close()
        data = json.loads(raw.decode('utf-8-sig'))
    except Exception:
        log_exception('reading backup')
        data = None
    if not is_valid_backup(data):
        notify(tr(S.BK_INVALID), xbmcgui.NOTIFICATION_ERROR)
        return
    if not xbmcgui.Dialog().yesno(tr(S.BACKUP_TITLE), tr(S.BK_CONFIRM_RESTORE)):
        return
    apply(data)
    notify(tr(S.BK_RESTORED))


def reset_menu():
    options = [
        (tr(S.RESET_VISIBILITY), lambda: visibility.replace_all({})),
        (tr(S.RESET_ORDER), order.reset),
        (tr(S.RESET_COLOUR), lambda: ADDON.setSetting('nav_highlight_color', DEFAULT_NAV_COLOR)),
        (tr(S.RESET_OVERRIDES), overrides.reset),
        (tr(S.RESET_RECENT), state.clear_recent),
        (tr(S.RESET_SHORTCUTS), lambda: shortcuts.replace_all([])),
    ]
    choice = xbmcgui.Dialog().select(tr(S.RESET_TITLE), [label for label, _ in options])
    if choice < 0:
        return
    if not xbmcgui.Dialog().yesno(options[choice][0], tr(S.RESET_CONFIRM)):
        return
    options[choice][1]()
    notify(tr(S.RESET_DONE))
