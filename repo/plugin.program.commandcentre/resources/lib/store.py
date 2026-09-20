# -*- coding: utf-8 -*-
"""JSON files in the addon's profile folder.

Writes are atomic (temp file + os.replace) so a power cut on the HTPC can't leave
a half-written file. A file that exists but can't be parsed is copied aside as
``<name>.corrupt-<time>`` before defaults are used, so a hand-edit typo never
gets silently overwritten by the next save.
"""
import copy
import json
import os
import shutil
import time

import xbmc

from .common import PROFILE_PATH, log

_cache = {}


def _path(name):
    return os.path.join(PROFILE_PATH, name)


def exists(name):
    return os.path.isfile(_path(name))


def load(name, default):
    """Parsed JSON for ``name``; ``default`` (a fresh copy) if missing, unreadable
    or of a different top-level type. The returned object is cached - mutate it
    only if you go on to save() it."""
    if name in _cache:
        return _cache[name]
    data = None
    path = _path(name)
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            if not isinstance(data, type(default)):
                raise ValueError('expected {}'.format(type(default).__name__))
        except Exception as exc:
            log('{} is unreadable ({}) - keeping a copy and using defaults'.format(
                name, exc), xbmc.LOGWARNING)
            _quarantine(path)
            data = None
    if data is None:
        data = copy.deepcopy(default)
    _cache[name] = data
    return data


def save(name, data):
    os.makedirs(PROFILE_PATH, exist_ok=True)
    path = _path(name)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
    _cache[name] = data


def delete(name):
    _cache.pop(name, None)
    try:
        os.remove(_path(name))
    except OSError:
        pass


def rename(name, new_name):
    _cache.pop(name, None)
    try:
        os.replace(_path(name), _path(new_name))
    except OSError:
        pass


def _quarantine(path):
    try:
        shutil.copyfile(path, '{}.corrupt-{}'.format(path, int(time.time())))
    except OSError as exc:
        log('could not back up {}: {}'.format(path, exc), xbmc.LOGWARNING)


def clear_cache():
    _cache.clear()
