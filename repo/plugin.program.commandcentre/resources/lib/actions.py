# -*- coding: utf-8 -*-
"""Builds the Kodi built-in strings stored in shortcuts.

Kodi's built-in for opening a plugin folder is ActivateWindow(<window>,<url>,return);
for playing an item PlayMedia(<url>); for running a plugin action RunPlugin(<url>).
A bare plugin:// URL is not a built-in, so shortcuts must always store one of these.
URLs are double-quoted so commas/brackets inside them don't split the parameters.
"""


def quote(value):
    return '"{}"'.format(value.replace('"', '%22'))


def open_folder(window, url):
    return 'ActivateWindow({},{},return)'.format(window, quote(url))


def play(url):
    return 'PlayMedia({})'.format(quote(url))


def run_plugin(url):
    return 'RunPlugin({})'.format(quote(url))


# Actions that don't take you to another page, so there is nothing to "back out" of.
NO_RETURN_PREFIXES = ('ReloadSkin', 'RestartApp', 'Quit', 'ToggleDebug', 'Minimize')


def should_return(action):
    """True if backing out of this action should reopen the popup."""
    return not action.strip().startswith(NO_RETURN_PREFIXES)


def plugin_addon_id(url):
    """'plugin://plugin.video.x/foo' -> 'plugin.video.x' (None if not a plugin URL)."""
    if not url.lower().startswith('plugin://'):
        return None
    rest = url[len('plugin://'):]
    for sep in '/?#':
        rest = rest.split(sep, 1)[0]
    return rest or None
