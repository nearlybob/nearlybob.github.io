# -*- coding: utf-8 -*-
import xbmc

from resources.lib import pip_core, winctl

CONTEXT_MENU_WINDOW_ID = 10106  # WINDOW_DIALOG_CONTEXT_MENU, confirmed against
                                 # Kodi's own current WindowIDs reference

POLL_INTERVAL_IDLE = 5       # no PiP active - check rarely, nothing to do
POLL_INTERVAL_ACTIVE = 0.15  # PiP active - fast enough that hiding the PiP
                             # when the menu opens feels close to instant.
                             # This is polling, not an event callback, so
                             # there's up to this much delay - not
                             # literally zero, but should be imperceptible
                             # at 150ms.

if __name__ == "__main__":
    monitor = xbmc.Monitor()

    # If Kodi crashed last session while a PiP was open, the state file
    # would still say active - and worse, the actual mpv.exe could still
    # be running as an orphan, which would collide with a freshly launched
    # one later since the IPC pipe name isn't unique per session. Close it
    # properly (this also resets the state file) rather than just wiping
    # the bookkeeping and leaving the process behind.
    pip_core.close_pip(silent=True)

    menu_was_open = False

    while not monitor.abortRequested():
        # Cheap check every tick - only does any real work (JSON-RPC
        # calls) on an actual transition of the verbose_logging setting,
        # so this is safe even at the fast 0.15s poll interval.
        pip_core.sync_kodi_debug_logging()

        hwnd = winctl.find_window(pip_core.MPV_WINDOW_TITLE)

        if hwnd:
            menu_open = xbmc.getCondVisibility(
                "Window.IsActive(%d)" % CONTEXT_MENU_WINDOW_ID
            )

            if menu_open and not menu_was_open:
                # Menu just opened - hide the PiP rather than fight over
                # z-order (which tested correctly - confirmed via an
                # earlier diagnostic build showing the right Windows API
                # calls firing - but didn't visually work in practice on
                # this setup). A hidden window categorically cannot cover
                # anything, regardless of whatever z-order quirk that was.
                winctl.hide(hwnd)
                pip_core.verbose_log("context menu opened - hid PiP window")
            elif not menu_open and menu_was_open:
                # Safety net: if the menu closes without the user picking
                # one of our own actions (grow/shrink/nudge/swap already
                # show the window again themselves, as their last step,
                # once they've applied whatever change was requested),
                # this makes sure it doesn't stay hidden forever. Calling
                # show() when it's already visible is a harmless no-op,
                # so there's no race to worry about here even if this
                # fires around the same time as an action's own show().
                winctl.show(hwnd)
                pip_core.verbose_log("context menu closed - restored PiP window visibility (safety net)")

            menu_was_open = menu_open
            interval = POLL_INTERVAL_ACTIVE
        else:
            menu_was_open = False
            interval = POLL_INTERVAL_IDLE

            # Resilience check: our own state can say a PiP is active
            # while its window has actually already disappeared - mpv
            # can fail to play a stream (dead link, blocked content,
            # network failure) and exit on its own well after launch,
            # with nothing else ever noticing. Left unhandled, this can
            # leave the main stream permanently hidden behind nothing -
            # or, worse, leave stale state blocking a fresh attempt.
            # Clean up immediately and force the main stream back to
            # fullscreen the moment this is detected, rather than only
            # reacting to the specific launch-time failure paths that
            # already have their own handling elsewhere.
            state = pip_core.load_state()
            if state.get("active"):
                pip_core.log("PiP window disappeared unexpectedly - cleaning up and restoring main stream")
                pip_core.close_pip(silent=True)  # now handles ActivateWindow(fullscreenvideo) itself

        if monitor.waitForAbort(interval):
            break

    # Kodi is shutting down (or this service is being stopped/reloaded) -
    # close any PiP that's still running rather than leaving mpv orphaned.
    # xbmc.Monitor.onAbortRequested() as an overridable callback was
    # removed from the Python API in Kodi v19 - confirmed against the
    # current official Monitor class docs, which no longer list it at
    # all. Checking here, right after the wait loop exits, is the
    # current documented way to detect shutdown instead.
    state = pip_core.load_state()
    if state.get("active"):
        pip_core.log("Kodi shutting down, closing PiP window")
        pip_core.close_pip(silent=True)
