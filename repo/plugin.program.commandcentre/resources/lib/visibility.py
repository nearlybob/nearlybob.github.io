# -*- coding: utf-8 -*-
"""Which entries the user has chosen to HIDE, per section (hidden.json).

This is a hide-list on purpose: anything not hidden is shown, so a newly
installed addon (or a system function added in a later version) appears by
default instead of staying invisible until the user re-opens the config.

Versions before 1.0.1 stored an allow-list (visible_addons.json); that file is
converted once, on first use, to the equivalent hide-list.
"""
import xbmc

from . import addons, store
from .common import log

SYSTEM_KEY = 'system'
HIDDEN_FILE = 'hidden.json'
LEGACY_FILE = 'visible_addons.json'
_STALE_FILES = ('shortcuts_schema.txt', 'system_actions_schema.txt')


def _data():
    if store.exists(HIDDEN_FILE):
        return store.load(HIDDEN_FILE, {})
    try:
        data = _migrate_legacy()
        store.save(HIDDEN_FILE, data)
        for name in _STALE_FILES:
            store.delete(name)
    except Exception as exc:
        log('visibility migration failed: {}'.format(exc), xbmc.LOGWARNING)
        data = {}
        store.load(HIDDEN_FILE, {})  # cache an empty dict for this run
    return data


def _migrate_legacy():
    if not store.exists(LEGACY_FILE):
        return {}
    from . import system_actions  # local import: keeps this module dependency-light
    legacy = store.load(LEGACY_FILE, {})
    result = {}
    for key, allowed in legacy.items():
        if not isinstance(allowed, list):
            continue
        allowed = set(allowed)
        if key == SYSTEM_KEY:
            universe = [a['id'] for a in system_actions.SYSTEM_ACTIONS]
        else:
            universe = [a['addonid'] for a in addons.discover(key)]
        hidden = [i for i in universe if i not in allowed]
        if hidden:
            result[key] = hidden
    store.rename(LEGACY_FILE, LEGACY_FILE + '.migrated')
    return result


def hidden_ids(key):
    return set(_data().get(key, []))


def set_hidden(key, ids):
    data = _data()
    ids = list(dict.fromkeys(ids))
    if ids:
        data[key] = ids
    else:
        data.pop(key, None)
    store.save(HIDDEN_FILE, data)


def hide(key, entry_id):
    ids = list(_data().get(key, []))
    if entry_id not in ids:
        ids.append(entry_id)
    set_hidden(key, ids)


def apply_checked(key, universe_ids, checked_ids):
    """Save the result of a 'choose visible' dialog: everything in universe_ids that
    was left unchecked becomes hidden. Hidden ids that aren't in universe_ids right
    now (e.g. an addon that's temporarily disabled) stay hidden."""
    universe = list(universe_ids)
    checked = set(checked_ids)
    known = set(universe)
    kept = [i for i in _data().get(key, []) if i not in known]
    set_hidden(key, [i for i in universe if i not in checked] + kept)


def export():
    return {k: list(v) for k, v in _data().items()}


def replace_all(data):
    clean = {}
    for key, ids in (data or {}).items():
        if isinstance(key, str) and isinstance(ids, list):
            ids = [i for i in ids if isinstance(i, str)]
            if ids:
                clean[key] = ids
    store.save(HIDDEN_FILE, clean)
