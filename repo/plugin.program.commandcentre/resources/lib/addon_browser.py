# -*- coding: utf-8 -*-
"""
Lets the user browse into an installed addon's own menu structure —
the same way Nimbus's widget picker lets you drill into an addon to
pick a specific list as a widget source — and choose any page along
the way as a Shortcuts target, rather than only the addon's top
level or a fully manual plugin:// URL.

Uses the real Files.GetDirectory JSON-RPC method (verified: takes
'directory' and 'media' params, returns a 'files' array where each
entry has 'file', 'filetype' ('file' or 'directory'), and 'label').
"""
import json
import xbmc
import xbmcgui


def _get_directory(url):
    """Returns the list of {'file':..., 'filetype':..., 'label':...}
    entries for a plugin:// directory, or None on error (e.g. the
    addon's own code raised an exception while building that page —
    real plugin addons can do this for pages that need extra
    context this browse-only call doesn't provide)."""
    request = {
        'jsonrpc': '2.0', 'id': 1, 'method': 'Files.GetDirectory',
        'params': {'directory': url, 'media': 'files'},
    }
    response = xbmc.executeJSONRPC(json.dumps(request))
    result = json.loads(response)
    if 'error' in result:
        xbmc.log('Command Centre: Files.GetDirectory error for {}: {}'.format(
            url, result['error']), xbmc.LOGWARNING)
        return None
    return result.get('result', {}).get('files', [])


def browse_and_pick(addon_id, addon_name):
    """Interactive drill-down: at every level, offers 'Use this page'
    plus everything the addon lists there. Picking a folder drills
    in; picking a file (or 'Use this page') ends the browse and
    returns (label, plugin_url). Returns None if cancelled at any
    point (Back or closing a select dialog)."""
    current_url = 'plugin://{}/'.format(addon_id)
    current_label = addon_name

    while True:
        listing = _get_directory(current_url)
        if listing is None:
            xbmcgui.Dialog().notification(
                'Command Centre', 'Could not browse this addon',
                xbmcgui.NOTIFICATION_ERROR)
            return None

        use_this_page = 'Use "{}" as the shortcut'.format(current_label)
        options = [use_this_page] + [f.get('label', '') for f in listing]
        choice = xbmcgui.Dialog().select(current_label, options)
        if choice < 0:
            return None  # Back/cancel — abandon the whole browse
        if choice == 0:
            return current_label, current_url

        entry = listing[choice - 1]
        if entry.get('filetype') == 'directory':
            current_url = entry.get('file')
            current_label = entry.get('label') or current_label
        else:
            return entry.get('label') or current_label, entry.get('file')
