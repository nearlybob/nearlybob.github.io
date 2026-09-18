# -*- coding: utf-8 -*-
"""
Discovers installed, enabled video and program addons via JSON-RPC,
and stores/reads which of them the user has chosen to show in
Command Centre's Video Addons / Program Addons sections.

Verified against the real Kodi JSON-RPC API (Addons.GetAddons):
addon "type" values are "xbmc.addon.video" and "xbmc.addon.executable";
"enabled" accepts a boolean to filter to only enabled addons;
"properties" accepts "name" and "thumbnail" (icon) among others.
"""
import json
import os
import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
VISIBILITY_CONFIG = os.path.join(PROFILE_PATH, 'visible_addons.json')

VIDEO_ADDON_TYPE = 'xbmc.addon.video'
PROGRAM_ADDON_TYPE = 'xbmc.addon.executable'


def _json_rpc(method, params):
    request = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    response = xbmc.executeJSONRPC(json.dumps(request))
    result = json.loads(response)
    if 'error' in result:
        xbmc.log('Command Centre: JSON-RPC error on {}: {}'.format(
            method, result['error']), xbmc.LOGWARNING)
        return None
    return result.get('result')


def discover_addons(addon_type):
    """Returns [{'addonid':..., 'name':..., 'thumbnail':...}, ...] for
    all currently enabled addons of the given type. Excludes this
    addon itself (Command Centre should not be able to list itself
    as a launchable "program addon")."""
    result = _json_rpc('Addons.GetAddons', {
        'type': addon_type,
        'enabled': True,
        'properties': ['name', 'thumbnail'],
    })
    if not result:
        return []
    addons = result.get('addons', [])
    return [a for a in addons if a.get('addonid') != ADDON_ID]


_visibility_cache = None


def _load_visibility_config():
    global _visibility_cache
    if _visibility_cache is not None:
        return _visibility_cache
    if not xbmcvfs.exists(VISIBILITY_CONFIG):
        _visibility_cache = {}
        return _visibility_cache
    try:
        with open(VISIBILITY_CONFIG, 'r', encoding='utf-8') as f:
            _visibility_cache = json.load(f)
    except Exception as exc:
        xbmc.log('Command Centre: failed to read visibility config ({}), '
                 'treating as unset'.format(exc), xbmc.LOGWARNING)
        _visibility_cache = {}
    return _visibility_cache


def _save_visibility_config(config):
    global _visibility_cache
    if not xbmcvfs.exists(PROFILE_PATH):
        xbmcvfs.mkdirs(PROFILE_PATH)
    with open(VISIBILITY_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f)
    _visibility_cache = config


def get_visible_addons(addon_type):
    """Returns the discovered addons of this type, filtered to the
    user's chosen visible set. If the user has never configured
    visibility for this type, every discovered addon is shown by
    default (nothing is hidden until the user explicitly hides it)."""
    discovered = discover_addons(addon_type)
    config = _load_visibility_config()
    chosen_ids = config.get(addon_type)
    if chosen_ids is None:
        return discovered
    return [a for a in discovered if a.get('addonid') in chosen_ids]


def set_visible_addon_ids(addon_type, addon_ids):
    config = _load_visibility_config()
    config[addon_type] = list(addon_ids)
    _save_visibility_config(config)


def get_chosen_ids(addon_type):
    """Returns the stored chosen id list for this type, or None if
    the user has never configured it (meaning: show everything)."""
    return _load_visibility_config().get(addon_type)


def clear_visible_addon_ids(addon_type):
    """Removes any stored visibility choice for this type, reverting
    it to the "never configured" (show everything) state. Used for
    one-off migrations when a section's set of ids changes wholesale
    and an old saved choice would otherwise reference ids that no
    longer exist."""
    config = _load_visibility_config()
    if addon_type in config:
        del config[addon_type]
        _save_visibility_config(config)


def get_all_enabled_addon_ids():
    """Returns a set of every currently enabled addon id, of any type —
    one JSON-RPC call. Used to validate every shortcut's target addon in
    a single round trip instead of one Addons.GetAddonDetails call per
    shortcut (what this replaced, and the only thing that used to need
    a single-addon check — see shortcuts_manager.get_valid_shortcuts)."""
    result = _json_rpc('Addons.GetAddons', {'enabled': True, 'properties': []})
    if not result:
        return set()
    return {a.get('addonid') for a in result.get('addons', [])}
