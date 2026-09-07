# -*- coding: utf-8 -*-
"""
MDB Addon -- standalone entry point.

Depends on plugin.video.redlight being installed and enabled (declared in
addon.xml <requires>). Redlight's own addon.xml exposes its resources/lib
as an importable Python module via <extension point="xbmc.python.module">,
which is the Kodi-native way this addon's <requires> import should make
redlight's modules (indexers.movies, indexers.tvshows, indexers.personal_lists,
etc.) directly importable without any manual path manipulation.

The manual sys.path fallback below only runs if that doesn't hold on a given
Kodi build/version -- it's a safety net, not the primary mechanism.
"""
import sys
import os

_ADDON_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', 'lib')
if _ADDON_LIB not in sys.path:
	sys.path.insert(0, _ADDON_LIB)


def _ensure_redlight_importable():
	"""Best-effort fallback: if redlight's modules aren't already importable via Kodi's
	own xbmc.python.module mechanism, manually add its resources/lib to sys.path."""
	try:
		from indexers import movies  # noqa: F401 -- probe only
		return True
	except ImportError:
		pass
	try:
		import xbmcaddon
		redlight = xbmcaddon.Addon('plugin.video.redlight')
		redlight_lib = os.path.join(redlight.getAddonInfo('path'), 'resources', 'lib')
		if redlight_lib not in sys.path:
			sys.path.insert(0, redlight_lib)
		from indexers import movies  # noqa: F401 -- probe again
		return True
	except Exception:
		return False


if not _ensure_redlight_importable():
	import xbmcgui
	xbmcgui.Dialog().ok(
		'MDB Addon',
		'This addon requires Red Light (plugin.video.redlight) to be installed and enabled.'
	)
	sys.exit(0)

from router import router
router(sys.argv)
