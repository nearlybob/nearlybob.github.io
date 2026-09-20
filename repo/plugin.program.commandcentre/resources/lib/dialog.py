# -*- coding: utf-8 -*-
"""Command Centre - the popup.

Section headings are real list rows (row_type='header'), because a Kodi <list>
evaluates <itemlayout> conditions once per build, not per row, so every row must
share one height. Headers therefore must never stay selected: after every action
_fix_selection() nudges the selection off a header (and wraps top<->bottom on
Up/Down whichever way Kodi itself handled the key), which also covers PageUp/Down,
Home/End, the mouse wheel and hovering.

Each item row carries: action (built-in to run), section, entry_id, confirm.
The context key (or right-click / long-press) on an item opens a small menu to
move it, hide it, or edit/remove it, then the list is rebuilt in place.
"""
import time

import xbmc
import xbmcgui

import re

from . import actions, addons, order, overrides, shortcuts, state, system_actions, visibility
from .sections import (CONFIGURE_SECTION, MUSIC_SECTION, PICTURES_SECTION, PLACE_AFTER,
                       PROGRAM_SECTION, RECENT, SECTION_KEYS, SECTION_LABELS,
                       SHORTCUTS_SECTION, SYSTEM_SECTION, VIDEO_SECTION)
from .common import (ACTION_MOVE_DOWN, ACTION_MOVE_UP, ADDON_NAME, ADDON_PATH,
                     CLOSE_ACTIONS, CONTEXT_ACTIONS, DEFAULT_ICON, focus_id, get_bool_setting,
                     get_int_setting, get_nav_color, is_light_color, log_exception, notify, tr)
from .strings import S

CONTROL_LIST = 5001
CONTROL_PANEL = 5000        # the group holding background, list and scrollbar
CONTROL_BACKGROUND = 5003

# Layout (1080i skin units) - must match command_center.xml.
SCREEN_HEIGHT = 1080
PANEL_X = 460
ROW_HEIGHT = 56
PANEL_PADDING = 12
MAX_ROWS = 18               # 18 x 56 + 2 x 12 = 1032: 24px above and below at full size
INTERNAL_CONFIGURE = 'internal:configure'

# Key each section's item order (and hide-list) is stored under.
ADDON_SECTION_TYPES = {VIDEO_SECTION: addons.VIDEO, MUSIC_SECTION: addons.AUDIO,
                       PICTURES_SECTION: addons.IMAGE, PROGRAM_SECTION: addons.EXECUTABLE}
ORDER_KEYS = dict(ADDON_SECTION_TYPES)
ORDER_KEYS.update({SHORTCUTS_SECTION: order.SHORTCUTS_KEY, SYSTEM_SECTION: visibility.SYSTEM_KEY})
HIDE_KEYS = dict(ADDON_SECTION_TYPES)
HIDE_KEYS[SYSTEM_SECTION] = visibility.SYSTEM_KEY


def panel_geometry(row_count):
    """(panel height, top edge) for a popup showing ``row_count`` rows, centred on the screen."""
    rows = max(1, min(row_count, MAX_ROWS))
    height = rows * ROW_HEIGHT + 2 * PANEL_PADDING
    return height, (SCREEN_HEIGHT - height) // 2


def _addon_entry(a):
    name, icon = overrides.display(a['addonid'], a['name'], a.get('thumbnail') or DEFAULT_ICON)
    return {'id': a['addonid'], 'name': name, 'icon': icon,
            'action': 'RunAddon({})'.format(a['addonid'])}


class CommandCenterDialog(xbmcgui.WindowXMLDialog):

    def __init__(self, *args, **kwargs):
        super(CommandCenterDialog, self).__init__(*args, **kwargs)
        self._list = None
        self._first_item_index = 0
        self._last_position = 0
        self._section_keys = []   # sections currently shown (no Configure), in order
        self._section_ids = {}    # section key -> entry ids currently shown, in order
        self._ctx_block_until = 0.0
        self.launch = None        # built-in to run once the popup has closed

    # ---- building the list
    def onInit(self):
        # Window property (not a skin variable): $INFO[Window.Property(...)] with no
        # window id resolves to this script-owned window, which is how the highlight
        # colour reaches the XML.
        nav_color = get_nav_color()
        self.setProperty('nav_highlight_color', nav_color)
        self.setProperty('nav_highlight_is_light', 'true' if is_light_color(nav_color) else 'false')
        self._list = self.getControl(CONTROL_LIST)
        try:
            self._populate(focus=state.get_last_focus())
        except Exception:
            log_exception('building the popup')
            notify(tr(S.POPUP_ERROR), xbmcgui.NOTIFICATION_ERROR)
            self.close()

    def _populate(self, focus=None):
        """(Re)build the list. ``focus`` = (section, entry_id) to select afterwards."""
        rows = []
        first_item = None
        focus_index = None
        self._section_keys = []
        self._section_ids = {}

        for key, heading, entries in self._gather_sections():
            if not entries:
                continue
            header = xbmcgui.ListItem(label=heading.upper())
            header.setProperty('row_type', 'header')
            rows.append(header)
            if key != CONFIGURE_SECTION:
                self._section_keys.append(key)
                self._section_ids[key] = [e['id'] for e in entries]
            for entry in entries:
                item = xbmcgui.ListItem(label=entry['name'])
                item.setArt({'icon': entry.get('icon') or DEFAULT_ICON})
                item.setProperty('row_type', 'item')
                item.setProperty('action', entry['action'])
                item.setProperty('section', key)
                item.setProperty('entry_id', entry['id'])
                item.setProperty('confirm', entry.get('confirm') or '')
                if first_item is None:
                    first_item = len(rows)
                if focus_index is None and focus == (key, entry['id']):
                    focus_index = len(rows)
                rows.append(item)

        if first_item is None:
            # Configure row switched off and everything else hidden/empty.
            notify(tr(S.NOTHING_TO_SHOW))
            self.close()
            return
        self._list.reset()
        for row in rows:
            self._list.addItem(row)
        self._first_item_index = first_item
        position = focus_index if focus_index is not None else self._first_item_index
        self._list.selectItem(position)
        self._last_position = position
        self._fit_panel(len(rows))
        self.setFocus(self._list)

    def _fit_panel(self, row_count):
        """Shrink the background to fit ``row_count`` rows and keep the panel vertically centred; from
        MAX_ROWS rows up it stays at the full size defined in the XML and the list scrolls. The list keeps
        its full-size (transparent) area, so item layout and scrolling are never touched. Purely cosmetic:
        if Kodi refuses, the full-size XML layout simply stays."""
        if not get_bool_setting('fit_popup_height', True):
            return
        height, top = panel_geometry(row_count)
        try:
            self.getControl(CONTROL_PANEL).setPosition(PANEL_X, top)
            self.getControl(CONTROL_BACKGROUND).setHeight(height)
        except Exception:
            log_exception('resizing the popup')

    def _gather_sections(self):
        # Every enabled addon of these types (before hiding), used to skip a JSON-RPC
        # call when validating shortcuts/recent entries that point at one of them.
        known = set()
        for addon_type in addons.BROWSABLE_TYPES:
            known.update(a['addonid'] for a in addons.discover(addon_type))

        by_section = {}
        for section, addon_type in ADDON_SECTION_TYPES.items():
            hidden = visibility.hidden_ids(addon_type)
            by_section[section] = self._ordered(addon_type, [
                _addon_entry(a) for a in addons.discover_unique(addon_type)
                if a['addonid'] not in hidden])

        hidden_system = visibility.hidden_ids(visibility.SYSTEM_KEY)
        by_section[SHORTCUTS_SECTION] = self._ordered(order.SHORTCUTS_KEY, [
            {'id': shortcuts.shortcut_key(s), 'name': s['name'], 'icon': s['icon'],
             'action': s['action']}
            for s in shortcuts.filter_valid(shortcuts.load_shortcuts(), known)])
        by_section[SYSTEM_SECTION] = self._ordered(visibility.SYSTEM_KEY, [
            {'id': a['id'], 'name': system_actions.label(a), 'icon': a['icon'],
             'action': a['action'], 'confirm': system_actions.confirm_text(a)}
            for a in system_actions.SYSTEM_ACTIONS if a['id'] not in hidden_system])
        by_section[RECENT] = self._recent_entries(known)

        section_order = order.get_order(order.HEADINGS_KEY, SECTION_KEYS,
                                        first=(RECENT,), after=PLACE_AFTER)
        sections = [(key, tr(SECTION_LABELS[key]), by_section[key]) for key in section_order]
        if get_bool_setting('show_configure_row', True):
            sections.append((CONFIGURE_SECTION, tr(SECTION_LABELS[CONFIGURE_SECTION]), [
                {'id': CONFIGURE_SECTION, 'name': tr(S.CONFIGURE_ROW),
                 'icon': 'DefaultAddonService.png', 'action': INTERNAL_CONFIGURE}]))
        return sections

    @staticmethod
    def _recent_entries(known):
        if not get_bool_setting('show_recent', True):
            return []
        limit = max(1, min(get_int_setting('recent_count', 5), state.MAX_RECENT_KEPT))
        valid = shortcuts.filter_valid(state.get_recent(), known)[:limit]
        entries = []
        for e in valid:
            name, icon = e['name'], e['icon']
            match = re.match(r'^RunAddon\((.+)\)$', e['action'])
            if match:  # keep a renamed / re-iconed addon consistent in Recent too
                name, icon = overrides.display(match.group(1), name, icon)
            entries.append({'id': e['action'], 'name': name, 'icon': icon, 'action': e['action'],
                            'confirm': e.get('confirm', '')})
        return entries

    @staticmethod
    def _ordered(key, entries):
        by_id = {e['id']: e for e in entries}
        return [by_id[i] for i in order.get_order(key, [e['id'] for e in entries])]

    # ---- selecting / launching
    def _selected_item(self):
        item = self._list.getSelectedItem()
        if item is None or item.getProperty('row_type') != 'item':
            return None
        return item

    def _remember_focus(self):
        item = self._selected_item()
        if item is not None and item.getProperty('section') != CONFIGURE_SECTION:
            try:
                state.set_last_focus(item.getProperty('section'), item.getProperty('entry_id'))
            except Exception:
                log_exception('saving last position')

    def onClick(self, control_id):
        if control_id != CONTROL_LIST:
            return
        item = self._selected_item()
        if item is None:
            return
        action = item.getProperty('action')
        if not action:
            return

        if action == INTERNAL_CONFIGURE:
            self._configure()
            return

        confirm = item.getProperty('confirm')
        if confirm and not xbmcgui.Dialog().yesno(ADDON_NAME, confirm):
            return

        self._remember_focus()
        try:
            state.add_recent(item.getLabel(), item.getArt('icon'), action, confirm)
        except Exception:
            log_exception('saving recent entry')
        self.launch = action  # run by open_command_center() after the popup has fully closed
        self.close()

    def _configure(self):
        from . import settings_actions  # lazy: only needed when configuring
        try:
            settings_actions.configure_main()
        except Exception:
            log_exception('configure menu')
            notify(tr(S.ERROR_GENERIC), xbmcgui.NOTIFICATION_ERROR)
        addons.clear_cache()
        self._populate(focus=(CONFIGURE_SECTION, CONFIGURE_SECTION))  # show the changes

    # ---- keys
    def onAction(self, action):
        action_id = action.getId()
        if action_id in CLOSE_ACTIONS:
            self._remember_focus()
            self.close()
            return
        if action_id in CONTEXT_ACTIONS:
            self._show_item_menu()
            return
        if focus_id(self) == CONTROL_LIST:
            self._fix_selection(action_id)

    def _is_header(self, position):
        return self._list.getListItem(position).getProperty('row_type') == 'header'

    def _fix_selection(self, action_id):
        """Keep the selection on real items and wrap at the ends. Runs after Kodi has
        already moved the selection for this action."""
        size = self._list.size()
        if size == 0:
            return
        position = self._list.getSelectedPosition()
        if not 0 <= position < size:
            return
        if action_id == ACTION_MOVE_UP:
            direction = -1
        elif action_id == ACTION_MOVE_DOWN:
            direction = 1
        else:  # page keys, wheel, hover...: infer the direction from where we were
            direction = -1 if position < self._last_position else 1

        # Down on the very last row that Kodi left in place (it did not wrap itself):
        # wrap to the top. (If Kodi did wrap, position is already 0 - a header - and
        # the header scan below lands on the first item.)
        if action_id == ACTION_MOVE_DOWN and position == size - 1 == self._last_position:
            position = 0

        if self._is_header(position):
            scan = position + direction
            while 0 <= scan < size and self._is_header(scan):
                scan += direction
            if 0 <= scan < size:
                position = scan
            elif direction < 0:
                position = size - 1              # Up past the first item: wrap to the last row
            else:
                position = self._first_item_index

        if position != self._list.getSelectedPosition():
            self._list.selectItem(position)
        self._last_position = position

    # ---- per-item menu (context key / right-click / long-press)
    def _show_item_menu(self):
        if time.time() < self._ctx_block_until:
            return  # a duplicate event queued behind the menu that was just closed
        item = self._selected_item()
        if item is None:
            return
        section = item.getProperty('section')
        entry_id = item.getProperty('entry_id')
        if section == CONFIGURE_SECTION:
            return

        options = []  # [(label, handler)]; handler returns the (section, id) to select
        if section == RECENT:
            options.append((tr(S.REMOVE_FROM_RECENT), lambda: self._remove_recent(entry_id)))
        else:
            options.append((tr(S.MOVE_UP), lambda: self._move(section, entry_id, -1)))
            options.append((tr(S.MOVE_DOWN), lambda: self._move(section, entry_id, 1)))
        if len(self._section_keys) > 1:
            options.append((tr(S.MOVE_SECTION_UP), lambda: self._move_section(section, entry_id, -1)))
            options.append((tr(S.MOVE_SECTION_DOWN), lambda: self._move_section(section, entry_id, 1)))
        if section in ADDON_SECTION_TYPES:
            options.append((tr(S.EDIT_RENAME), lambda: self._rename_addon(section, entry_id, item.getLabel())))
            options.append((tr(S.EDIT_ICON), lambda: self._change_addon_icon(section, entry_id, item.getArt('icon'))))
        if section in HIDE_KEYS:
            options.append((tr(S.HIDE), lambda: self._hide(section, entry_id)))
        if section == SHORTCUTS_SECTION:
            options.append((tr(S.EDIT), lambda: self._edit_shortcut(entry_id)))
            options.append((tr(S.REMOVE), lambda: self._remove_shortcut(entry_id, item.getLabel())))

        choice = xbmcgui.Dialog().contextmenu([label for label, _ in options])
        self._ctx_block_until = time.time() + 0.6
        if choice < 0:
            return
        try:
            focus = options[choice][1]()
        except Exception:
            log_exception('item menu')
            notify(tr(S.ERROR_GENERIC), xbmcgui.NOTIFICATION_ERROR)
            focus = None
        self._populate(focus=focus or (section, entry_id))

    def _neighbour(self, section, entry_id):
        ids = self._section_ids.get(section, [])
        if entry_id in ids and len(ids) > 1:
            index = ids.index(entry_id)
            return (section, ids[index + 1] if index + 1 < len(ids) else ids[index - 1])
        return None

    def _move(self, section, entry_id, delta):
        order.move_id(ORDER_KEYS[section], self._section_ids[section], entry_id, delta)
        return (section, entry_id)

    def _move_section(self, section, entry_id, delta):
        order.move_id(order.HEADINGS_KEY, self._section_keys, section, delta,
                      first=(RECENT,), after=PLACE_AFTER)
        return (section, entry_id)

    def _hide(self, section, entry_id):
        visibility.hide(HIDE_KEYS[section], entry_id)
        return self._neighbour(section, entry_id)

    @staticmethod
    def _original_name(section, addon_id):
        for a in addons.discover_unique(ADDON_SECTION_TYPES[section]):
            if a['addonid'] == addon_id:
                return a['name']
        return addon_id

    def _rename_addon(self, section, addon_id, current_name):
        from . import settings_actions
        settings_actions.rename_addon(addon_id, self._original_name(section, addon_id), current_name)
        return (section, addon_id)

    def _change_addon_icon(self, section, addon_id, current_icon):
        from . import settings_actions
        settings_actions.change_addon_icon(addon_id, current_icon)
        return (section, addon_id)

    def _remove_recent(self, action):
        neighbour = self._neighbour(RECENT, action)
        state.remove_recent(action)
        return neighbour

    def _remove_shortcut(self, key, name):
        if not xbmcgui.Dialog().yesno(ADDON_NAME, tr(S.CONFIRM_REMOVE_ONE).format(name)):
            return (SHORTCUTS_SECTION, key)
        neighbour = self._neighbour(SHORTCUTS_SECTION, key)
        shortcuts.remove_shortcuts([key])
        return neighbour

    def _edit_shortcut(self, key):
        from . import settings_actions
        new_key = settings_actions.edit_shortcut(key)
        return (SHORTCUTS_SECTION, new_key or key)


# ---- coming back to the popup after an item is backed out of
TOKEN_PROPERTY = 'CommandCentre.ReturnToken'   # set on the Home window; a newer popup cancels older waiters
POLL_SECONDS = 0.25
DEPARTURE_TIMEOUT = 8.0     # how long to wait for the launched item to take us somewhere else
# Windows whose current folder is part of "where you are" (Home's focused widget moves around, so it isn't).
FOLDER_WINDOWS = (10001, 10002, 10003, 10025, 10040, 10502, 10821)


def _where_am_i():
    window = xbmcgui.getCurrentWindowId()
    folder = xbmc.getInfoLabel('Container.FolderPath') if window in FOLDER_WINDOWS else ''
    return (window, xbmcgui.getCurrentWindowDialogId(), folder)


def _cancel_waiters():
    xbmcgui.Window(10000).setProperty(TOKEN_PROPERTY, '')


def _wait_for_return(origin):
    """Block until Kodi has left ``origin`` (window, dialog, folder) and come back to it - i.e. the
    user backed out of what the popup launched. False if it never left, Kodi is quitting, or a
    newer popup took over."""
    token = repr(time.time())
    home = xbmcgui.Window(10000)
    home.setProperty(TOKEN_PROPERTY, token)
    monitor = xbmc.Monitor()
    deadline = time.time() + DEPARTURE_TIMEOUT
    left = False
    matches = 0
    while not monitor.abortRequested():
        if monitor.waitForAbort(POLL_SECONDS):
            return False
        if home.getProperty(TOKEN_PROPERTY) != token:
            return False
        here = _where_am_i()
        if not left:
            if here != origin:
                left = True
            elif time.time() > deadline:
                return False            # the action didn't take us anywhere (e.g. a toggle)
            continue
        matches = matches + 1 if here == origin else 0
        if matches >= 2:                # two polls in a row, so a passing dialog doesn't fool us
            return True
    return False


def open_command_center():
    """Show the popup. If the chosen item opens another page, wait for the user to back out of it
    and then show the popup again (unless the 'return to Command Centre' setting is off)."""
    _cancel_waiters()
    while True:
        dialog = CommandCenterDialog('command_center.xml', ADDON_PATH, 'Default', '1080i')
        dialog.doModal()
        action = dialog.launch
        del dialog
        if not action:
            return
        # Sampled once the popup is fully closed, so it is the page the popup was opened over.
        origin = (_where_am_i() if get_bool_setting('return_to_popup', True)
                  and actions.should_return(action) else None)
        xbmc.executebuiltin(action)
        if origin is None or not _wait_for_return(origin):
            return
