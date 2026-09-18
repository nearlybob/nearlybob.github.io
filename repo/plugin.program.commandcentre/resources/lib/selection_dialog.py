# -*- coding: utf-8 -*-
"""
A reusable multi-select popup, built the same way as the main
Command Centre dialog (WindowXMLDialog, own fonts, own layout) so
its checked/unchecked state is never dependent on the active skin's
native DialogSelect styling — which is what made the built-in
xbmcgui.Dialog().multiselect() hard to read.

Usage:
    result = select_items('Choose visible Video Addons', [
        {'id': 'plugin.video.redlightpicker', 'label': 'Red Light Picker', 'checked': True},
        ...
    ])
    # result is a list of the ids left checked when Save was pressed,
    # or None if the user cancelled (Back/Escape or the Cancel button).
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

CHECKED_PREFIX = '[X]  '
UNCHECKED_PREFIX = '[ ]  '


class SelectionDialog(xbmcgui.WindowXMLDialog):

    def __init__(self, *args, **kwargs):
        super(SelectionDialog, self).__init__(*args, **kwargs)
        self.title = ''
        self.entries = []  # list of {'id', 'label', 'checked'}
        self.result = None

    def onInit(self):
        self.getControl(CONTROL_TITLE).setLabel(self.title)
        self._render_list()
        # Same logged issue as the main popup: Kodi's own
        # <onload>/<defaultcontrol> focus attempt fires before this
        # runs, while the list is still empty, and fails silently
        # ("Control 4001 ... has been asked to focus, but it can't").
        # Focus explicitly now that it has content. Guarded against
        # an empty entries list — not currently reachable since every
        # caller checks for that first, but cheap to guard here too.
        control = self.getControl(CONTROL_LIST)
        if control.size() > 0:
            self.setFocus(control)

    def _render_list(self, keep_position=None):
        control = self.getControl(CONTROL_LIST)
        position = keep_position if keep_position is not None else control.getSelectedPosition()
        control.reset()
        for entry in self.entries:
            prefix = CHECKED_PREFIX if entry['checked'] else UNCHECKED_PREFIX
            item = xbmcgui.ListItem(label=prefix + entry['label'])
            control.addItem(item)
        if self.entries:
            position = max(0, min(position, len(self.entries) - 1))
            control.selectItem(position)

    def onClick(self, controlId):
        if controlId == CONTROL_LIST:
            self._toggle_selected()
        elif controlId == CONTROL_SAVE:
            self.result = [e['id'] for e in self.entries if e['checked']]
            self.close()
        elif controlId == CONTROL_CANCEL:
            self.result = None
            self.close()

    def _toggle_selected(self):
        control = self.getControl(CONTROL_LIST)
        position = control.getSelectedPosition()
        if 0 <= position < len(self.entries):
            self.entries[position]['checked'] = not self.entries[position]['checked']
            self._render_list(keep_position=position)

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK):
            self.result = None
            self.close()
            return
        if action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN):
            self._ensure_list_focus()

    def _ensure_list_focus(self):
        """Same defensive fix as CommandCenterDialog, corrected: only
        self-heal when NO control has focus at all (getFocusId()
        raising RuntimeError) — not whenever focus merely isn't on
        the list. The first version checked the latter, which also
        fires the moment focus legitimately moves off the list onto
        Save/Cancel via normal Down navigation, yanking focus back
        and making those buttons unreachable. That was the actual
        cause of Save being unreachable, not a design tradeoff."""
        control = self.getControl(CONTROL_LIST)
        if control.size() == 0:
            return
        try:
            self.getFocusId()
        except RuntimeError:
            self.setFocus(control)


def select_items(title, entries):
    """entries: list of {'id':..., 'label':..., 'checked': bool}.
    Returns the list of ids left checked if Save was pressed, or
    None if the dialog was cancelled."""
    dialog = SelectionDialog('selection_dialog.xml', ADDON_PATH, 'Default', '1080i')
    dialog.title = title
    dialog.entries = [dict(e) for e in entries]  # copy, don't mutate caller's list
    dialog.doModal()
    result = dialog.result
    del dialog
    return result
