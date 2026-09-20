# -*- coding: utf-8 -*-
"""Small remembered state (state.json): the Recent list and the last focused entry."""
from . import store

STATE_FILE = 'state.json'
MAX_RECENT_KEPT = 15


def _state():
    data = store.load(STATE_FILE, {})
    data.setdefault('recent', [])
    return data


def get_recent():
    return [dict(e) for e in _state()['recent']
            if isinstance(e, dict) and e.get('action')]


def add_recent(name, icon, action, confirm=''):
    data = _state()
    entries = [e for e in data['recent'] if e.get('action') != action]
    entries.insert(0, {'name': name, 'icon': icon or '', 'action': action, 'confirm': confirm or ''})
    data['recent'] = entries[:MAX_RECENT_KEPT]
    store.save(STATE_FILE, data)


def remove_recent(action):
    data = _state()
    data['recent'] = [e for e in data['recent'] if e.get('action') != action]
    store.save(STATE_FILE, data)


def clear_recent():
    data = _state()
    data['recent'] = []
    store.save(STATE_FILE, data)


def get_last_focus():
    last = _state().get('last')
    if isinstance(last, dict) and last.get('section') and last.get('id') is not None:
        return (last['section'], last['id'])
    return None


def set_last_focus(section, entry_id):
    data = _state()
    if data.get('last') != {'section': section, 'id': entry_id}:
        data['last'] = {'section': section, 'id': entry_id}
        store.save(STATE_FILE, data)
