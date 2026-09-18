# -*- coding: utf-8 -*-
"""
Stores the user's custom ordering for the popup's sections (headings)
and for the items within each section, as a separate JSON file from
visible_addons.json (that file governs *which* items show; this one
governs the order they show in — independent, so re-ordering never
disturbs visibility choices and vice versa).

SECTION_KEYS/SECTION_LABELS are the four fixed section identities;
per-section item order is keyed by the same strings addon_discovery
and system_actions already use for visibility (VIDEO_ADDON_TYPE,
PROGRAM_ADDON_TYPE, SYSTEM_KEY) plus a dedicated key for Shortcuts,
which has no equivalent constant elsewhere.
"""
import os
import json
import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
ORDER_CONFIG = os.path.join(PROFILE_PATH, 'order.json')

HEADINGS_KEY = 'headings'
SHORTCUTS_KEY = 'shortcuts'

SECTION_KEYS = ['video_addons', 'program_addons', SHORTCUTS_KEY, 'system']
SECTION_LABELS = {
    'video_addons': 'Video Addons',
    'program_addons': 'Program Addons',
    SHORTCUTS_KEY: 'Shortcuts',
    'system': 'System',
}


_cache = None


def _load():
    global _cache
    if _cache is not None:
        return _cache
    if not xbmcvfs.exists(ORDER_CONFIG):
        _cache = {}
        return _cache
    try:
        with open(ORDER_CONFIG, 'r', encoding='utf-8') as f:
            _cache = json.load(f)
    except Exception as exc:
        xbmc.log('Command Centre: failed to read order config ({}), '
                 'treating as unset'.format(exc), xbmc.LOGWARNING)
        _cache = {}
    return _cache


def _save(config):
    global _cache
    if not xbmcvfs.exists(PROFILE_PATH):
        xbmcvfs.mkdirs(PROFILE_PATH)
    with open(ORDER_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f)
    _cache = config


def get_order(key, current_ids):
    """Returns current_ids reordered: ids previously saved for this
    key come first (in that saved order, dropping any no longer
    present), followed by any ids not seen before in their original
    order — so a newly discovered addon, a newly added shortcut, or
    a newly available system function simply appears at the end
    rather than being dropped or crashing the lookup."""
    saved = _load().get(key)
    current_ids = list(current_ids)
    if not saved:
        return current_ids
    current_set = set(current_ids)
    ordered = [i for i in saved if i in current_set]
    seen = set(ordered)
    ordered.extend(i for i in current_ids if i not in seen)
    return ordered


def set_order(key, ids):
    """Stores ids as the order for key. Any previously-saved id not in
    ids is preserved, appended after ids in its old relative order —
    this matters because the reorder UI only ever offers the currently
    *visible* entries in a section (see settings_actions._reorder_section),
    so ids can legitimately be missing here just because they're hidden
    right now. Without this, saving a reorder while something is hidden
    would permanently forget its old position instead of leaving it
    alone for whenever it's shown again."""
    config = _load()
    ids = list(ids)
    old = config.get(key) or []
    ids_set = set(ids)
    preserved = [i for i in old if i not in ids_set]
    config[key] = ids + preserved
    _save(config)
