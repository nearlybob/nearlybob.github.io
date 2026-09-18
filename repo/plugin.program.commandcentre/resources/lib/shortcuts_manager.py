# -*- coding: utf-8 -*-
"""
Manages the user-defined "Shortcuts" list: named links to a specific
page or action inside an addon (e.g. "Red Light Picker - Settings"),
as distinct from the Video Addons / Program Addons sections, which
just launch an addon at its default entry point.

Stored as JSON in the addon's profile folder so it survives addon
updates. A starter example ships in resources/data/shortcuts.json
and is copied in on first run.
"""
import os
import json
import xbmc
import xbmcaddon
import xbmcvfs

import re

import addon_discovery

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo('path')
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

BUNDLED_CONFIG = os.path.join(ADDON_PATH, 'resources', 'data', 'shortcuts.json')
USER_CONFIG = os.path.join(PROFILE_PATH, 'shortcuts.json')
SCHEMA_MARKER = os.path.join(PROFILE_PATH, 'shortcuts_schema.txt')

# Bump this whenever the bundled starter shortcuts.json's meaning or
# content changes (e.g. v1.1.0 changed Shortcuts from "launch any
# addon" to "link to a specific page in an addon"). Without this,
# _ensure_user_config's "copy on first run only" logic would leave
# a profile that was first created under an older version stuck
# with that older starter content forever, even after this addon
# updates — which is exactly what happened: a profile first created
# under the original all-in-one shortcuts.json kept showing addon
# launchers and system commands under Shortcuts long after both got
# their own dedicated, auto-discovered sections.
SCHEMA_VERSION = '3'


def _ensure_user_config():
    if not xbmcvfs.exists(PROFILE_PATH):
        xbmcvfs.mkdirs(PROFILE_PATH)

    current_marker = None
    if xbmcvfs.exists(SCHEMA_MARKER):
        with open(SCHEMA_MARKER, 'r', encoding='utf-8') as f:
            current_marker = f.read().strip()

    needs_migration = not xbmcvfs.exists(USER_CONFIG) or current_marker != SCHEMA_VERSION
    if needs_migration:
        with open(BUNDLED_CONFIG, 'r', encoding='utf-8') as src:
            data = src.read()
        with open(USER_CONFIG, 'w', encoding='utf-8') as dst:
            dst.write(data)
        with open(SCHEMA_MARKER, 'w', encoding='utf-8') as f:
            f.write(SCHEMA_VERSION)


def load_shortcuts():
    """Returns the list of {'name':..., 'icon':..., 'action':...}
    shortcut dicts, with exact (name, action) duplicates collapsed —
    this repairs a shortcuts.json that already has duplicates in it
    (e.g. from a shortcut having been added more than once before
    duplicate prevention existed), not just preventing new ones.
    Falls back to the bundled starter list if the user's copy is
    missing or fails to parse."""
    try:
        _ensure_user_config()
        with open(USER_CONFIG, 'r', encoding='utf-8') as f:
            shortcuts = json.load(f)
    except Exception as exc:
        xbmc.log('Command Centre: failed to load shortcuts ({}), '
                 'falling back to bundled defaults'.format(exc), xbmc.LOGWARNING)
        with open(BUNDLED_CONFIG, 'r', encoding='utf-8') as f:
            shortcuts = json.load(f)
    seen = set()
    deduped = []
    for entry in shortcuts:
        key = (entry.get('name', ''), entry.get('action', ''))
        if key not in seen:
            seen.add(key)
            deduped.append(entry)
    return deduped


def save_shortcuts(shortcuts):
    _ensure_user_config()
    with open(USER_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(shortcuts, f, indent=4)


def add_shortcut(name, icon, action):
    """Returns True if the shortcut was added, False if an identical
    (name, action) shortcut already existed and nothing changed."""
    shortcuts = load_shortcuts()
    for entry in shortcuts:
        if entry.get('name', '') == name and entry.get('action', '') == action:
            return False
    shortcuts.append({'name': name, 'icon': icon, 'action': action})
    save_shortcuts(shortcuts)
    return True


def remove_shortcuts(indices):
    """Removes multiple shortcuts by index in one save, so the user
    doesn't have to repeat the remove flow one at a time."""
    shortcuts = load_shortcuts()
    for index in sorted(indices, reverse=True):
        if 0 <= index < len(shortcuts):
            shortcuts.pop(index)
    save_shortcuts(shortcuts)


_ADDON_ID_PATTERNS = [
    re.compile(r'Addon\.OpenSettings\(\s*([^,)]+)\s*\)'),
    re.compile(r'RunAddon\(\s*([^,)]+)'),
    re.compile(r'plugin://([^/]+)/'),
]


def extract_addon_id(action):
    """Returns the addon id an action string targets, if any —
    covers Addon.OpenSettings(id), RunAddon(id[,...]), and
    plugin://id/... URLs. Returns None for actions that don't
    reference a specific addon at all (e.g. a raw system builtin
    like ReloadSkin()), since those have nothing to validate."""
    for pattern in _ADDON_ID_PATTERNS:
        match = pattern.search(action or '')
        if match:
            return match.group(1)
    return None


def get_valid_shortcuts():
    """Returns only the shortcuts whose target addon (if any) is
    actually installed and enabled right now. This is what the
    popup displays — load_shortcuts() (the raw, unfiltered list) is
    still what the add/remove management flows operate on, so a
    now-invalid shortcut can still be found and removed rather than
    just silently hidden forever."""
    enabled_ids = addon_discovery.get_all_enabled_addon_ids()
    valid = []
    for entry in load_shortcuts():
        addon_id = extract_addon_id(entry.get('action', ''))
        if addon_id is None or addon_id in enabled_ids:
            valid.append(entry)
    return valid


def shortcut_key(entry):
    """A stable identity for a shortcut entry, used wherever a
    per-shortcut unique id is needed (custom ordering). Shortcuts
    have no id field of their own, so this combines name and action
    — the same pairing load_shortcuts() already uses to dedupe
    entries — rather than name alone, which two shortcuts can share
    (e.g. two pages linked from the same addon under the same
    label) and would then collide as a dict key."""
    return '{}\x1f{}'.format(entry.get('name', ''), entry.get('action', ''))
