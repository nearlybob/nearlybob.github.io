# -*- coding: utf-8 -*-
"""Custom names and icons for the addons listed in the popup (overrides.json).

Keyed by addon id, so a rename follows the addon whichever section it is in and survives
hiding/reordering. Only what the user changed is stored; anything not overridden keeps the
addon's own name/icon, and setting a value back to the original removes the override.
"""
from . import store

OVERRIDES_FILE = 'overrides.json'


def _all():
    return store.load(OVERRIDES_FILE, {})


def get(addon_id):
    entry = _all().get(addon_id)
    return entry if isinstance(entry, dict) else {}


def display(addon_id, name, icon):
    """(name, icon) to show for an addon, given its own name and icon."""
    entry = get(addon_id)
    return entry.get('name') or name, entry.get('icon') or icon


def name_of(addon):
    """Display name for an addon dict from addons.discover()."""
    return get(addon['addonid']).get('name') or addon['name']


def _set(addon_id, field, value):
    data = _all()
    entry = dict(get(addon_id))
    if value:
        entry[field] = value
    else:
        entry.pop(field, None)
    if entry:
        data[addon_id] = entry
    else:
        data.pop(addon_id, None)
    store.save(OVERRIDES_FILE, data)


def set_name(addon_id, original_name, new_name):
    """Rename; a blank name, or the addon's own name, clears the override."""
    new_name = (new_name or '').strip()
    _set(addon_id, 'name', '' if new_name == original_name else new_name)


def set_icon(addon_id, icon):
    """Change icon; '' goes back to the addon's own icon."""
    _set(addon_id, 'icon', icon or '')


def reset():
    store.save(OVERRIDES_FILE, {})


def export():
    return {k: dict(v) for k, v in _all().items() if isinstance(v, dict)}


def replace_all(data):
    clean = {}
    for addon_id, entry in (data or {}).items():
        if isinstance(addon_id, str) and isinstance(entry, dict):
            kept = {k: v for k, v in entry.items() if k in ('name', 'icon') and isinstance(v, str) and v}
            if kept:
                clean[addon_id] = kept
    store.save(OVERRIDES_FILE, clean)
