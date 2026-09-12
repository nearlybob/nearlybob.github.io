# -*- coding: utf-8 -*-
"""
A blank, non-XML Kodi dialog window whose only job is to catch
directional/select/back actions coming from a remote (e.g. the
official iOS Kodi Remote app over JSON-RPC/EventServer) and relay
them to the real Windows mouse cursor.

Kodi keeps delivering these actions to this window's onAction()
regardless of which application currently has OS-level focus, which
is what lets this work even while Chrome is fullscreen on top.

Action IDs are from Kodi's Key.h / kodi_key_action_ids, confirmed
against the official Kodi documentation:
https://xbmc.github.io/docs.kodi.tv/master/kodi-base/dc/d13/group__python__xbmcgui__action.html
"""

import threading
import time

import xbmc
import xbmcgui

from . import mouserelay

ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2
ACTION_MOVE_UP = 3
ACTION_MOVE_DOWN = 4
ACTION_SELECT_ITEM = 7
ACTION_PREVIOUS_MENU = 10
ACTION_STOP = 13
ACTION_CONTEXT_MENU = 117  # used here as a "right click" trigger

# Confirmed from a real device log (2026-09-09): this remote/keymap
# sends 92 (ACTION_NAV_BACK) for the Back button, not the 10
# (ACTION_PREVIOUS_MENU) shown in the generic Kodi scripting docs.
# Both are treated the same way here. Back sends the browser's own
# back shortcut while there's real navigation depth to step back
# through; once already at the starting page, it arms an exit rather
# than closing immediately (see _back_exit_armed below), and the
# press after that exits - a safety buffer against an accidental
# close. Stop, Info, and the top-right gesture-area button (below)
# all exit immediately from anywhere, regardless of depth.
ACTION_NAV_BACK = 92

# Confirmed from a real device log (2026-09-09): Stop never appeared
# in testing at all - Kodi's Stop button is normally tied to an
# active Player state, which this addon doesn't use, so it likely
# wasn't reachable on the remote screen. The one exit attempt that
# did register sent action 11 (ACTION_SHOW_INFO/Info button) - a
# reasonable thing to reach for, and now wired up as a second exit
# trigger alongside Stop.
ACTION_SHOW_INFO = 11

# Confirmed from a real device log (2026-09-09): the top-right
# diamond/gesture-area icon on the official Kodi iOS remote sends
# action 18 (ACTION_SHOW_GUI) - a normal dispatched action, unlike
# Home, which never reaches onAction() at all. User's preferred exit
# button - added here as a third trigger alongside Stop and Info.
ACTION_SHOW_GUI = 18

BROWSER_BACK_ACTIONS = (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK)
CLOSE_ACTIONS = (ACTION_STOP, ACTION_SHOW_INFO, ACTION_SHOW_GUI)
DIRECTIONAL_ACTIONS = (ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN)

# Acceleration: repeated presses in the same direction within this
# window (seconds) ramp the effective step size up, multiplicatively,
# up to max_speed_multiplier. A direction change or a pause longer
# than this window resets to the base step size. Confirmed working in
# testing (0.2.0 feedback: "movement needs to be sped up") - the
# multiplier curve itself hasn't been separately tuned, so it's worth
# adjusting max_speed_multiplier in settings if the ramp feels too
# fast or too slow.
ACCEL_WINDOW_SECONDS = 0.35
ACCEL_FACTOR = 1.5


class MouseControlWindow(xbmcgui.WindowDialog):
    """
    No skin XML required - xbmcgui.WindowDialog can be instantiated
    directly. It renders nothing itself, so with Chrome fullscreen on
    top there is nothing visible to the user; the window exists only
    to receive input.

    Also watches the Chrome process in a background thread so that if
    Chrome is closed some other way (Alt+F4, task manager, crash) this
    window closes itself automatically instead of sitting open,
    invisible, and silently absorbing all Kodi input forever.
    """

    def __init__(
        self,
        step_size=5,
        chrome_process=None,
        max_speed_multiplier=10,
        scroll_notches=2,
        nav_depth_server=None,
    ):
        super(MouseControlWindow, self).__init__()
        self.step_size = step_size
        self.max_speed_multiplier = max_speed_multiplier
        self.scroll_notches = scroll_notches
        self._chrome_process = chrome_process
        self._closed = False

        self._last_direction = None
        self._last_move_time = 0.0
        self._current_multiplier = 1.0

        # Approximate navigation depth relative to the page Chrome
        # launched on. Every click (Select) is assumed to move forward
        # a page; every Back steps back (if depth > 0). The
        # "already at the start page, arm exit instead" safety buffer
        # is tracked separately, in self._back_exit_armed below - see
        # its comment for why.
        #
        # This counter is a fallback, always kept updated regardless
        # of whether nav_depth_server below is available - a count of
        # our own simulated clicks, not Chrome's real history stack,
        # so a click that doesn't actually navigate (a dropdown, a
        # form submit that stays on the page, etc.) will still count
        # as a step and could throw this off by one occasionally.
        self._nav_depth = 0

        # Optional resources.lib.navdepthserver.NavDepthServer -
        # reports real navigation depth grounded in Chrome's own
        # webNavigation events (via the bundled extension), which
        # doesn't have the click-counting drift above. Used in
        # preference to self._nav_depth once it has reported at least
        # once; falls back to self._nav_depth entirely if it's None
        # (setting disabled, port bind failed) or hasn't reported yet
        # (extension didn't load, was blocked, or Chrome version
        # mismatch) - this must never be the only way Back can work.
        self._nav_depth_server = nav_depth_server

        # Whether a Back press has armed the exit (see
        # BROWSER_BACK_ACTIONS handling in onAction()). Deliberately a
        # separate, independent flag rather than folded into
        # self._nav_depth as a sentinel value (self._nav_depth = -1) -
        # a real bug, found by tracing through this code rather than
        # from a specific device report: once nav_depth_server is
        # active, _get_current_depth() always returns the SERVER's
        # live value on every press, completely ignoring whatever
        # self._nav_depth was set to on a previous press. Since real
        # browser history genuinely cannot go negative, the server
        # reports exactly 0 forever once already at the starting page
        # - meaning the old "set self._nav_depth to -1 to arm" approach
        # was structurally unreachable as soon as the server took
        # over: every press would see depth == 0 again and just
        # re-arm, never falling through to the exit branch, no matter
        # how many times Back was pressed. An independent flag, not
        # derived from whichever depth source happens to be active,
        # is unaffected by this.
        self._back_exit_armed = False

        if self._chrome_process is not None:
            watcher = threading.Thread(target=self._watch_chrome, daemon=True)
            watcher.start()

    def _watch_chrome(self):
        # Blocks in this background thread only - doModal() on the
        # main script thread is unaffected until we call close().
        self._chrome_process.wait()
        xbmc.log(
            '[plugin.program.quickbrowser] Chrome process ended - closing control window',
            xbmc.LOGINFO,
        )
        if not self._closed:
            self.close()

    def _get_effective_step(self, action_id):
        now = time.time()
        if (
            action_id == self._last_direction
            and (now - self._last_move_time) < ACCEL_WINDOW_SECONDS
        ):
            self._current_multiplier = min(
                self._current_multiplier * ACCEL_FACTOR, self.max_speed_multiplier
            )
        else:
            self._current_multiplier = 1.0

        self._last_direction = action_id
        self._last_move_time = now
        return int(self.step_size * self._current_multiplier)

    def _get_current_depth(self):
        """
        Prefer the real, Chrome-event-grounded depth from
        nav_depth_server once it has reported at least once; fall
        back to the click-counting self._nav_depth otherwise (server
        not configured, port bind failed, or extension never loaded).
        """
        if self._nav_depth_server is not None and self._nav_depth_server.has_reported():
            return self._nav_depth_server.get_depth()
        return self._nav_depth

    def _trigger_browser_back(self):
        """
        Prefer asking the extension to call chrome.tabs.goBack()
        directly, once it has reported at least once (confirming it's
        actually active). Falls back to a synthetic Alt+Left keystroke
        otherwise.

        Confirmed on a real device as the actual fix, not just an
        alternative: a site's own page JavaScript can call
        preventDefault() on the Alt+Left keydown to silently swallow
        it (no fullscreen or Keyboard Lock API needed - a plain
        keydown listener is enough), while the real back button in a
        normal browser window worked fine on the same site. That
        showed the two aren't equivalent after all - chrome.tabs.goBack()
        operates at the same browser-chrome level a real back button
        click would, which page content has no keydown event to
        intercept in the first place.
        """
        if self._nav_depth_server is not None and self._nav_depth_server.has_reported():
            xbmc.log(
                '[plugin.program.quickbrowser] Back: using extension-driven chrome.tabs.goBack() '
                '(nav_depth_server has reported)',
                xbmc.LOGINFO,
            )
            self._nav_depth_server.request_go_back()
        else:
            xbmc.log(
                '[plugin.program.quickbrowser] Back: using Alt+Left keystroke fallback '
                '(nav_depth_server {})'.format(
                    'not configured' if self._nav_depth_server is None else 'has not reported yet'
                ),
                xbmc.LOGINFO,
            )
            mouserelay.browser_back()

    def onAction(self, action):
        action_id = action.getId()

        # Logged at DEBUG - this fires on every single action,
        # including every mouse-relay press, so INFO-level would mean
        # continuous log writes during ordinary use. Still visible if
        # debug logging is turned on.
        xbmc.log(
            '[plugin.program.quickbrowser] Received action id: {}'.format(action_id),
            xbmc.LOGDEBUG,
        )

        if action_id in DIRECTIONAL_ACTIONS:
            step = self._get_effective_step(action_id)
            hit_edge = False

            if action_id == ACTION_MOVE_LEFT:
                hit_edge = mouserelay.move_cursor_relative(-step, 0)
            elif action_id == ACTION_MOVE_RIGHT:
                hit_edge = mouserelay.move_cursor_relative(step, 0)
            elif action_id == ACTION_MOVE_UP:
                hit_edge = mouserelay.move_cursor_relative(0, -step)
            elif action_id == ACTION_MOVE_DOWN:
                hit_edge = mouserelay.move_cursor_relative(0, step)

            # Only vertical edges trigger scrolling, per the reported
            # behaviour wanted (top/bottom of page, not left/right).
            if hit_edge and action_id == ACTION_MOVE_UP:
                mouserelay.scroll_up(self.scroll_notches)
            elif hit_edge and action_id == ACTION_MOVE_DOWN:
                mouserelay.scroll_down(self.scroll_notches)

        elif action_id == ACTION_SELECT_ITEM:
            mouserelay.left_click()
            self._nav_depth += 1
            self._back_exit_armed = False
        elif action_id == ACTION_CONTEXT_MENU:
            mouserelay.right_click()
        elif action_id in BROWSER_BACK_ACTIONS:
            if self._back_exit_armed:
                xbmc.log(
                    '[plugin.program.quickbrowser] Back pressed again while armed - exiting',
                    xbmc.LOGINFO,
                )
                self._do_close()
            else:
                depth = self._get_current_depth()
                if depth > 0:
                    xbmc.log(
                        '[plugin.program.quickbrowser] Browser-back action ({}) received, depth {} -> {}'.format(
                            action_id, depth, depth - 1
                        ),
                        xbmc.LOGINFO,
                    )
                    self._nav_depth -= 1
                    self._trigger_browser_back()
                else:
                    # depth <= 0: safety buffer - the first Back press
                    # once already at the start page doesn't exit
                    # immediately, it arms the exit for the *next*
                    # Back press instead, via the independent
                    # self._back_exit_armed flag (see __init__ for
                    # why this can't be represented as a depth value
                    # once nav_depth_server is active). Nothing to
                    # navigate to here, so no _trigger_browser_back()
                    # call either.
                    xbmc.log(
                        '[plugin.program.quickbrowser] Back pressed at depth {} - arming exit '
                        '(press Back once more to exit)'.format(depth),
                        xbmc.LOGINFO,
                    )
                    self._back_exit_armed = True
        elif action_id in CLOSE_ACTIONS:
            self._do_close()
        else:
            xbmc.log(
                '[plugin.program.quickbrowser] Unhandled action id: {}'.format(action_id),
                xbmc.LOGDEBUG,
            )

    def _do_close(self):
        xbmc.log(
            '[plugin.program.quickbrowser] Closing control window',
            xbmc.LOGINFO,
        )
        self._closed = True
        self.close()
        if self._chrome_process is not None and self._chrome_process.poll() is None:
            xbmc.log(
                '[plugin.program.quickbrowser] Terminating Chrome process',
                xbmc.LOGINFO,
            )
            try:
                self._chrome_process.terminate()
            except OSError as exc:
                xbmc.log(
                    '[plugin.program.quickbrowser] chrome_process.terminate() raised: {}'.format(exc),
                    xbmc.LOGWARNING,
                )

    def close(self):
        self._closed = True
        super(MouseControlWindow, self).close()
