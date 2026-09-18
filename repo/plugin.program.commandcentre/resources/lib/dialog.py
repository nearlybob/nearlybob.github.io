# -*- coding: utf-8 -*-
"""Command Centre — core popup dialog.

Section headings are real, separate list items (row_type='header') rather
than metadata bolted onto the first item of a section. This is deliberate:
Kodi's <itemlayout>/<focusedlayout> condition attribute is only evaluated
once, when the list is (re)built — not per item — so it cannot be used to
give header rows a different height than item rows. Making every row
(header or item) share one uniform row height is what keeps the spacing
even, and it means header rows need to be skipped over during Up/Down
navigation. That handler also makes the list circular (Up from the first
real item wraps to the last row, Down from the last wraps back to the
first), since Kodi's plain <list> control does not do this on its own —
only <wraplist> does, and that also changes to a different, fixed-focus-
position visual style, which isn't wanted here. Both behaviours together
are the one bit of custom input handling this file has.
"""
import xbmc
import xbmcgui
import xbmcaddon

import addon_discovery
import shortcuts_manager
import system_actions
import order_manager

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo('path')

CONTROL_LIST_ID = 5001
ACTION_MOVE_UP = 3
ACTION_MOVE_DOWN = 4
ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
DEFAULT_NAV_HIGHLIGHT_COLOR = 'FFFFFFFF'
LIGHT_LUMINANCE_THRESHOLD = 128  # 0-255 scale; ITU-R BT.601 perceptual luma


def _is_light_color(hex_color):
    """True if hex_color (AARRGGBB or RRGGBB) is light enough that
    black text reads better on it than white text. Uses perceptual
    luminance (0.299 R + 0.587 G + 0.114 B), not a literal
    white-only check, so near-white highlight colours also get
    black text rather than just pure FFFFFFFF/FFFFFF."""
    s = (hex_color or '').strip().lstrip('#')
    if len(s) == 8:
        rgb = s[2:]
    elif len(s) == 6:
        rgb = s
    else:
        return False
    try:
        r = int(rgb[0:2], 16)
        g = int(rgb[2:4], 16)
        b = int(rgb[4:6], 16)
    except ValueError:
        return False
    luminance = (r * 299 + g * 587 + b * 114) / 1000
    return luminance >= LIGHT_LUMINANCE_THRESHOLD


class CommandCenterDialog(xbmcgui.WindowXMLDialog):

    def onInit(self):
        # Read as a Window property (not a skin variable) because this is a
        # script-owned WindowXMLDialog, not part of the active Kodi skin —
        # $INFO[Window.Property(...)] with no window id resolves to this
        # window, which is how the highlight bar's colour reaches the XML.
        nav_color = ADDON.getSetting('nav_highlight_color') or DEFAULT_NAV_HIGHLIGHT_COLOR
        self.setProperty('nav_highlight_color', nav_color)
        self.setProperty('nav_highlight_is_light', 'true' if _is_light_color(nav_color) else 'false')

        sections = self._gather_sections()
        rows = []
        first_item_index = None

        for heading, entries in sections:
            if not entries:
                continue

            header = xbmcgui.ListItem(label=heading.upper())
            header.setProperty('row_type', 'header')
            rows.append(header)

            for entry in entries:
                item = xbmcgui.ListItem(label=entry.get('name', ''))
                item.setArt({'icon': entry.get('icon') or 'DefaultAddonProgram.png'})
                item.setProperty('action', entry.get('action', ''))
                item.setProperty('row_type', 'item')
                if first_item_index is None:
                    first_item_index = len(rows)
                rows.append(item)

        if first_item_index is None:
            xbmcgui.Dialog().notification(
                'Command Centre', 'Nothing to show — check settings',
                xbmcgui.NOTIFICATION_INFO)
            self.close()
            return

        self._list = self.getControl(CONTROL_LIST_ID)
        self._list.reset()
        for row in rows:
            self._list.addItem(row)

        # Headers are real rows (needed so every row can share one uniform
        # height — see module docstring) but must never end up selected, so
        # start on the first real item rather than row 0.
        self._first_item_index = first_item_index
        self._last_position = first_item_index
        self._list.selectItem(first_item_index)
        self.setFocus(self._list)

    def onClick(self, controlId):
        if controlId != CONTROL_LIST_ID:
            return

        selected = self._list.getSelectedItem()
        if selected is None:
            return

        action = selected.getProperty('action')
        if not action:
            return

        self.close()
        xbmc.executebuiltin(action)

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK):
            self.close()
            return
        if action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN) and self.getFocusId() == CONTROL_LIST_ID:
            self._handle_vertical_move(action_id)

    def _handle_vertical_move(self, action_id):
        """Kodi's plain <list> control clamps at its own absolute ends
        (position 0 and the last position) — Up/Down there is a no-op,
        leaving the selection unchanged. But row 0 here is always a
        header (see module docstring), so pressing Up from the first
        real item (row 1) is a perfectly normal, non-clamped move *into*
        row 0 as far as the list control is concerned — the position
        does change, just onto a header. Landing on row 0 after an Up
        therefore always means "hit the top", checked directly rather
        than through the no-op/unchanged-position test that catches the
        Down case (there, the last row genuinely is the list's own last
        position, so Kodi's own clamp is what leaves it unchanged).

        Either way, once wrapped, this still does the header-skip: if
        the resulting position landed on a header row, keep stepping in
        the same direction until a real item is reached, falling back
        to the item right after the header if that runs off the list —
        every header is immediately followed by at least one real item,
        since empty sections are never given a header in the first
        place.

        Known limitation: the Down-wrap detection relies on
        self._last_position, updated only by this handler. A mouse
        hover that moves focus without a click (Kodi doesn't route
        that through onAction the way Up/Down key presses are) isn't
        seen here, so it can desync that memory and cost one wasted
        Down press before wrapping correctly resumes. Up-wrap is
        unaffected — its detection (pos == 0) is structural, not
        based on remembered state. Keyboard/remote navigation, the
        normal way this popup is used, never triggers this."""
        size = self._list.size()
        if size == 0:
            return
        pos = self._list.getSelectedPosition()
        if not (0 <= pos < size):
            return
        direction = -1 if action_id == ACTION_MOVE_UP else 1

        at_top = direction == -1 and pos == 0
        at_bottom = direction == 1 and pos == self._last_position

        if at_top:
            pos = size - 1  # wrap to the last row, always a real item
        elif at_bottom:
            pos = self._first_item_index  # wrap to the first real item

        if self._list.getListItem(pos).getProperty('row_type') == 'header':
            scan = pos + direction
            while 0 <= scan < size and self._list.getListItem(scan).getProperty('row_type') == 'header':
                scan += direction
            pos = scan if 0 <= scan < size else pos + 1

        self._list.selectItem(pos)
        self._last_position = pos

    def _gather_sections(self):
        video_addons = addon_discovery.get_visible_addons(addon_discovery.VIDEO_ADDON_TYPE)
        program_addons = addon_discovery.get_visible_addons(addon_discovery.PROGRAM_ADDON_TYPE)
        shortcuts = shortcuts_manager.get_valid_shortcuts()
        system = system_actions.get_visible_system_actions()

        video_entries = self._ordered(addon_discovery.VIDEO_ADDON_TYPE, [
            {'id': a.get('addonid'),
             'name': a.get('name') or a.get('addonid'),
             'icon': a.get('thumbnail', 'DefaultAddonProgram.png'),
             'action': 'RunAddon({})'.format(a.get('addonid'))}
            for a in video_addons
        ])
        program_entries = self._ordered(addon_discovery.PROGRAM_ADDON_TYPE, [
            {'id': a.get('addonid'),
             'name': a.get('name') or a.get('addonid'),
             'icon': a.get('thumbnail', 'DefaultAddonProgram.png'),
             'action': 'RunAddon({})'.format(a.get('addonid'))}
            for a in program_addons
        ])
        shortcut_entries = self._ordered(order_manager.SHORTCUTS_KEY, [
            {'id': shortcuts_manager.shortcut_key(s), 'name': s.get('name', ''),
             'icon': s.get('icon', ''), 'action': s.get('action', '')}
            for s in shortcuts
        ])
        system_entries = self._ordered(system_actions.SYSTEM_KEY, [
            {'id': a['id'], 'name': a['name'], 'icon': a['icon'], 'action': a['action']}
            for a in system
        ])

        sections_by_key = {
            'video_addons': video_entries,
            'program_addons': program_entries,
            order_manager.SHORTCUTS_KEY: shortcut_entries,
            'system': system_entries,
        }
        section_order = order_manager.get_order(
            order_manager.HEADINGS_KEY, order_manager.SECTION_KEYS)

        return [
            (order_manager.SECTION_LABELS[key], sections_by_key[key])
            for key in section_order
        ]

    @staticmethod
    def _ordered(key, entries):
        """entries reordered per the user's saved order for this
        section, matched by each entry's 'id'."""
        by_id = {e['id']: e for e in entries}
        order = order_manager.get_order(key, [e['id'] for e in entries])
        return [by_id[i] for i in order if i in by_id]


def open_command_center():
    dialog = CommandCenterDialog('command_center.xml', ADDON_PATH, 'Default', '1080i')
    dialog.doModal()
    del dialog
