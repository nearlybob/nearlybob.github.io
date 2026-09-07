# -*- coding: utf-8 -*-
from urllib.parse import parse_qsl


def _parse_params(argv):
	query = argv[2][1:] if len(argv) > 2 and argv[2].startswith('?') else ''
	params = dict(parse_qsl(query))
	return params


def router(argv):
	import kodi_utils
	params = _parse_params(argv)
	mode = params.get('mode')
	try:
		import mdblist_public
		if not mode:
			mdblist_public.mdblist_public_menu(params)
			return
		func = getattr(mdblist_public, mode, None)
		if func is None:
			kodi_utils.logger('MDB Addon', 'Unknown mode: %s' % mode)
			return
		func(params)
	except Exception as e:
		kodi_utils.logger('MDB Addon', 'router error (mode=%s): %s' % (mode, e))
		try:
			handle = int(argv[1])
			kodi_utils.end_directory(handle)
		except:
			pass
