# -*- coding: utf-8 -*-
"""One reusable list popup with two modes, in the same WindowXMLDialog style as the
main popup (so it never depends on the active skin's native dialog styling):

    select_items('Choose visible Video Addons', [{'id':..., 'label':..., 'checked': True}, ...])
        -> ids left checked when Save is pressed, or None if cancelled.

    reorder_items('Set order for Video Addons', [{'id':..., 'label':...}, ...])
        -> ids in the chosen order when Save is pressed, or None if cancelled.
        Left/Right moves the selected entry; pressing Select on it offers
        Move up/down/to top/to bottom (for mouse and touch).
"""
import xbmcgui

from .common import (ACTION_MOVE_DOWN, ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT, ACTION_MOVE_UP,
                     ADDON_PATH, CLOSE_ACTIONS, focus_id, tr)
from .strings import S

CONTROL_TITLE = 4000
CONTROL_LIST = 4001
CONTROL_SAVE = 4002
CONTROL_CANCEL = 4003
CONTROL_HINT = 4004

MODE_SELECT = 'select'
MODE_REORDER = 'reorder'
CHECKED_PREFIX = '[X]  '
UNCHECKED_PREFIX = '[ ]  '


class ListDialog(xbmcgui.WindowXMLDialog):

    def __init__(self, *args, **kwargs):
        super(ListDialog, self).__init__(*args, **kwargs)
        self.mode = MODE_SELECT
        self.title = ''
        self.hint = ''
        self.accept_label = ''
        self.entries = []
        self.result = None

    def onInit(self):
        self.getControl(CONTROL_TITLE).setLabel(self.title)
        self.getControl(CONTROL_HINT).setLabel(self.hint)
        self.getControl(CONTROL_SAVE).setLabel(self.accept_label or tr(S.SAVE))
        self.getControl(CONTROL_CANCEL).setLabel(tr(S.CANCEL))
        self._render_list()
        # Kodi's own <onload>/<defaultcontrol> focus fires while the list is still
        # empty and can't take focus, so focus explicitly now that it has content.
        control = self.getControl(CONTROL_LIST)
        if control.size() > 0:
            self.setFocus(control)

    def _label(self, entry):
        if self.mode == MODE_SELECT:
            return (CHECKED_PREFIX if entry['checked'] else UNCHECKED_PREFIX) + entry['label']
        return entry['label']

    def _render_list(self, keep_position=None):
        control = self.getControl(CONTROL_LIST)
        position = keep_position if keep_position is not None else control.getSelectedPosition()
        control.reset()
        for entry in self.entries:
            control.addItem(xbmcgui.ListItem(label=self._label(entry)))
        if self.entries:
            control.selectItem(max(0, min(position, len(self.entries) - 1)))

    # --- input
    def onClick(self, control_id):
        if control_id == CONTROL_LIST:
            if self.mode == MODE_SELECT:
                self._toggle_selected()
            else:
                self._reorder_menu()
        elif control_id == CONTROL_SAVE:
            if self.mode == MODE_SELECT:
                self.result = [e['id'] for e in self.entries if e['checked']]
            else:
                self.result = [e['id'] for e in self.entries]
            self.close()
        elif control_id == CONTROL_CANCEL:
            self.result = None
            self.close()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in CLOSE_ACTIONS:
            self.result = None
            self.close()
            return
        if action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN, ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT):
            control = self.getControl(CONTROL_LIST)
            if focus_id(self) == -1 and control.size() > 0:
                self.setFocus(control)  # nothing focused: self-heal
            elif (self.mode == MODE_REORDER and focus_id(self) == CONTROL_LIST
                  and action_id in (ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT)):
                self._move_selected_by(-1 if action_id == ACTION_MOVE_LEFT else 1)

    def _toggle_selected(self):
        control = self.getControl(CONTROL_LIST)
        position = control.getSelectedPosition()
        if 0 <= position < len(self.entries):
            self.entries[position]['checked'] = not self.entries[position]['checked']
            self._render_list(keep_position=position)

    def _move_selected_by(self, direction):
        position = self.getControl(CONTROL_LIST).getSelectedPosition()
        self._move_to(position, position + direction)

    def _move_to(self, position, new_position):
        if not (0 <= position < len(self.entries) and 0 <= new_position < len(self.entries)):
            return
        if position == new_position:
            return
        self.entries.insert(new_position, self.entries.pop(position))
        self._render_list(keep_position=new_position)

    def _reorder_menu(self):
        position = self.getControl(CONTROL_LIST).getSelectedPosition()
        last = len(self.entries) - 1
        choice = xbmcgui.Dialog().contextmenu([
            tr(S.MOVE_UP), tr(S.MOVE_DOWN), tr(S.MOVE_TOP), tr(S.MOVE_BOTTOM)])
        target = {0: position - 1, 1: position + 1, 2: 0, 3: last}.get(choice)
        if target is not None:
            self._move_to(position, target)


def _run(mode, title, entries, hint='', accept_label=''):
    dialog = ListDialog('list_dialog.xml', ADDON_PATH, 'Default', '1080i')
    dialog.mode = mode
    dialog.title = title
    dialog.hint = hint
    dialog.accept_label = accept_label
    dialog.entries = [dict(e) for e in entries]  # copies - don't mutate the caller's list
    dialog.doModal()
    result = dialog.result
    del dialog
    return result


def select_items(title, entries, accept_label=''):
    return _run(MODE_SELECT, title, entries, accept_label=accept_label)


def reorder_items(title, entries):
    return _run(MODE_REORDER, title, entries, hint=tr(S.REORDER_HINT))
