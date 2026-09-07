# -*- coding: utf-8 -*-
"""
MDB Addon -- core browsing/search/export logic.

This addon's OWN menu screens (Popular/Curated/Official/Search, and this
module's folder-building calls) use the local kodi_utils.py in this same
directory -- so this addon's own navigation stays inside its own plugin
process (plugin://plugin.video.mdblistred/...).

The actual list *contents* -- posters, plot, cast, ratings, and playback --
come directly from redlight's own Movies()/TVShows() classes, imported from
redlight's resources/lib (made importable via this addon's <requires> import
of plugin.video.redlight, which declares its own resources/lib as an
xbmc.python.module). Those classes build their own listitems internally
using redlight's kodi_utils, so play actions correctly launch redlight --
this addon never needs to know how playback works.

Exporting a list to a Red Light Personal List reuses redlight's own
indexers.personal_lists + caches.personal_lists_cache directly, so an
exported list is a genuine, native Personal List afterwards -- fully
independent of this addon and of mdblist.com from that point on.
"""
import re
import sys
import json
import requests
from urllib.parse import quote_plus
from threading import Thread

import kodi_utils

# Redlight's own modules -- imported directly, not reimplemented.
from indexers.movies import Movies
from indexers.tvshows import TVShows
from caches.mdblist_cache import mdblist_cache as _cache
from indexers import personal_lists
from caches.personal_lists_cache import personal_lists_cache

_HEADERS = {'User-Agent': 'Mozilla/5.0'}
# See redlight's resources/lib/indexers/mdblist_public.py for the full explanation of
# this pattern (generalized path/slug model, backtrack-safe terminator lookahead).
_LIST_HREF = re.compile(r'/lists/((?:[a-zA-Z0-9_-]+/)+)([a-zA-Z0-9_-]+)(?=["\'?#)\s]|$)')

_SOURCES = {
	'popular': ('https://mdblist.com/toplists/', 'Popular MDBLists'),
	'curated': ('https://mdblist.com/curatedlists/', 'Curated MDBLists'),
	'official': ('https://mdblist.com/lists/official/', 'Official MDBLists'),
}


# ---------------------------------------------------------------- fetching --

def _fetch_html(url):
	try:
		response = requests.get(url, headers=_HEADERS, timeout=20)
		kodi_utils.logger('MDB Addon', 'fetch %s -> status %s, %s bytes' % (url, response.status_code, len(response.text or '')))
		return response.text if response.status_code == 200 else ''
	except Exception as e:
		kodi_utils.logger('MDB Addon', 'fetch FAILED %s: %s' % (url, e))
		return ''

def _fetch_json_list(path, slug):
	cache_key = 'mdblistred_json_%s_%s' % (path.rstrip('/').replace('/', '_'), slug)
	cached = _cache.get(cache_key)
	if cached is not None:
		return cached
	html = _fetch_html('https://mdblist.com/lists/%s%s/json/' % (path, slug))
	try:
		data = json.loads(html)
		data = data if isinstance(data, list) else []
	except:
		data = []
	if data:
		_cache.set(cache_key, data)
	return data


# ------------------------------------------------------------- HTML parse --

def _strip_tags(text):
	return re.sub(r'<[^>]+>', ' ', text).strip()

def _type_tag_from_path(path):
	segments = [s for s in path.split('/') if s]
	if 'movies' in segments:
		return ' (Movies)'
	if 'shows' in segments:
		return ' (Shows)'
	return ''

def _parse_list_cards(html):
	cards, seen = [], set()
	for match in _LIST_HREF.finditer(html):
		path, slug = match.group(1), match.group(2)
		key = (path, slug)
		if key in seen:
			continue
		seen.add(key)
		window = html[match.end():match.end() + 500]
		name = ''
		name_match = re.search(r'>(.*?)</a>', window, re.S)
		if name_match:
			name = _strip_tags(name_match.group(1))
		if not name:
			name = slug.replace('-', ' ').title()
		if 'streaming chart' in name.lower():
			continue
		tag = _type_tag_from_path(path)
		if tag:
			name = '%s%s' % (name, tag)
		cards.append({'path': path, 'slug': slug, 'name': name})
	kodi_utils.logger('MDB Addon', 'parsed %s cards from %s bytes of html' % (len(cards), len(html or '')))
	return cards

def _parse_url(url):
	if not url:
		return None
	match = _LIST_HREF.search(url.strip())
	if not match:
		return None
	path, slug = match.group(1), match.group(2)
	if slug.lower() == 'json':
		return None
	return path, slug


# ---------------------------------------------------------------- menus --

def _context_menu(path, slug, list_name):
	export_url = kodi_utils.build_url({
		'mode': 'export_mdbl_public_list_to_personal',
		'path': path, 'slug': slug, 'list_name': list_name
	})
	add_url = kodi_utils.build_url({
		'mode': 'add_mdbl_public_list_to_personal',
		'path': path, 'slug': slug, 'list_name': list_name
	})
	return [
		('Export to Personal List (New)', 'RunPlugin(%s)' % export_url),
		('Add to Personal List (Existing)', 'RunPlugin(%s)' % add_url),
	]

def mdblist_public_menu(params):
	handle = int(sys.argv[1])
	icon, fanart, build_url = kodi_utils.get_icon(), kodi_utils.get_addon_fanart(), kodi_utils.build_url

	def _entry(label, url_params, is_folder=True):
		listitem = kodi_utils.make_listitem()
		listitem.setLabel(label)
		listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart})
		try:
			listitem.getVideoInfoTag(True).setPlot(' ')
		except:
			pass
		return (build_url(url_params), listitem, is_folder)

	items = [
		_entry('[B]+ Add List by URL[/B]', {'mode': 'add_mdbl_public_list_by_url'}, is_folder=False),
		_entry('[B]Search Lists[/B]', {'mode': 'search_mdbl_public_lists_prompt'}, is_folder=False),
		_entry('Popular Lists', {'mode': 'get_mdbl_public_lists', 'source': 'popular', 'name': 'Popular MDBLists'}),
		_entry('Curated Lists', {'mode': 'get_mdbl_public_lists', 'source': 'curated', 'name': 'Curated MDBLists'}),
		_entry('Official Lists', {'mode': 'get_mdbl_public_lists', 'source': 'official', 'name': 'Official MDBLists'}),
		_entry('My Lists', {'mode': 'saved_mdbl_lists_menu'}),
	]
	kodi_utils.add_items(handle, items)
	kodi_utils.set_content(handle, kodi_utils.MENU_FOLDER_CONTENT)
	kodi_utils.set_category(handle, 'MDB Addon')
	kodi_utils.end_directory(handle)

def get_mdbl_public_lists(params):
	def _process():
		for c in cards:
			try:
				display = '[B]%s[/B]' % c['name']
				url = build_url({
					'mode': 'build_mdbl_public_list',
					'path': c['path'], 'slug': c['slug'], 'list_name': c['name']
				})
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart})
				try:
					listitem.getVideoInfoTag(True).setPlot(' ')
				except:
					pass
				listitem.addContextMenuItems(_context_menu(c['path'], c['slug'], c['name']))
				yield (url, listitem, True)
			except:
				pass
	handle = int(sys.argv[1])
	icon, fanart, build_url = kodi_utils.get_icon(), kodi_utils.get_addon_fanart(), kodi_utils.build_url
	source = params.get('source', 'popular')
	source_url, default_name = _SOURCES.get(source, _SOURCES['popular'])
	cards = _parse_list_cards(_fetch_html(source_url))
	if source == 'official':
		cards = [c for c in cards if c['path'].count('/') >= 2]
	kodi_utils.add_items(handle, list(_process()))
	kodi_utils.set_content(handle, kodi_utils.MENU_FOLDER_CONTENT)
	kodi_utils.set_category(handle, params.get('name', default_name))
	kodi_utils.end_directory(handle)


# -------------------------------------------------------------- search --

def search_mdbl_public_lists_prompt(params):
	query = kodi_utils.kodi_dialog().input('Search Public MDBLists')
	if not query:
		return
	kodi_utils.container_update({'mode': 'search_mdbl_public_lists', 'query': query})

def search_mdbl_public_lists(params):
	def _process():
		for c in cards:
			try:
				display = '[B]%s[/B]' % c['name']
				url = build_url({
					'mode': 'build_mdbl_public_list',
					'path': c['path'], 'slug': c['slug'], 'list_name': c['name']
				})
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart})
				try:
					listitem.getVideoInfoTag(True).setPlot(' ')
				except:
					pass
				listitem.addContextMenuItems(_context_menu(c['path'], c['slug'], c['name']))
				yield (url, listitem, True)
			except:
				pass
	handle = int(sys.argv[1])
	icon, fanart, build_url = kodi_utils.get_icon(), kodi_utils.get_addon_fanart(), kodi_utils.build_url
	query = params.get('query', '')
	cards = []
	if query:
		search_url = 'https://mdblist.com/curatedlists/?public_list_name=%s' % quote_plus(query)
		cards = _parse_list_cards(_fetch_html(search_url))
	kodi_utils.add_items(handle, list(_process()))
	kodi_utils.set_content(handle, kodi_utils.MENU_FOLDER_CONTENT)
	kodi_utils.set_category(handle, ('Search: %s' % query) if query else 'Search Public MDBLists')
	kodi_utils.end_directory(handle)


# ------------------------------------------------------------ add by url --

def add_mdbl_public_list_by_url(params):
	url = kodi_utils.kodi_dialog().input('Paste MDBList List URL')
	if not url:
		return
	parsed = _parse_url(url)
	if not parsed:
		kodi_utils.notification("Couldn't read that URL", 3000)
		return
	path, slug = parsed
	items = _fetch_json_list(path, slug)
	if not items:
		kodi_utils.notification('List not found or empty', 3000)
		return
	default_name = slug.replace('-', ' ').title()
	list_name = kodi_utils.kodi_dialog().input('Name This List', defaultt=default_name) or default_name
	_add_to_saved_lists(path, slug, list_name)
	kodi_utils.container_update({
		'mode': 'build_mdbl_public_list',
		'path': path, 'slug': slug, 'list_name': list_name
	})


# --------------------------------------------------------- saved lists --
# Entries added via "Add List by URL" are kept here so they survive as a
# permanent "My Lists" folder on the main menu, independent of mdblist.com
# session state -- only path/slug/name are stored; contents are always
# re-fetched (and cached, see _fetch_json_list) when the folder is opened.

def _load_saved_lists():
	return kodi_utils.load_saved_lists()

def _save_saved_lists(items):
	kodi_utils.save_saved_lists(items)

def _add_to_saved_lists(path, slug, list_name):
	saved = _load_saved_lists()
	for entry in saved:
		if entry.get('path') == path and entry.get('slug') == slug:
			entry['name'] = list_name
			_save_saved_lists(saved)
			return
	saved.append({'path': path, 'slug': slug, 'name': list_name})
	_save_saved_lists(saved)

def saved_mdbl_lists_menu(params):
	handle = int(sys.argv[1])
	icon, fanart, build_url = kodi_utils.get_icon(), kodi_utils.get_addon_fanart(), kodi_utils.build_url
	saved = _load_saved_lists()
	items = []
	last_index = len(saved) - 1
	for index, entry in enumerate(saved):
		path, slug = entry.get('path', ''), entry.get('slug', '')
		if not path or not slug:
			continue
		name = entry.get('name') or slug.replace('-', ' ').title()
		listitem = kodi_utils.make_listitem()
		listitem.setLabel('[B]%s[/B]' % name)
		listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart})
		try:
			listitem.getVideoInfoTag(True).setPlot(' ')
		except:
			pass
		context = [
			('Rename', 'RunPlugin(%s)' % build_url({'mode': 'rename_saved_mdbl_list', 'path': path, 'slug': slug})),
		]
		if index > 0:
			context.append(('Move Up', 'RunPlugin(%s)' % build_url({'mode': 'move_saved_mdbl_list', 'path': path, 'slug': slug, 'direction': 'up'})))
		if index < last_index:
			context.append(('Move Down', 'RunPlugin(%s)' % build_url({'mode': 'move_saved_mdbl_list', 'path': path, 'slug': slug, 'direction': 'down'})))
		context.append(('Remove from My Lists', 'RunPlugin(%s)' % build_url({'mode': 'remove_saved_mdbl_list', 'path': path, 'slug': slug})))
		listitem.addContextMenuItems(context)
		url = build_url({'mode': 'build_mdbl_public_list', 'path': path, 'slug': slug, 'list_name': name})
		items.append((url, listitem, True))
	kodi_utils.add_items(handle, items)
	kodi_utils.set_content(handle, kodi_utils.MENU_FOLDER_CONTENT)
	kodi_utils.set_category(handle, 'My Lists')
	kodi_utils.end_directory(handle, cacheToDisc=False)

def rename_saved_mdbl_list(params):
	path, slug = params.get('path'), params.get('slug')
	saved = _load_saved_lists()
	entry = next((e for e in saved if e.get('path') == path and e.get('slug') == slug), None)
	if entry is None:
		kodi_utils.notification('Not found in My Lists', 3000)
		return
	current_name = entry.get('name') or slug.replace('-', ' ').title()
	new_name = kodi_utils.kodi_dialog().input('Rename List', defaultt=current_name)
	if not new_name or new_name == current_name:
		return
	entry['name'] = new_name
	_save_saved_lists(saved)
	kodi_utils.container_refresh()

def move_saved_mdbl_list(params):
	path, slug, direction = params.get('path'), params.get('slug'), params.get('direction')
	saved = _load_saved_lists()
	index = next((i for i, e in enumerate(saved) if e.get('path') == path and e.get('slug') == slug), None)
	if index is None:
		kodi_utils.notification('Not found in My Lists', 3000)
		return
	target = index - 1 if direction == 'up' else index + 1
	if target < 0 or target >= len(saved):
		return
	saved[index], saved[target] = saved[target], saved[index]
	_save_saved_lists(saved)
	kodi_utils.container_refresh()

def remove_saved_mdbl_list(params):
	path, slug = params.get('path'), params.get('slug')
	saved = _load_saved_lists()
	new_saved = [e for e in saved if not (e.get('path') == path and e.get('slug') == slug)]
	if len(new_saved) == len(saved):
		kodi_utils.notification('Not found in My Lists', 3000)
		return
	_save_saved_lists(new_saved)
	kodi_utils.notification('Removed from My Lists', 3000)
	kodi_utils.container_refresh()


# ----------------------------------------------------------- build list --

def _rows_from_json(path, slug):
	movies, shows = [], []
	for i in _fetch_json_list(path, slug):
		try:
			tmdb_id = i.get('id')
			if not tmdb_id:
				continue
			row = (i.get('rank') or 0, int(tmdb_id))
			if (i.get('mediatype') or '').lower() == 'movie':
				movies.append(row)
			else:
				shows.append(row)
		except:
			pass
	movies.sort(key=lambda k: k[0])
	shows.sort(key=lambda k: k[0])
	return movies, shows

def build_mdbl_public_list(params):
	handle = int(sys.argv[1])
	path, slug, list_name = params.get('path'), params.get('slug'), params.get('list_name', 'MDBList')
	movies, shows = _rows_from_json(path, slug)
	item_list, threads = [], []
	if movies:
		threads.append(Thread(target=lambda: item_list.extend(Movies({'list': movies, 'custom_order': 'true'}).worker())))
	if shows:
		threads.append(Thread(target=lambda: item_list.extend(TVShows({'list': shows, 'custom_order': 'true'}).worker())))
	for t in threads:
		t.start()
	for t in threads:
		t.join()
	item_list.sort(key=lambda k: k[1])
	content = 'movies' if len(movies) >= len(shows) else 'tvshows'
	kodi_utils.add_items(handle, [i[0] for i in item_list])
	kodi_utils.set_content(handle, content)
	kodi_utils.set_category(handle, list_name)
	kodi_utils.end_directory(handle, cacheToDisc=True)
	# Match redlight's own build_mdbl_list: switch into the Flix-style view.movies/view.tvshows
	# skin view once the directory content is set, so the fanart/clearlogo/plot already set on
	# each item by Movies()/TVShows() above is actually displayed.
	kodi_utils.set_view_mode('view.%s' % content, content, False)


# --------------------------------------------------- export to personal --

def _build_personal_list_contents(raw_items):
	from modules.utils import get_current_timestamp
	current_timestamp = get_current_timestamp()
	new_contents = []
	for count, i in enumerate(raw_items):
		try:
			tmdb_id = i.get('id')
			if not tmdb_id:
				continue
			mediatype = 'movie' if (i.get('mediatype') or '').lower() == 'movie' else 'tvshow'
			release_year = i.get('release_year')
			# Redlight's own Movies()/TVShows() pull the real release date from TMDb once
			# the tmdb_id is stored -- this is only a harmless placeholder for the
			# personal-list storage row itself, matching how e.g. a bare year would sort.
			release_date = ('%s-01-01' % release_year) if release_year else ''
			new_contents.append({
				'media_id': str(int(tmdb_id)),
				'title': i.get('title') or '',
				'type': mediatype,
				'release_date': release_date,
				'date_added': str(current_timestamp + count),
			})
		except:
			continue
	return new_contents

def export_mdbl_public_list_to_personal(params):
	path, slug, list_name = params.get('path'), params.get('slug'), params.get('list_name', 'MDBList')
	new_contents = _build_personal_list_contents(_fetch_json_list(path, slug))
	if not new_contents:
		kodi_utils.notification('Nothing to export', 3000)
		return
	created_name, created_author = personal_lists.make_new_personal_list({
		'external_creation': 'true',
		'suggested_list_name': list_name,
	})
	if not created_name:
		return  # user cancelled the name/author/sort prompts
	result = personal_lists_cache.add_many_list_items(created_name, created_author, new_contents)
	if result == 'Success':
		kodi_utils.notification('Exported %s items to "%s"' % (len(new_contents), created_name), 4000)
	else:
		kodi_utils.notification('Export failed', 3000)

def add_mdbl_public_list_to_personal(params):
	"""Merge this list's contents into a Personal List the user already has -- rather than
	create a new one. add_many_list_items already de-dupes against what's already in the
	target list (by media_id per movie/show type), so repeat adds don't create duplicates."""
	path, slug = params.get('path'), params.get('slug')
	new_contents = _build_personal_list_contents(_fetch_json_list(path, slug))
	if not new_contents:
		kodi_utils.notification('Nothing to add', 3000)
		return
	existing = personal_lists.get_all_personal_lists()
	if not existing:
		kodi_utils.notification('No Personal Lists yet -- use "Export to Personal List" to create one', 5000)
		return
	labels = ['%s (%s) - %s items' % (i.get('name', ''), i.get('author', 'Unknown'), i.get('total') or 0) for i in existing]
	idx = kodi_utils.select_dialog(labels, heading='Add to Personal List')
	if idx is None:
		return
	chosen = existing[idx]
	result = personal_lists_cache.add_many_list_items(chosen['name'], chosen['author'], new_contents)
	if result == 'Success':
		kodi_utils.notification('Added to "%s"' % chosen['name'], 4000)
	else:
		kodi_utils.notification('Add failed', 3000)
