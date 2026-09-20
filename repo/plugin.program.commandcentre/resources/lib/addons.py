# -*- coding: utf-8 -*-
"""Addon discovery through JSON-RPC (Addons.GetAddons).

Results are sorted A-Z by name and cached for the life of the script.
"""
import json
import os

import xbmc
import xbmcvfs

from .common import ADDON_ID, log

VIDEO = 'xbmc.addon.video'
AUDIO = 'xbmc.addon.audio'
IMAGE = 'xbmc.addon.image'
EXECUTABLE = 'xbmc.addon.executable'

# Window to open a plugin folder in, by the content type the addon provides.
WINDOWS = {VIDEO: 'Videos', AUDIO: 'Music', IMAGE: 'Pictures', EXECUTABLE: 'Programs'}
BROWSABLE_TYPES = (VIDEO, AUDIO, IMAGE, EXECUTABLE)  # also the priority order for de-duplication

_cache = {}


def rpc(method, params):
    """Result of a JSON-RPC call, or None on any error."""
    request = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    try:
        result = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except Exception as exc:
        log('JSON-RPC {} failed: {}'.format(method, exc), xbmc.LOGWARNING)
        return None
    if 'error' in result:
        log('JSON-RPC error on {}: {}'.format(method, result['error']), xbmc.LOGWARNING)
        return None
    return result.get('result')


def _sorted(addon_list):
    return sorted(addon_list, key=lambda a: a['name'].lower())


def _clean(raw):
    out = []
    for a in raw or []:
        addon_id = a.get('addonid')
        if not addon_id or addon_id == ADDON_ID:
            continue
        entry = dict(a)
        entry['name'] = a.get('name') or addon_id
        out.append(entry)
    return _sorted(out)


def discover(addon_type):
    """Enabled addons of one type: [{'addonid', 'name', 'thumbnail'}], A-Z.
    Excludes Command Centre itself."""
    key = ('type', addon_type)
    if key not in _cache:
        result = rpc('Addons.GetAddons', {
            'type': addon_type, 'enabled': True, 'properties': ['name', 'thumbnail']})
        _cache[key] = _clean((result or {}).get('addons'))
    return _cache[key]


def discover_unique(addon_type):
    """Like discover(), but an addon that provides several kinds of content (say video
    and audio) is listed only under the first type in BROWSABLE_TYPES, so it doesn't
    appear in two sections."""
    if 'unique' not in _cache:
        seen = set()
        unique = {}
        for t in BROWSABLE_TYPES:
            unique[t] = [a for a in discover(t) if a['addonid'] not in seen]
            seen.update(a['addonid'] for a in unique[t])
        _cache['unique'] = unique
    return _cache['unique'][addon_type]


def enabled_ids():
    """Ids of every enabled addon of any type (one call)."""
    if 'enabled_ids' not in _cache:
        result = rpc('Addons.GetAddons', {'enabled': True, 'properties': []})
        _cache['enabled_ids'] = {a.get('addonid') for a in (result or {}).get('addons', [])}
    return _cache['enabled_ids']


def browsable():
    """Plugin addons that can be browsed (video/audio/image/program), de-duplicated,
    each with the 'window' its folders should open in."""
    if 'browsable' not in _cache:
        found = []
        for addon_type in BROWSABLE_TYPES:
            for a in discover_unique(addon_type):
                entry = dict(a)
                entry['window'] = WINDOWS[addon_type]
                found.append(entry)
        _cache['browsable'] = _sorted(found)
    return _cache['browsable']


def window_for(addon_id):
    for a in browsable():
        if a['addonid'] == addon_id:
            return a['window']
    return None


def with_settings():
    """Every enabled addon (any type, services included) that has a settings.xml."""
    if 'with_settings' not in _cache:
        result = rpc('Addons.GetAddons', {
            'enabled': True, 'properties': ['name', 'thumbnail', 'path']})
        with_path = result is not None
        if result is None:  # older/odd builds: retry without 'path' and keep everything
            result = rpc('Addons.GetAddons', {
                'enabled': True, 'properties': ['name', 'thumbnail']})
        found = []
        for a in _clean((result or {}).get('addons')):
            path = a.get('path')
            if with_path and path and not xbmcvfs.exists(
                    os.path.join(path, 'resources', 'settings.xml')):
                continue
            found.append(a)
        _cache['with_settings'] = found
    return _cache['with_settings']


def clear_cache():
    _cache.clear()
