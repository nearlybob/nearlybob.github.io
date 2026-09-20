# -*- coding: utf-8 -*-
"""The user's Shortcuts: named links to a page or action inside an addon.

Stored in the profile folder (shortcuts.json) so they survive addon updates.
Each entry is {'name', 'icon', 'action'}; 'action' is a Kodi built-in string.
Identity is (name, action) - see shortcut_key().
"""
import os
import re
import xml.etree.ElementTree as ET

import xbmc
import xbmcvfs

from . import addons, order, store
from .common import log

SHORTCUTS_FILE = 'shortcuts.json'

# --- which addon does an action target? (used to hide shortcuts whose addon is gone)
_ID = r'[A-Za-z0-9_.\-]+'
_END = r'(?=[\s"\',)/?#]|$)'   # id must end at a delimiter (so 'special://' isn't read as id 'special')
_ADDON_ID_PATTERNS = [
    re.compile(r'Addon\.OpenSettings\(\s*[\'"]?(' + _ID + r')' + _END, re.I),
    re.compile(r'RunAddon\(\s*[\'"]?(' + _ID + r')' + _END, re.I),
    re.compile(r'RunScript\(\s*[\'"]?(' + _ID + r')' + _END, re.I),
    re.compile(r'plugin://(' + _ID + r')' + _END, re.I),
]


def extract_addon_id(action):
    """The addon id an action targets - Addon.OpenSettings(id), RunAddon(id[,...]),
    RunScript(id[,...]) or any plugin://id... URL (quoted or not). None when the action
    doesn't reference a specific addon, so there is nothing to validate."""
    for pattern in _ADDON_ID_PATTERNS:
        match = pattern.search(action or '')
        if match:
            found = match.group(1)
            if found.lower().endswith('.py'):
                return None  # RunScript(myscript.py) is a file, not an addon
            return found
    return None


def filter_valid(entries, known_ids=()):
    """Entries whose target addon (if any) is installed and enabled. ``known_ids``
    are addon ids already known to be enabled, to avoid an extra JSON-RPC call."""
    enabled = None
    valid = []
    for entry in entries:
        addon_id = extract_addon_id(entry.get('action', ''))
        if addon_id is None or addon_id in known_ids:
            valid.append(entry)
            continue
        if enabled is None:
            enabled = addons.enabled_ids()
        if addon_id in enabled:
            valid.append(entry)
    return valid


def is_valid(entry, enabled_ids):
    addon_id = extract_addon_id(entry.get('action', ''))
    return addon_id is None or addon_id in enabled_ids


def shortcut_key(entry):
    """Stable identity of a shortcut: name + action (two shortcuts may share a
    name, or an action, but not both - duplicates are refused)."""
    return '{}\x1f{}'.format(entry.get('name', ''), entry.get('action', ''))


# --- storage
def load_shortcuts():
    """Clean list of shortcut dicts (malformed entries and exact duplicates dropped)."""
    seen = set()
    cleaned = []
    for raw in store.load(SHORTCUTS_FILE, []):
        if not isinstance(raw, dict):
            continue
        action = raw.get('action')
        if not isinstance(action, str) or not action.strip():
            continue
        entry = dict(raw)
        name = raw.get('name')
        entry['name'] = name if isinstance(name, str) and name else action
        icon = raw.get('icon')
        entry['icon'] = icon if isinstance(icon, str) else ''
        key = (entry['name'], action)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(entry)
    return cleaned


def save_shortcuts(shortcuts):
    store.save(SHORTCUTS_FILE, shortcuts)


def add_shortcut(name, icon, action):
    """True if added, False if an identical (name, action) shortcut already exists."""
    shortcuts = load_shortcuts()
    if any(e['name'] == name and e['action'] == action for e in shortcuts):
        return False
    shortcuts.append({'name': name, 'icon': icon or '', 'action': action})
    save_shortcuts(shortcuts)
    return True


def update_shortcut(old_key, name=None, icon=None, action=None):
    """Edit a shortcut. Returns (new_key, 'ok') | (None, 'missing') | (None, 'duplicate')."""
    shortcuts = load_shortcuts()
    for index, entry in enumerate(shortcuts):
        if shortcut_key(entry) == old_key:
            break
    else:
        return None, 'missing'
    updated = dict(entry)
    if name is not None:
        updated['name'] = name
    if icon is not None:
        updated['icon'] = icon
    if action is not None:
        updated['action'] = action
    new_key = shortcut_key(updated)
    if new_key != old_key and any(shortcut_key(e) == new_key for e in shortcuts):
        return None, 'duplicate'
    shortcuts[index] = updated
    save_shortcuts(shortcuts)
    if new_key != old_key:
        order.replace_id(order.SHORTCUTS_KEY, old_key, new_key)
    return new_key, 'ok'


def remove_shortcuts(keys):
    """Remove shortcuts by key (not index, so it can't hit the wrong one)."""
    keys = set(keys)
    shortcuts = load_shortcuts()
    remaining = [e for e in shortcuts if shortcut_key(e) not in keys]
    if len(remaining) != len(shortcuts):
        save_shortcuts(remaining)
    for key in keys:
        order.discard_id(order.SHORTCUTS_KEY, key)
    return len(shortcuts) - len(remaining)


def replace_all(entries):
    save_shortcuts([e for e in entries if isinstance(e, dict)])


# --- Kodi Favourites
def read_favourites():
    """[{'name', 'icon', 'action'}] from the current profile's favourites.xml.
    Each <favourite>'s text is already a ready-to-run built-in."""
    path = xbmcvfs.translatePath('special://profile/favourites.xml')
    if not os.path.isfile(path):
        return []
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        log('could not read favourites.xml: {}'.format(exc), xbmc.LOGWARNING)
        return []
    favourites = []
    for element in root.iter('favourite'):
        action = (element.text or '').strip()
        if action:
            favourites.append({'name': element.get('name') or action,
                               'icon': element.get('thumb') or '',
                               'action': action})
    return favourites
