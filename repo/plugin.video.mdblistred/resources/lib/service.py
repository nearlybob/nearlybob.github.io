# -*- coding: utf-8 -*-
"""
MDB Addon -- season-view fix-up service.

Why this exists: Red Light's own seasons.py decides whether to apply the
saved 'view.seasons' Flix view based on kodi_utils.external(), which reads
the 'Container.PluginName' infolabel. That infolabel is stale on the very
first paint of a new plugin directory -- it still reports the *previous*
container's addon id. Navigating show -> season from inside Red Light
itself is harmless (previous container was also Red Light), but reaching
the same season list by clicking a show from an MDB Addon-built list means
the previous container was plugin.video.mdblistred, so external() comes
back True and Red Light silently skips Container.SetViewMode() for that
directory -- the saved view is correct, it's just never applied.

This monitor watches for exactly that situation (Red Light showing a
'seasons' directory reached via build_season_list, on the wrong view) and
re-applies the saved view directly. It never touches Red Light's own
files, only reads the shared view.seasons setting it already exposes.

Deliberately narrow triggers:
- Only acts on Container.Content == 'seasons' AND folder path mode ==
  build_season_list, so it never interferes with Red Light's own "Set
  Views" wizard screens (navigator.choose_view/set_view), which also show
  content='seasons' while the user is deliberately picking a new view.
  (MDB Addon no longer has its own copy of that wizard -- view changes are
  made through Red Light's Tools > Set Views instead; this monitor just
  makes sure whatever's saved there actually gets applied when seasons are
  reached through MDB Addon's lists.)
- Only fires when the live viewmode actually differs from the saved
  setting, so it's a no-op once Red Light has applied it correctly (e.g.
  when browsing from inside Red Light itself).
"""
import sys
import os
import xbmc
from urllib.parse import unquote

_ADDON_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)))
if _ADDON_LIB not in sys.path:
	sys.path.insert(0, _ADDON_LIB)


def _ensure_redlight_importable():
	try:
		from caches import settings_cache  # noqa: F401 -- probe only
		return True
	except ImportError:
		pass
	try:
		import xbmcaddon
		redlight = xbmcaddon.Addon('plugin.video.redlight')
		redlight_lib = os.path.join(redlight.getAddonInfo('path'), 'resources', 'lib')
		if redlight_lib not in sys.path:
			sys.path.insert(0, redlight_lib)
		from caches import settings_cache  # noqa: F401 -- probe again
		return True
	except Exception:
		return False


def _saved_seasons_view_id():
	try:
		from caches.settings_cache import get_setting
		return get_setting('redlight.view.seasons') or get_setting('view.seasons') or None
	except Exception:
		return None


class SeasonViewFixMonitor(xbmc.Monitor):
	def __init__(self):
		xbmc.Monitor.__init__(self)
		self._redlight_ready = _ensure_redlight_importable()

	def _check(self):
		if not self._redlight_ready:
			self._redlight_ready = _ensure_redlight_importable()
			if not self._redlight_ready:
				return
		if xbmc.getInfoLabel('Container.PluginName') != 'plugin.video.redlight':
			return
		if xbmc.getInfoLabel('Container.Content') != 'seasons':
			return
		folder_path = unquote(xbmc.getInfoLabel('Container.FolderPath') or '')
		if 'mode=build_season_list' not in folder_path:
			return
		saved_view_id = _saved_seasons_view_id()
		if not saved_view_id:
			return
		current_view_id = xbmc.getInfoLabel('Container.Viewmode.id') or xbmc.getInfoLabel('Container.Viewmode')
		if current_view_id and str(current_view_id) == str(saved_view_id):
			return
		xbmc.executebuiltin('Container.SetViewMode(%s)' % saved_view_id)

	def run(self):
		while not self.abortRequested():
			try:
				self._check()
			except Exception as e:
				try:
					xbmc.log('[MDB Addon] season view fix-up failed: %s' % e, xbmc.LOGDEBUG)
				except Exception:
					pass
			if self.waitForAbort(1.0):
				break


if __name__ == '__main__':
	SeasonViewFixMonitor().run()
