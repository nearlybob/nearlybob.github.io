# -*- coding: utf-8 -*-
"""Drill into an installed addon's own menus and pick any page or item as a
shortcut target (like Nimbus's widget picker).

Uses Files.GetDirectory. Back goes up one level (and leaves the browse from the
top level); a spinner shows while an addon builds a page.
"""
import xbmcgui

from . import addons
from .common import busy, notify, tr
from .strings import S


def _get_directory(url):
    """Files in a plugin:// directory as [{'file','filetype','label'}], or None on
    error (e.g. the addon raised while building a page that needs extra context)."""
    with busy():
        result = addons.rpc('Files.GetDirectory', {'directory': url, 'media': 'files'})
    if result is None:
        return None
    return result.get('files', []) or []


def browse_and_pick(addon):
    """``addon``: a dict from addons.browsable(). Returns None if cancelled, else
    {'label': str, 'url': str, 'is_folder': bool}."""
    stack = []  # parents: [(url, label), ...]
    url = 'plugin://{}/'.format(addon['addonid'])
    label = addon['name']

    while True:
        listing = _get_directory(url)
        if listing is None:
            notify(tr(S.COULD_NOT_BROWSE), xbmcgui.NOTIFICATION_ERROR)
            if not stack:
                return None
            url, label = stack.pop()
            continue

        trail = ' > '.join([l for _, l in stack] + [label])
        options = [tr(S.USE_THIS_PAGE).format(label)] + [f.get('label', '') for f in listing]
        choice = xbmcgui.Dialog().select(trail, options)
        if choice < 0:
            if not stack:
                return None
            url, label = stack.pop()  # Back: up one level
            continue
        if choice == 0:
            return {'label': label, 'url': url, 'is_folder': True}

        entry = listing[choice - 1]
        if entry.get('filetype') == 'directory':
            stack.append((url, label))
            url = entry.get('file')
            label = entry.get('label') or label
        else:
            return {'label': entry.get('label') or label, 'url': entry.get('file'),
                    'is_folder': False}
