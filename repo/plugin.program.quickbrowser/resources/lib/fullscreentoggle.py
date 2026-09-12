# -*- coding: utf-8 -*-
"""
Temporarily switches Kodi from true exclusive fullscreen to
"fullscreen window" (borderless windowed) mode while a Chrome
session is active, restoring whatever mode was set before on exit.

REVISED APPROACH: an earlier version did this via JSON-RPC
Settings.SetSettingValue on videoscreen.fakefullscreen, and was
confirmed via a real device log to lock up Kodi entirely -
xbmc.executeJSONRPC() is a synchronous call, and Kodi's handling of
that specific settings write never returned (nothing after the
"switching" log line ever appeared, not even the unconditional
Chrome-launch line that always follows in the calling code).

This version instead uses xbmc.executebuiltin('Action(togglefullscreen)')
- the exact same action bound to the \\ key by default for manually
flipping between windowed and fullscreen. executebuiltin() is
fire-and-forget (posts to Kodi's action queue and returns
immediately, unlike executeJSONRPC's synchronous request/response),
and this is a heavily-exercised, ordinary code path rather than the
settings-write path that hung. A real forum post independently
confirms this exact pattern working for the same use case (dropping
out of fullscreen, launching a kiosk-mode browser, restoring
fullscreen after):

    xbmc.executebuiltin('XBMC.Action(togglefullscreen)')
    subprocess.call([...browser path..., "-k"])
    xbmc.executebuiltin('XBMC.Action(togglefullscreen)')

Since this is a TOGGLE rather than a direct set, the current state is
still read via JSON-RPC Settings.GetSettingValue first (that read -
not the write - is what worked fine before; only the write hung), so
the toggle is only fired when the state actually needs to change, and
exactly one more toggle on exit is known to restore the original
state correctly.

Known residual limitation: since executebuiltin() doesn't wait for
the transition to finish, there's a small window where Chrome could
launch before Kodi's window mode has actually finished changing. A
short fixed delay is inserted after firing the toggle to reduce this,
but the exact right duration hasn't been tested on a real device.

Second residual limitation, inherent to toggling rather than
directly setting a value: restore() assumes nothing else changed the
fullscreen state during the session, and just fires the toggle back
once if a toggle was fired on the way in. If the user manually
presses \\ (or otherwise changes display mode) while Chrome is open,
restore() would toggle in the wrong direction on exit, since its
one-toggle-undoes-one-toggle assumption would no longer hold. A
direct "set to X" write would not have this problem, but is exactly
what hung Kodi in the previous approach - accepted as a tradeoff.
"""

import json

import xbmc

SETTING_ID = 'videoscreen.fakefullscreen'
TOGGLE_DELAY_MS = 500


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


def get_current_fakefullscreen():
    """
    Read-only - confirmed safe from a real device log (this call
    returned successfully right before the write that hung).
    """
    result = _call('Settings.GetSettingValue', {'setting': SETTING_ID})
    return result.get('result', {}).get('value')


def _fire_toggle():
    xbmc.executebuiltin('Action(togglefullscreen)')
    xbmc.sleep(TOGGLE_DELAY_MS)


def enable_fullscreen_window():
    """
    Switch Kodi to fullscreen-window (borderless) mode if it isn't
    already, and return the previous value so it can be restored. If
    the current value can't be read, does NOT change anything - same
    reasoning as soundtoggle.silence(): changing it blind would leave
    restore() with nothing to go back to.
    """
    original = get_current_fakefullscreen()
    if original is None:
        xbmc.log(
            '[plugin.program.quickbrowser] Could not read current {} - '
            'skipping fullscreen-window switching entirely rather than '
            'risk leaving it stuck'.format(SETTING_ID),
            xbmc.LOGWARNING,
        )
        return None

    if original is True:
        xbmc.log(
            '[plugin.program.quickbrowser] Already in fullscreen-window mode - not toggling',
            xbmc.LOGINFO,
        )
        return original

    xbmc.log(
        '[plugin.program.quickbrowser] Toggling to fullscreen-window mode via Action(togglefullscreen) (was: {})'.format(
            original
        ),
        xbmc.LOGINFO,
    )
    _fire_toggle()
    return original


def restore(original_value):
    """
    Restore whatever fakefullscreen value was active before
    enable_fullscreen_window() was called, by toggling back exactly
    once if - and only if - a toggle was actually fired (i.e.
    original_value was False, meaning we switched away from it).
    """
    if original_value is None or original_value is True:
        # Either enable_fullscreen_window() was never called, skipped
        # because it couldn't read the original value, or the mode
        # was already fullscreen-window and nothing was toggled -
        # nothing to restore in any of those cases.
        return
    xbmc.log(
        '[plugin.program.quickbrowser] Toggling back via Action(togglefullscreen) to restore original mode',
        xbmc.LOGINFO,
    )
    _fire_toggle()
