# -*- coding: utf-8 -*-
"""
A reusable reordering popup: shows a list of labelled entries in
their current order, and lets the user move the focused entry up or
down with Left/Right, then Save or Cancel — the same WindowXMLDialog
pattern as selection_dialog.py, for the same reason (consistent,
skin-independent look rather than relying on any native dialog).

Left/Right (rather than Up/Down, which stay as plain list
navigation) was chosen because it mirrors how moving an item up/down
a list is commonly done with a single physical direction pair on a
remote, leaving Up/Down free for moving focus between rows.

Usage:
    result = reorder_items('Set order for Video Addons', [
        {'id': 'plugin.video.redlightpicker', 'label': 'Red Light Picker'},
        ...
    ])
    # result is the list of ids in the user's chosen order if Save was
    # pressed, or None if the user cancelled (Back/Escape or Cancel).
"""
import xbmcgui
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo('path')

CONTROL_TITLE = 4000
CONTROL_LIST = 4001
CONTROL_SAVE = 4002
CONTROL_CANCEL = 4003

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
ACTION_MOVE_UP = 3
ACTION_MOVE_DOWN = 4
ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2


class ReorderDialog(xbmcgui.WindowXMLDialog):

    def __init__(self, *args, **kwargs):
        super(ReorderDialog, self).__init__(*args, **kwargs)
        self.title = ''
        self.entries = []  # list of {'id', 'label'}
        self.result = None

    def onInit(self):
        self.getControl(CONTROL_TITLE).setLabel(self.title)
        self._render_list()
        control = self.getControl(CONTROL_LIST)
        if control.size() > 0:
            self.setFocus(control)

    def _render_list(self, keep_position=None):
        control = self.getControl(CONTROL_LIST)
        position = keep_position if keep_position is not None else control.getSelectedPosition()
        control.reset()
        for entry in self.entries:
            control.addItem(xbmcgui.ListItem(label=entry['label']))
        if self.entries:
            position = max(0, min(position, len(self.entries) - 1))
            control.selectItem(position)

    def onClick(self, controlId):
        if controlId == CONTROL_SAVE:
            self.result = [e['id'] for e in self.entries]
            self.close()
        elif controlId == CONTROL_CANCEL:
            self.result = None
            self.close()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK):
            self.result = None
            self.close()
            return
        if action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN):
            self._ensure_list_focus()
            return
        if action_id in (ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT):
            if self.getFocusId() == CONTROL_LIST:
                self._move_selected(-1 if action_id == ACTION_MOVE_LEFT else 1)

    def _move_selected(self, direction):
        control = self.getControl(CONTROL_LIST)
        position = control.getSelectedPosition()
        new_position = position + direction
        if not (0 <= position < len(self.entries)) or not (0 <= new_position < len(self.entries)):
            return
        self.entries[position], self.entries[new_position] = (
            self.entries[new_position], self.entries[position])
        self._render_list(keep_position=new_position)

    def _ensure_list_focus(self):
        """Same defensive fix as CommandCenterDialog/SelectionDialog:
        only self-heal when NO control has focus at all — see
        SelectionDialog._ensure_list_focus for why."""
        control = self.getControl(CONTROL_LIST)
        if control.size() == 0:
            return
        try:
            self.getFocusId()
        except RuntimeError:
            self.setFocus(control)


def reorder_items(title, entries):
    """entries: list of {'id':..., 'label':...} in their current
    order. Returns the list of ids in the user's chosen order if
    Save was pressed, or None if the dialog was cancelled."""
    dialog = ReorderDialog('reorder_dialog.xml', ADDON_PATH, 'Default', '1080i')
    dialog.title = title
    dialog.entries = [dict(e) for e in entries]  # copy, don't mutate caller's list
    dialog.doModal()
    result = dialog.result
    del dialog
    return result
