# -*- coding: utf-8 -*-
"""All the configuration flows. Reached three ways: the buttons in the addon's
settings (default.py passes a mode), the "Configure Command Centre..." row in the
popup (configure_main), and the per-item menu in the popup (edit_shortcut).
"""
import xbmcgui

from . import actions, addons, backup, browser, list_dialog, order, overrides, shortcuts, visibility
from . import system_actions
from .sections import PLACE_AFTER, RECENT, SECTION_KEYS, SECTION_LABELS
from .common import (ADDON, busy, get_nav_color, log_exception,
                     normalize_color, notify, tr)
from .strings import S

ERROR = xbmcgui.NOTIFICATION_ERROR


def _menu(title, options):
    """Loop a select dialog over [(label, callable)] until closed. A failing
    handler is logged and reported instead of killing the whole flow."""
    labels = [label for label, _ in options] + [tr(S.CLOSE)]
    while True:
        choice = xbmcgui.Dialog().select(title, labels)
        if choice < 0 or choice >= len(options):
            return
        try:
            options[choice][1]()
        except Exception:
            log_exception('configure: {}'.format(options[choice][0]))
            notify(tr(S.ERROR_GENERIC), ERROR)


def configure_main():
    _menu(tr(S.MENU_TITLE_MAIN), [
        (tr(S.SET_VIDEO), configure_video_addons),
        (tr(S.SET_MUSIC), configure_music_addons),
        (tr(S.SET_PICTURES), configure_picture_addons),
        (tr(S.SET_PROGRAM), configure_program_addons),
        (tr(S.SET_SYSTEM), configure_system_functions),
        (tr(S.SET_SHORTCUTS), configure_shortcuts),
        (tr(S.SET_ORDER), configure_menu_order),
        (tr(S.SET_COLOUR), configure_nav_color),
        (tr(S.SET_BACKUP), configure_backup),
    ])


# ---- visibility
def _configure_visibility_for(addon_type, title):
    discovered = addons.discover_unique(addon_type)
    if not discovered:
        notify(tr(S.NO_ADDONS_TYPE))
        return
    hidden = visibility.hidden_ids(addon_type)
    entries = [{'id': a['addonid'], 'label': overrides.name_of(a), 'checked': a['addonid'] not in hidden}
               for a in discovered]
    result = list_dialog.select_items(title, entries)
    if result is None:
        return  # cancelled
    visibility.apply_checked(addon_type, [a['addonid'] for a in discovered], result)
    notify(tr(S.VISIBLE_UPDATED))


def configure_video_addons():
    _configure_visibility_for(addons.VIDEO, tr(S.TITLE_VIDEO))


def configure_music_addons():
    _configure_visibility_for(addons.AUDIO, tr(S.TITLE_MUSIC))


def configure_picture_addons():
    _configure_visibility_for(addons.IMAGE, tr(S.TITLE_PICTURES))


def configure_program_addons():
    _configure_visibility_for(addons.EXECUTABLE, tr(S.TITLE_PROGRAM))


def configure_system_functions():
    hidden = visibility.hidden_ids(visibility.SYSTEM_KEY)
    entries = [{'id': a['id'], 'label': system_actions.label(a), 'checked': a['id'] not in hidden}
               for a in system_actions.SYSTEM_ACTIONS]
    result = list_dialog.select_items(tr(S.TITLE_SYSTEM), entries)
    if result is None:
        return
    visibility.apply_checked(visibility.SYSTEM_KEY,
                             [a['id'] for a in system_actions.SYSTEM_ACTIONS], result)
    notify(tr(S.SYSTEM_UPDATED))


# ---- highlight colour
def configure_nav_color():
    """Colour picker (Kodi 20+) or a typed hex code. Both routes go through
    normalize_color(), so what's stored is always a valid AARRGGBB."""
    current = get_nav_color()
    options = [tr(S.COLOUR_PICKER), tr(S.COLOUR_CODE)]
    choice = xbmcgui.Dialog().select(tr(S.COLOUR_MENU_TITLE), options)
    if choice == 0:
        dialog = xbmcgui.Dialog()
        if not hasattr(dialog, 'colorpicker'):  # added to Kodi's Python API in v20
            notify(tr(S.COLOUR_PICKER_UNAVAILABLE), ERROR)
            return
        chosen = dialog.colorpicker(tr(S.COLOUR_PICKER_HEADING), current)
        if chosen:
            _save_nav_color(chosen)
    elif choice == 1:
        entered = xbmcgui.Dialog().input(tr(S.COLOUR_INPUT_HEADING), defaultt=current,
                                         type=xbmcgui.INPUT_ALPHANUM)
        if entered:
            _save_nav_color(entered)


def _save_nav_color(value):
    normalized = normalize_color(value)
    if normalized is None:
        notify(tr(S.COLOUR_INVALID), ERROR)
        return
    ADDON.setSetting('nav_highlight_color', normalized)
    notify(tr(S.COLOUR_UPDATED))


# ---- order
def _visible_addon_entries(addon_type):
    hidden = visibility.hidden_ids(addon_type)
    return [{'id': a['addonid'], 'label': overrides.name_of(a)}
            for a in addons.discover_unique(addon_type) if a['addonid'] not in hidden]


def _visible_shortcut_entries():
    return [{'id': shortcuts.shortcut_key(s), 'label': s['name']}
            for s in shortcuts.filter_valid(shortcuts.load_shortcuts())]


def _visible_system_entries():
    hidden = visibility.hidden_ids(visibility.SYSTEM_KEY)
    return [{'id': a['id'], 'label': system_actions.label(a)}
            for a in system_actions.SYSTEM_ACTIONS if a['id'] not in hidden]


def configure_menu_order():
    _menu(tr(S.MENU_SET_ORDER), [
        (tr(S.ORDER_SECTIONS), lambda: _reorder_headings(SECTION_KEYS, SECTION_LABELS, RECENT)),
        (tr(S.ORDER_VIDEO), lambda: _reorder_section(
            addons.VIDEO, tr(S.SEC_VIDEO), lambda: _visible_addon_entries(addons.VIDEO))),
        (tr(S.ORDER_MUSIC), lambda: _reorder_section(
            addons.AUDIO, tr(S.SEC_MUSIC), lambda: _visible_addon_entries(addons.AUDIO))),
        (tr(S.ORDER_PICTURES), lambda: _reorder_section(
            addons.IMAGE, tr(S.SEC_PICTURES), lambda: _visible_addon_entries(addons.IMAGE))),
        (tr(S.ORDER_PROGRAM), lambda: _reorder_section(
            addons.EXECUTABLE, tr(S.SEC_PROGRAM), lambda: _visible_addon_entries(addons.EXECUTABLE))),
        (tr(S.ORDER_SHORTCUTS), lambda: _reorder_section(
            order.SHORTCUTS_KEY, tr(S.SEC_SHORTCUTS), _visible_shortcut_entries)),
        (tr(S.ORDER_SYSTEM), lambda: _reorder_section(
            visibility.SYSTEM_KEY, tr(S.SEC_SYSTEM), _visible_system_entries)),
    ])


def _reorder_headings(section_keys, labels, recent_key):
    ordered = order.get_order(order.HEADINGS_KEY, section_keys, first=(recent_key,), after=PLACE_AFTER)
    entries = [{'id': key, 'label': tr(labels[key])} for key in ordered]
    result = list_dialog.reorder_items(tr(S.ORDER_SECTIONS), entries)
    if result is None:
        return
    order.set_order(order.HEADINGS_KEY, result)
    notify(tr(S.SECTION_ORDER_UPDATED))


def _reorder_section(key, title, fetch_entries):
    """Reorder the entries currently shown in a section (hidden ones keep their
    saved place for when they are shown again)."""
    raw_entries = fetch_entries()
    if not raw_entries:
        notify(tr(S.NOTHING_TO_REORDER))
        return
    by_id = {e['id']: e for e in raw_entries}
    entries = [by_id[i] for i in order.get_order(key, list(by_id))]
    result = list_dialog.reorder_items(tr(S.SET_ORDER_FOR).format(title), entries)
    if result is None:
        return
    order.set_order(key, result)
    notify(tr(S.ORDER_UPDATED).format(title))


# ---- shortcuts
def configure_shortcuts():
    _menu(tr(S.MANAGE_SHORTCUTS), [
        (tr(S.SC_BROWSE), _add_browsed_shortcut),
        (tr(S.SC_SETTINGS), _add_settings_shortcut),
        (tr(S.SC_FAVOURITES), configure_favourites),
        (tr(S.SC_CUSTOM), _add_custom_shortcut),
        (tr(S.SC_EDIT), _edit_shortcut_flow),
        (tr(S.SC_REMOVE), _remove_shortcuts),
    ])


def configure_backup():
    _menu(tr(S.BACKUP_TITLE), [
        (tr(S.BK_EXPORT), backup.export_backup),
        (tr(S.BK_IMPORT), backup.import_backup),
        (tr(S.BK_RESET), backup.reset_menu),
    ])


def _pick_addon(prompt, candidates):
    if not candidates:
        notify(tr(S.NO_ADDONS))
        return None
    index = xbmcgui.Dialog().select(prompt, [a['name'] for a in candidates])
    return candidates[index] if index >= 0 else None


def _save_new_shortcut(label, icon, action):
    if shortcuts.add_shortcut(label, icon, action):
        notify(tr(S.SHORTCUT_ADDED))
    else:
        notify(tr(S.SHORTCUT_EXISTS))


def _add_browsed_shortcut():
    """Drill into an addon's menus and pick any page or item."""
    with busy():
        candidates = addons.browsable()
    chosen = _pick_addon(tr(S.BROWSE_WHICH), candidates)
    if chosen is None:
        return
    picked = browser.browse_and_pick(chosen)
    if picked is None:
        return
    if picked['is_folder']:
        action = actions.open_folder(chosen['window'], picked['url'])
    else:
        # Kodi can't tell us whether a non-folder is playable or a plugin action.
        what = xbmcgui.Dialog().select(tr(S.PLAY_OR_RUN), [tr(S.OPT_PLAY), tr(S.OPT_RUN)])
        if what < 0:
            return
        action = actions.play(picked['url']) if what == 0 else actions.run_plugin(picked['url'])
    label = xbmcgui.Dialog().input(tr(S.SHORTCUT_LABEL), defaultt=picked['label'])
    if label:
        _save_new_shortcut(label, chosen.get('thumbnail', ''), action)


def _add_settings_shortcut():
    with busy():
        candidates = addons.with_settings()
    if not candidates:
        notify(tr(S.NO_SETTINGS_ADDONS))
        return
    chosen = _pick_addon(tr(S.SETTINGS_WHICH), candidates)
    if chosen is None:
        return
    label = xbmcgui.Dialog().input(tr(S.SHORTCUT_LABEL), defaultt=tr(S.SETTINGS_SUFFIX).format(chosen['name']))
    if label:
        _save_new_shortcut(label, chosen.get('thumbnail', ''),
                           'Addon.OpenSettings({})'.format(chosen['addonid']))


def _add_custom_shortcut():
    label = xbmcgui.Dialog().input(tr(S.SHORTCUT_LABEL))
    if not label:
        return
    action = xbmcgui.Dialog().input(tr(S.CUSTOM_ACTION))
    if action:
        _save_new_shortcut(label, '', action)


def configure_favourites():
    """Import Kodi Favourites as shortcuts (no typing on a remote)."""
    favourites = shortcuts.read_favourites()
    if not favourites:
        notify(tr(S.NO_FAVOURITES))
        return
    entries = [{'id': i, 'label': f['name'], 'checked': False} for i, f in enumerate(favourites)]
    result = list_dialog.select_items(tr(S.SELECT_FAVOURITES), entries, accept_label=tr(S.ADD))
    if not result:
        return
    added = sum(1 for i in result
                if shortcuts.add_shortcut(favourites[i]['name'], favourites[i]['icon'],
                                          favourites[i]['action']))
    notify(tr(S.SHORTCUTS_ADDED_N).format(added))


def _labelled_shortcuts():
    """[(entry, label)] for every stored shortcut, flagging ones whose addon is gone."""
    entries = shortcuts.load_shortcuts()
    enabled = addons.enabled_ids() if any(
        shortcuts.extract_addon_id(e['action']) for e in entries) else set()
    return [(e, e['name'] if shortcuts.is_valid(e, enabled)
             else '{} {}'.format(e['name'], tr(S.MISSING_ADDON))) for e in entries]


def _remove_shortcuts():
    labelled = _labelled_shortcuts()
    if not labelled:
        notify(tr(S.NO_SHORTCUTS))
        return
    entries = [{'id': shortcuts.shortcut_key(e), 'label': label, 'checked': False}
               for e, label in labelled]
    result = list_dialog.select_items(tr(S.SELECT_TO_REMOVE), entries, accept_label=tr(S.REMOVE))
    if not result:
        return  # cancelled, or nothing ticked
    if not xbmcgui.Dialog().yesno(tr(S.SC_REMOVE), tr(S.CONFIRM_REMOVE).format(len(result))):
        return
    removed = shortcuts.remove_shortcuts(result)
    notify(tr(S.SHORTCUTS_REMOVED).format(removed))


def _edit_shortcut_flow():
    labelled = _labelled_shortcuts()
    if not labelled:
        notify(tr(S.NO_SHORTCUTS))
        return
    index = xbmcgui.Dialog().select(tr(S.SC_EDIT_WHICH), [label for _, label in labelled])
    if index >= 0:
        edit_shortcut(shortcuts.shortcut_key(labelled[index][0]))


def edit_shortcut(key):
    """Rename / change icon / change action of one shortcut. Returns its (possibly
    new) key, or None if nothing changed."""
    entry = next((e for e in shortcuts.load_shortcuts() if shortcuts.shortcut_key(e) == key), None)
    if entry is None:
        return None
    what = xbmcgui.Dialog().select(entry['name'], [
        tr(S.EDIT_RENAME), tr(S.EDIT_ICON), tr(S.EDIT_ACTION)])
    changes = {}
    if what == 0:
        value = xbmcgui.Dialog().input(tr(S.SHORTCUT_LABEL), defaultt=entry['name'])
        if value:
            changes['name'] = value
    elif what == 1:
        icon = _pick_icon(entry['icon'])
        if icon is not None:
            changes['icon'] = icon
    elif what == 2:
        value = xbmcgui.Dialog().input(tr(S.CUSTOM_ACTION), defaultt=entry['action'])
        if value:
            changes['action'] = value
    if not changes:
        return None
    new_key, status = shortcuts.update_shortcut(key, **changes)
    if status == 'duplicate':
        notify(tr(S.SHORTCUT_EXISTS))
        return None
    notify(tr(S.SHORTCUT_UPDATED))
    return new_key


def rename_addon(addon_id, original_name, current_name):
    """Give an addon listed in the popup a different display name (its own name = undo)."""
    value = xbmcgui.Dialog().input(tr(S.EDIT_RENAME), defaultt=current_name)
    if not value or not value.strip():
        return False
    overrides.set_name(addon_id, original_name, value)
    notify(tr(S.SHORTCUT_UPDATED))
    return True


def change_addon_icon(addon_id, current_icon):
    """Pick a different icon for an addon listed in the popup ('default' = undo)."""
    icon = _pick_icon(current_icon)
    if icon is None:
        return False
    overrides.set_icon(addon_id, icon)
    notify(tr(S.SHORTCUT_UPDATED))
    return True


def _pick_icon(current):
    """A new icon path, '' for the default icon, or None if cancelled/unchanged."""
    choice = xbmcgui.Dialog().select(tr(S.EDIT_ICON), [tr(S.ICON_CHOOSE), tr(S.ICON_DEFAULT)])
    if choice == 1:
        return ''
    if choice == 0:
        path = xbmcgui.Dialog().browseSingle(2, tr(S.ICON_HEADING), 'files', '', False, False, current)
        if path and path != current:
            return path
    return None
