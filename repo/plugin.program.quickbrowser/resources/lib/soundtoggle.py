# -*- coding: utf-8 -*-
"""
Kodi plays its own UI navigation/select sound effects on directional
and select actions - tied to the action itself, not to which window
handles it - so every cursor move via this addon also triggers Kodi's
normal move/select blip.

CORRECTED APPROACH (v0.5.0): an earlier version of this module tried
toggling lookandfeel.soundskin to a value of "OFF", based on an old
guisettings.xml example found online. Real-device testing showed this
does not work on current Kodi - the log showed:

    Unknown sounds addon 'OFF'. Setting default sounds.

Kodi's sound-skin setting is addon-based, so "OFF" was interpreted as
an addon ID, failed to resolve, and Kodi silently fell back to the
default sound theme instead of muting anything.

The correct setting is audiooutput.guisoundmode - a separate integer
setting (distinct from which sound theme is selected) controlling
*whether* GUI sounds play at all. Confirmed against Kodi's own
system/settings/settings.xml source, which contains:

    <dependency type="enable" setting="audiooutput.guisoundmode"
                operator="!is">0</dependency>

on the GUI sound volume setting - i.e. the volume control is only
enabled when guisoundmode is NOT 0, confirming 0 corresponds to
"Never" (no sound to set a volume for). Real guisettings.xml dumps
found in the wild show this setting defaulting to 1 ("Only when
playback is stopped").

This silences GUI sounds by temporarily setting audiooutput.guisoundmode
to 0 while the addon is running, and restores whatever integer value
was there before (whatever the user had configured - 0, 1, or 2).
"""

import json

import xbmc

SETTING_ID = 'audiooutput.guisoundmode'
NEVER_VALUE = 0


def _call(method, params):
    request = json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1})
    response = xbmc.executeJSONRPC(request)
    try:
        return json.loads(response)
    except ValueError:
        xbmc.log(
            '[plugin.program.quickbrowser] Could not parse JSON-RPC response: {}'.format(response),
            xbmc.LOGERROR,
        )
        return {}


def get_current_guisoundmode():
    result = _call('Settings.GetSettingValue', {'setting': SETTING_ID})
    return result.get('result', {}).get('value')


def set_guisoundmode(value):
    result = _call('Settings.SetSettingValue', {'setting': SETTING_ID, 'value': value})
    if 'error' in result:
        xbmc.log(
            '[plugin.program.quickbrowser] Failed to set {}={}: {}'.format(
                SETTING_ID, value, result['error']
            ),
            xbmc.LOGERROR,
        )
        return False
    return True


def silence():
    """
    Mute Kodi's UI sounds and return the previous value so it can be
    restored. If the current value can't be read (JSON-RPC failure),
    does NOT mute at all - muting without a known original value
    would mean restore() has nothing to restore to, leaving the
    user's Kodi silently and permanently muted after the addon exits.
    """
    original = get_current_guisoundmode()
    if original is None:
        xbmc.log(
            '[plugin.program.quickbrowser] Could not read current {} - '
            'skipping sound silencing entirely rather than risk leaving '
            'it permanently muted'.format(SETTING_ID),
            xbmc.LOGWARNING,
        )
        return None
    xbmc.log(
        '[plugin.program.quickbrowser] Silencing UI sounds via {} (was: {})'.format(
            SETTING_ID, original
        ),
        xbmc.LOGINFO,
    )
    set_guisoundmode(NEVER_VALUE)
    return original


def restore(original_value):
    """Restore whatever guisoundmode value was active before silence() was called."""
    if original_value is None:
        # silence() either was never called or skipped muting entirely
        # because it couldn't read the original value - nothing to do.
        return
    xbmc.log(
        '[plugin.program.quickbrowser] Restoring UI sounds to: {}'.format(original_value),
        xbmc.LOGINFO,
    )
    set_guisoundmode(original_value)

