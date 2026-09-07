# -*- coding: utf-8 -*-
"""
Small, local, addon-specific Kodi utility layer for MDB Addon.

Deliberately NOT a copy of redlight's own kodi_utils.py: that module's
build_url() is hardcoded to plugin://plugin.video.redlight/, which is
exactly right for redlight's own internal navigation but wrong for ours --
reusing it here would silently route this addon's own menu screens back
into redlight's plugin process instead of staying in this addon.

Only generic, addon-agnostic Kodi plumbing lives here. Content-specific
logic (metadata, art, playback) is never reimplemented here -- it comes
from redlight's own Movies()/TVShows()/personal_lists modules, imported
directly, exactly as they run inside redlight itself.
"""
import sys
import os
import json
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
from urllib.parse import urlencode

ADDON_ID = 'plugin.video.mdblistred'
MENU_FOLDER_CONTENT = ''


def addon():
	return xbmcaddon.Addon(id=ADDON_ID)


def addon_path():
	return addon().getAddonInfo('path')


def get_icon(name='icon'):
	local_path = os.path.join(addon_path(), 'resources', 'media', '%s.png' % name)
	return local_path if os.path.exists(local_path) else os.path.join(addon_path(), 'resources', 'media', 'icon.png')


def get_addon_fanart():
	return os.path.join(addon_path(), 'resources', 'media', 'fanart.jpg')


def build_url(url_params):
	return 'plugin://%s/?%s' % (ADDON_ID, urlencode(url_params))


def make_listitem(offscreen=True):
	try:
		return xbmcgui.ListItem(offscreen=offscreen)
	except TypeError:
		return xbmcgui.ListItem()


def add_items(handle, item_list):
	try:
		xbmcplugin.addDirectoryItems(handle, item_list)
	except Exception as e:
		logger('MDB Addon', 'add_items failed: %s' % e)


def add_item(handle, url, listitem, is_folder):
	try:
		xbmcplugin.addDirectoryItem(handle, url, listitem, is_folder)
	except Exception as e:
		logger('MDB Addon', 'add_item failed: %s' % e)


def set_content(handle, content):
	try:
		xbmcplugin.setContent(handle, content)
	except:
		pass


def set_category(handle, category):
	try:
		xbmcplugin.setPluginCategory(handle, category)
	except:
		pass


def end_directory(handle, cacheToDisc=True, updateListing=False):
	try:
		xbmcplugin.endOfDirectory(handle, cacheToDisc=cacheToDisc, updateListing=updateListing)
	except Exception as e:
		logger('MDB Addon', 'end_directory failed: %s' % e)


def set_view_mode(view_type, content='files', is_external=False, fallback_view_types=()):
	"""Delegates to redlight's own view-mode resolver (modules.kodi_utils) rather than
	reimplementing it -- this applies the exact same per-skin Flix-style view (view.movies /
	view.tvshows) the user has already configured inside Red Light itself, read from Red
	Light's own addon settings/window properties. Safe no-op if that module isn't importable
	for any reason (e.g. Red Light not installed)."""
	try:
		from modules import kodi_utils as _redlight_kodi_utils
		_redlight_kodi_utils.set_view_mode(view_type, content, is_external, fallback_view_types)
	except Exception as e:
		logger('MDB Addon', 'set_view_mode failed: %s' % e)


def notification(message, duration=3000, heading='MDB Addon', icon=None):
	try:
		xbmcgui.Dialog().notification(heading, message, icon or xbmcgui.NOTIFICATION_INFO, duration)
	except Exception as e:
		logger('MDB Addon', 'notification failed: %s' % e)


def kodi_dialog():
	return xbmcgui.Dialog()


def select_dialog(options, heading='Select'):
	idx = xbmcgui.Dialog().select(heading, options)
	return idx if idx != -1 else None


def container_update(params, block=False):
	if isinstance(params, dict):
		params = build_url(params)
	xbmc.executebuiltin('Container.Update(%s)' % params, block)


def container_refresh():
	xbmc.executebuiltin('Container.Refresh')


def logger(tag, message):
	try:
		xbmc.log('[%s] %s' % (tag, message), xbmc.LOGINFO)
	except:
		pass


# --------------------------------------------------------------- storage --
# Persistent storage for "Add List by URL" entries -- a plain JSON file in
# this addon's own profile folder (special://profile/addon_data/<id>/), so
# saved lists survive restarts/updates without touching redlight at all.

_SAVED_LISTS_FILENAME = 'saved_lists.json'


def _profile_dir():
	path = xbmcvfs.translatePath(addon().getAddonInfo('profile'))
	if not xbmcvfs.exists(path):
		xbmcvfs.mkdirs(path)
	return path


def _saved_lists_path():
	return os.path.join(_profile_dir(), _SAVED_LISTS_FILENAME)


def load_saved_lists():
	file_path = _saved_lists_path()
	if not xbmcvfs.exists(file_path):
		return []
	try:
		handle = xbmcvfs.File(file_path)
		raw = handle.read()
		handle.close()
		data = json.loads(raw) if raw else []
		return data if isinstance(data, list) else []
	except Exception as e:
		logger('MDB Addon', 'load_saved_lists failed: %s' % e)
		return []


def save_saved_lists(items):
	file_path = _saved_lists_path()
	try:
		handle = xbmcvfs.File(file_path, 'w')
		handle.write(json.dumps(items))
		handle.close()
		return True
	except Exception as e:
		logger('MDB Addon', 'save_saved_lists failed: %s' % e)
		return False
