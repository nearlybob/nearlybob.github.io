# -*- coding: utf-8 -*-
"""
Handlers for the settings.xml action buttons. Each is invoked via
RunScript(plugin.program.commandcentre, <mode>) — RunScript passes
extra parameters through sys.argv, which default.py reads to route
here instead of opening the popup dialog.

Uses selection_dialog.select_items() (our own WindowXMLDialog) rather
than Kodi's native xbmcgui.Dialog().multiselect(), because the native
dialog's checkbox styling is controlled by whatever skin is active
and can be hard to read (confirmed — this is why it was replaced).
"""
import xbmcgui
import xbmcaddon

import addon_discovery
import shortcuts_manager
import system_actions
import selection_dialog
import reorder_dialog
import order_manager
import addon_browser

DEFAULT_NAV_HIGHLIGHT_COLOR = 'FFFFFFFF'


def _configure_visibility_for(addon_type, title):
    discovered = addon_discovery.discover_addons(addon_type)
    if not discovered:
        xbmcgui.Dialog().notification(
            'Command Centre', 'No addons of this type found', xbmcgui.NOTIFICATION_INFO)
        return

    chosen_ids = addon_discovery.get_chosen_ids(addon_type)
    entries = [
        {
            'id': a.get('addonid'),
            'label': a.get('name') or a.get('addonid'),
            'checked': True if chosen_ids is None else a.get('addonid') in chosen_ids,
        }
        for a in discovered
    ]

    result = selection_dialog.select_items(title, entries)
    if result is None:
        return  # cancelled, leave existing config untouched
    addon_discovery.set_visible_addon_ids(addon_type, result)
    xbmcgui.Dialog().notification(
        'Command Centre', 'Visible addons updated', xbmcgui.NOTIFICATION_INFO)


def configure_video_addons():
    _configure_visibility_for(addon_discovery.VIDEO_ADDON_TYPE,
                               'Choose visible Video Addons')


def configure_program_addons():
    _configure_visibility_for(addon_discovery.PROGRAM_ADDON_TYPE,
                               'Choose visible Program Addons')


def configure_system_functions():
    chosen_ids = addon_discovery.get_chosen_ids(system_actions.SYSTEM_KEY)
    entries = [
        {
            'id': a['id'],
            'label': a['name'],
            'checked': True if chosen_ids is None else a['id'] in chosen_ids,
        }
        for a in system_actions.SYSTEM_ACTIONS
    ]

    result = selection_dialog.select_items('Choose visible System functions', entries)
    if result is None:
        return
    system_actions.set_visible_system_ids(result)
    xbmcgui.Dialog().notification(
        'Command Centre', 'System functions updated', xbmcgui.NOTIFICATION_INFO)


def configure_nav_color():
    """Offers a choice between Kodi's built-in colour-picker dialog
    (xbmcgui.Dialog().colorpicker, available since Kodi 20 Nexus) and typing
    an exact colour code. The two are kept separate rather than relying on
    a "manual entry" option inside the picker itself: whether that picker
    even offers manual hex entry depends on the active Kodi skin's own
    DialogColorPicker.xml, which isn't guaranteed — asking directly via
    Dialog().input() works the same regardless of which skin is active.
    Either way the result is stored as an addon setting; dialog.py reads it
    back on each popup open and passes it to the skin as a Window property,
    since the highlight bar's colour is read dynamically from there rather
    than being hardcoded in the XML."""
    addon = xbmcaddon.Addon()
    current = addon.getSetting('nav_highlight_color') or DEFAULT_NAV_HIGHLIGHT_COLOR
    options = ['Choose from colour picker', 'Enter a colour code (e.g. FF00A2ED)']
    choice = xbmcgui.Dialog().select('Navigation highlight colour', options)
    if choice == 0:
        chosen = xbmcgui.Dialog().colorpicker('Select navigation highlight colour', current)
        if not chosen:
            return  # cancelled
        _save_nav_color(addon, chosen)
    elif choice == 1:
        _configure_nav_color_by_code(addon, current)
    # choice == -1: cancelled the picker-vs-code menu itself


def _configure_nav_color_by_code(addon, current):
    entered = xbmcgui.Dialog().input(
        'Colour code (6 hex digits e.g. 00A2ED, or 8 with alpha e.g. FF00A2ED)',
        defaultt=current, type=xbmcgui.INPUT_ALPHANUM)
    if not entered:
        return  # cancelled
    normalized = _normalize_hex_color(entered)
    if normalized is None:
        xbmcgui.Dialog().notification(
            'Command Centre', 'Not a valid colour code', xbmcgui.NOTIFICATION_ERROR)
        return
    _save_nav_color(addon, normalized)


def _normalize_hex_color(value):
    """Accepts 6 hex digits (RRGGBB, treated as fully opaque) or 8
    (AARRGGBB); returns the normalized 8-digit AARRGGBB form Kodi's
    colordiffuse expects, or None if value is not valid hex of one
    of those two lengths."""
    s = (value or '').strip().lstrip('#')
    if len(s) not in (6, 8):
        return None
    try:
        int(s, 16)
    except ValueError:
        return None
    return ('FF' + s) if len(s) == 6 else s


def _save_nav_color(addon, hex_value):
    addon.setSetting('nav_highlight_color', hex_value)
    xbmcgui.Dialog().notification(
        'Command Centre', 'Highlight colour updated', xbmcgui.NOTIFICATION_INFO)


def configure_menu_order():
    while True:
        options = ['Set order for sections',
                    'Set order for Video Addons',
                    'Set order for Program Addons',
                    'Set order for Shortcuts',
                    'Set order for System functions',
                    'Close']
        choice = xbmcgui.Dialog().select('Set Menu Order', options)
        if choice in (-1, 5):
            return
        elif choice == 0:
            _reorder_headings()
        elif choice == 1:
            _reorder_section(
                addon_discovery.VIDEO_ADDON_TYPE, 'Video Addons',
                lambda: [{'id': a.get('addonid'), 'label': a.get('name') or a.get('addonid')}
                         for a in addon_discovery.get_visible_addons(addon_discovery.VIDEO_ADDON_TYPE)])
        elif choice == 2:
            _reorder_section(
                addon_discovery.PROGRAM_ADDON_TYPE, 'Program Addons',
                lambda: [{'id': a.get('addonid'), 'label': a.get('name') or a.get('addonid')}
                         for a in addon_discovery.get_visible_addons(addon_discovery.PROGRAM_ADDON_TYPE)])
        elif choice == 3:
            _reorder_section(
                order_manager.SHORTCUTS_KEY, 'Shortcuts',
                lambda: [{'id': shortcuts_manager.shortcut_key(s), 'label': s.get('name', '')}
                         for s in shortcuts_manager.get_valid_shortcuts()])
        elif choice == 4:
            _reorder_section(
                system_actions.SYSTEM_KEY, 'System functions',
                lambda: [{'id': a['id'], 'label': a['name']}
                         for a in system_actions.get_visible_system_actions()])


def _reorder_headings():
    entries = [
        {'id': key, 'label': order_manager.SECTION_LABELS[key]}
        for key in order_manager.get_order(order_manager.HEADINGS_KEY, order_manager.SECTION_KEYS)
    ]
    result = reorder_dialog.reorder_items('Set order for sections', entries)
    if result is None:
        return  # cancelled
    order_manager.set_order(order_manager.HEADINGS_KEY, result)
    xbmcgui.Dialog().notification(
        'Command Centre', 'Section order updated', xbmcgui.NOTIFICATION_INFO)


def _reorder_section(key, title, fetch_entries):
    """fetch_entries: zero-arg callable returning the section's
    current [{'id':..., 'label':...}, ...] (only the currently
    *visible* entries — reordering something that isn't shown in
    the popup would be confusing, and get_order already leaves a
    hidden entry's saved position untouched for if it's re-shown
    later)."""
    raw_entries = fetch_entries()
    if not raw_entries:
        xbmcgui.Dialog().notification(
            'Command Centre', 'Nothing to reorder', xbmcgui.NOTIFICATION_INFO)
        return
    ordered_ids = order_manager.get_order(key, [e['id'] for e in raw_entries])
    by_id = {e['id']: e for e in raw_entries}
    entries = [by_id[i] for i in ordered_ids if i in by_id]

    result = reorder_dialog.reorder_items('Set order for {}'.format(title), entries)
    if result is None:
        return  # cancelled
    order_manager.set_order(key, result)
    xbmcgui.Dialog().notification(
        'Command Centre', '{} order updated'.format(title), xbmcgui.NOTIFICATION_INFO)


def configure_shortcuts():
    while True:
        options = ['Browse an addon to pick a shortcut',
                    'Add shortcut to an addon\'s settings page',
                    'Add custom shortcut (advanced)',
                    'Remove shortcuts',
                    'Close']
        choice = xbmcgui.Dialog().select('Manage Shortcuts', options)
        if choice in (-1, 4):
            return
        elif choice == 0:
            _add_browsed_shortcut()
        elif choice == 1:
            _add_settings_shortcut()
        elif choice == 2:
            _add_custom_shortcut()
        elif choice == 3:
            _remove_shortcuts()


def _pick_any_addon(prompt):
    """Shared by the two 'pick any installed addon' flows below.
    Returns the chosen addon dict, or None if there are none or the
    user cancelled."""
    all_addons = (addon_discovery.discover_addons(addon_discovery.VIDEO_ADDON_TYPE) +
                  addon_discovery.discover_addons(addon_discovery.PROGRAM_ADDON_TYPE))
    if not all_addons:
        xbmcgui.Dialog().notification(
            'Command Centre', 'No addons found', xbmcgui.NOTIFICATION_INFO)
        return None
    names = [a.get('name') or a.get('addonid') for a in all_addons]
    index = xbmcgui.Dialog().select(prompt, names)
    if index < 0:
        return None
    return all_addons[index]


def _add_browsed_shortcut():
    """Lets the user drill into an addon's own menu structure — the
    same way Nimbus's widget picker works — and pick any page as the
    shortcut target, rather than only the addon's top level."""
    chosen = _pick_any_addon('Browse which addon?')
    if chosen is None:
        return
    picked = addon_browser.browse_and_pick(
        chosen.get('addonid'), chosen.get('name') or chosen.get('addonid'))
    if picked is None:
        return
    picked_label, picked_url = picked
    label = xbmcgui.Dialog().input('Shortcut label', defaultt=picked_label)
    if not label:
        return
    _save_new_shortcut(label, chosen.get('thumbnail', ''), picked_url)


def _add_settings_shortcut():
    chosen = _pick_any_addon('Open settings for which addon?')
    if chosen is None:
        return
    default_label = '{} - Settings'.format(chosen.get('name') or chosen.get('addonid'))
    label = xbmcgui.Dialog().input('Shortcut label', defaultt=default_label)
    if not label:
        return
    action = 'Addon.OpenSettings({})'.format(chosen.get('addonid'))
    _save_new_shortcut(label, chosen.get('thumbnail', ''), action)


def _add_custom_shortcut():
    label = xbmcgui.Dialog().input('Shortcut label')
    if not label:
        return
    action = xbmcgui.Dialog().input(
        'Action (e.g. a plugin:// URL or a Kodi built-in function)')
    if not action:
        return
    _save_new_shortcut(label, '', action)


def _save_new_shortcut(label, icon, action):
    added = shortcuts_manager.add_shortcut(label, icon, action)
    if added:
        xbmcgui.Dialog().notification('Command Centre', 'Shortcut added', xbmcgui.NOTIFICATION_INFO)
    else:
        xbmcgui.Dialog().notification(
            'Command Centre', 'That shortcut already exists', xbmcgui.NOTIFICATION_INFO)


def _remove_shortcuts():
    """Bulk removal via the same checkbox-style selection dialog:
    everything starts unchecked, and whatever's left checked when
    Save is pressed gets removed — so removing several no longer
    means repeating the whole flow one at a time."""
    shortcuts = shortcuts_manager.load_shortcuts()
    if not shortcuts:
        xbmcgui.Dialog().notification(
            'Command Centre', 'No shortcuts to remove', xbmcgui.NOTIFICATION_INFO)
        return

    entries = [
        {'id': i, 'label': s.get('name', ''), 'checked': False}
        for i, s in enumerate(shortcuts)
    ]
    result = selection_dialog.select_items('Select shortcuts to remove', entries)
    if not result:
        return  # cancelled, or nothing was checked
    shortcuts_manager.remove_shortcuts(result)
    xbmcgui.Dialog().notification(
        'Command Centre', '{} shortcut(s) removed'.format(len(result)),
        xbmcgui.NOTIFICATION_INFO)
