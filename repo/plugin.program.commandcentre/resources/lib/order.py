# -*- coding: utf-8 -*-
"""Custom ordering (order.json) for the popup's sections and for the entries
within each section. Independent of visibility.json, so hiding never disturbs
order and vice versa."""
from . import store

ORDER_FILE = 'order.json'
HEADINGS_KEY = 'headings'
SHORTCUTS_KEY = 'shortcuts'


def _all():
    return store.load(ORDER_FILE, {})


def get_order(key, current_ids, first=(), after=None):
    """current_ids reordered per the saved order for ``key``: saved ids first (in
    saved order, dropping any that no longer exist), then ids never seen before.
    Never-seen ids listed in ``first`` go to the very front instead of the end
    (used so the new Recent section appears at the top for existing users). ``after``
    maps a never-seen id to the id it should follow (new Music/Picture sections go
    right after Video Addons rather than at the very end)."""
    saved = _all().get(key) or []
    current = list(current_ids)
    present = set(current)
    ordered = [i for i in saved if i in present]
    seen = set(ordered)
    new = [i for i in current if i not in seen]
    front = [i for i in new if i in first]
    rest = [i for i in new if i not in first]
    result = front + ordered + rest
    for new_id, anchor in (after or {}).items():
        if new_id in rest and anchor in result:
            result.remove(new_id)
            result.insert(result.index(anchor) + 1, new_id)
    return result


def set_order(key, ids):
    """Save ``ids`` as the order for ``key``. Previously saved ids that aren't in
    ``ids`` (hidden right now) are kept after them, so they aren't forgotten."""
    config = _all()
    ids = list(ids)
    listed = set(ids)
    preserved = [i for i in (config.get(key) or []) if i not in listed]
    config[key] = ids + preserved
    store.save(ORDER_FILE, config)


def move_id(key, visible_ids, entry_id, delta, first=(), after=None):
    """Move one entry up (delta -1) or down (+1) among the visible ids.
    Returns True if it moved."""
    ordered = get_order(key, visible_ids, first, after)
    if entry_id not in ordered:
        return False
    index = ordered.index(entry_id)
    target = index + delta
    if not 0 <= target < len(ordered):
        return False
    ordered[index], ordered[target] = ordered[target], ordered[index]
    set_order(key, ordered)
    return True


def replace_id(key, old_id, new_id):
    config = _all()
    ids = config.get(key)
    if ids and old_id in ids:
        config[key] = [new_id if i == old_id else i for i in ids]
        store.save(ORDER_FILE, config)


def discard_id(key, entry_id):
    config = _all()
    ids = config.get(key)
    if ids and entry_id in ids:
        config[key] = [i for i in ids if i != entry_id]
        store.save(ORDER_FILE, config)


def reset():
    store.save(ORDER_FILE, {})


def export():
    return {k: list(v) for k, v in _all().items()}


def replace_all(data):
    clean = {}
    for key, ids in (data or {}).items():
        if isinstance(key, str) and isinstance(ids, list):
            clean[key] = [i for i in ids if isinstance(i, str)]
    store.save(ORDER_FILE, clean)
