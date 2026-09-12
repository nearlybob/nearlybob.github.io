"""
Version: 1.5.4

Background watcher: automatically starts voice capture (Windows Speech
Recognition / SAPI) whenever Kodi opens an on-screen keyboard, and
fills it with the recognised text.

HOW THIS WORKS
Kodi broadcasts a notification called "Input.OnInputRequested" over its
TCP/WebSocket JSON-RPC port every time ANY keyboard dialog opens
(search, renaming, passwords, addon settings, etc.). This script stays
connected and listens for that notification; when it arrives, it
captures one phrase via Windows Speech Recognition and sends it back
via Input.SendText.

IMPORTANT LIMITATION -- please read before relying on this:
Kodi's notification does not say WHICH keyboard opened. This script
cannot tell the difference between the Nimbus search box and, say, a
password prompt or a "rename file" dialog. It will try to fill
whichever keyboard just opened with whatever it hears. If that's a
problem in practice (e.g. it fires while you're trying to type a
password), the practical options are:
  - Only run this watcher when you're actively about to search, and
    close it afterwards (see the __main__ block below for a
    keyboard-interrupt-friendly loop).
  - Add your own filter based on Kodi's currently active window (see
    the CURRENT_WINDOW_FILTER note near the bottom) -- this is a
    heuristic, not a guarantee, since the keyboard dialog overlays
    whatever window was already open.

REQUIRES:
  - Kodi Settings > Services > Control:
      - "Allow remote control from applications on this system" (HTTP, port 8080)
      - "Allow programs on this system to control Kodi" (TCP/WebSocket, port 9090)
  - Windows Speech Recognition set up once via the Start menu.
  - pip install pywin32 websocket-client requests
"""

import json
import os
import sys
import threading
import time

import pythoncom
import requests
import websocket
import win32com.client

# --- Kodi connection settings ---------------------------------------
KODI_HOST = "localhost"
KODI_HTTP_PORT = 8080
KODI_WS_PORT = 9090
KODI_USER = "kodi"
KODI_PASS = "kodi"  # generic placeholder -- configure your real password
                    # via this addon's Settings screen in Kodi


def _load_credential_overrides():
    """When launched by the Kodi service addon, it passes the addon's
    userdata profile folder as sys.argv[1], so this can read
    kodi_username/kodi_password from config.txt there (set via the
    addon's own Settings screen, not by editing this file). Run
    standalone with no argument -- e.g. manual testing -- and the
    hardcoded defaults above are left as-is."""
    global KODI_USER, KODI_PASS
    if len(sys.argv) <= 1:
        return
    config_path = os.path.join(sys.argv[1], "config.txt")
    if not os.path.exists(config_path):
        return
    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "kodi_username" and value:
                KODI_USER = value
            elif key == "kodi_password":
                # Unlike username, an explicitly empty configured
                # password IS applied (overriding the hardcoded
                # placeholder above) -- a fresh, unconfigured install
                # should not silently authenticate with someone else's
                # guessed password.
                KODI_PASS = value


_load_credential_overrides()

# --- Persistent logging ----------------------------------------------
# This script runs silently via pythonw.exe (no console), so print()
# alone goes nowhere useful once launched by the Kodi service addon --
# it's only visible when run manually from a terminal. This writes the
# same messages to a log file too, so failures can actually be
# diagnosed after the fact instead of only inferred indirectly from
# kodi.log (which has no visibility into this process at all).
_LOG_PATH = None
if len(sys.argv) > 1:
    _LOG_PATH = os.path.join(sys.argv[1], "watcher_log.txt")

_LOG_MAX_BYTES = 2 * 1024 * 1024  # 2MB -- truncate rather than grow forever


def log(message: str):
    print(message)
    if not _LOG_PATH:
        return
    try:
        if os.path.exists(_LOG_PATH) and os.path.getsize(_LOG_PATH) > _LOG_MAX_BYTES:
            with open(_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                f.seek(_LOG_MAX_BYTES // 2)
                tail = f.read()
            with open(_LOG_PATH, "w", encoding="utf-8") as f:
                f.write("...(log truncated)...\n")
                f.write(tail)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} - {message}\n")
    except Exception:
        pass  # logging must never itself crash the watcher


KODI_HTTP_URL = f"http://{KODI_HOST}:{KODI_HTTP_PORT}/jsonrpc"
KODI_WS_URL = f"ws://{KODI_HOST}:{KODI_WS_PORT}/jsonrpc"

# Optional heuristic filter -- set to None to react to every keyboard,
# or to a Kodi window name (e.g. "home") to only react while that
# window is the current one. See the limitation note above.
CURRENT_WINDOW_FILTER = None

# How long to pause after typing the recognised text before
# automatically confirming the search (pressing OK). Gives you a
# moment to see what was typed, and a window to cancel it (see below)
# if it's wrong. Set to 0 to submit instantly, or None to type the
# text but require pressing OK yourself.
CONFIRM_DELAY_SECONDS = 1.0

# How to confirm (press OK) after typing. Input.Select triggers the
# same underlying "select" action a real button press or mouse click
# uses; the alternative is a second Input.SendText call with
# done=true. Set to False to use that instead.
USE_INPUT_SELECT_TO_CONFIRM = True

# Whether to poll Kodi during the delay above to detect you pressing
# Back/Cancel on your remote, and auto-restart voice search if so.
# DISABLED BY DEFAULT: real-world testing (Google engine) showed the
# detection method (polling Window.IsActive(virtualkeyboard))
# reporting the keyboard as closed 100% of the time against Nimbus's
# specific search dialog -- not intermittently, every single attempt
# -- which meant the search was NEVER actually confirming; it just
# kept "cancelling" and retrying until it gave up. Disabled here too
# for consistency, though this hasn't been separately confirmed
# broken on this engine specifically. With this off, send_text_and_wait
# always confirms after the delay, matching the simpler behaviour
# confirmed working before the cancel/retry feature was added.
ENABLE_CANCEL_DETECTION = False

# If you press Back/Cancel on your remote while the typed text is
# showing (within CONFIRM_DELAY_SECONDS), this reopens Nimbus's search
# box and listens again automatically, instead of just cancelling.
# NOTE: this retry action is Nimbus-specific (it re-runs Nimbus's own
# "new search" trigger) -- it assumes whatever you cancelled was a
# Nimbus search. If this watcher's "reacts to every keyboard"
# limitation causes it to fire on some other prompt (e.g. a password
# dialog) and you cancel that, this would incorrectly reopen a Nimbus
# search box rather than just cancelling.
# This is the number of retries AFTER the first attempt (so the
# default of 3 allows up to 4 total listen attempts). Set to 0 for
# exactly one attempt with no auto-reopen on cancel.
MAX_RETRIES = 3

# Minimum time that must pass after finishing one request before a new
# Input.OnInputRequested is treated as a genuine new search, rather
# than an echo of our own confirm (see handle_input_requested for the
# real-world evidence behind this, observed on the Google engine).
# Short enough not to block a genuinely quick deliberate re-search.
RETRIGGER_COOLDOWN_SECONDS = 2.5

# If True, this script handles exactly one request then exits --
# service.py relaunches a fresh instance immediately after (see
# service.py's respawn loop). If False, it runs indefinitely,
# reconnecting on its own if disconnected (see the loop at the bottom
# of start_watcher()). These must be changed together: a watcher that
# exits with nothing relaunching it leaves nothing listening for the
# next search.
EXIT_AFTER_ONE_REQUEST = True
_handled_one_request = threading.Event()

_listen_lock = threading.Lock()
_last_completed_time = 0.0


class SpeechEvents:
    def OnRecognition(self, StreamNumber, StreamPosition, RecognitionType, Result):
        global _recognized_text
        result_obj = win32com.client.Dispatch(Result)
        _recognized_text = result_obj.PhraseInfo.GetText()


def listen_once(timeout_seconds: float = 8.0):
    global _recognized_text
    _recognized_text = None

    context = win32com.client.DispatchWithEvents(
        "SAPI.SpSharedRecoContext", SpeechEvents
    )
    grammar = context.CreateGrammar()
    grammar.DictationLoad()
    grammar.DictationSetState(1)

    log("Keyboard opened -- listening (Windows Speech Recognition)...")
    start = time.time()
    try:
        while _recognized_text is None and (time.time() - start) < timeout_seconds:
            pythoncom.PumpWaitingMessages()
            time.sleep(0.05)
    finally:
        grammar.DictationSetState(0)

    return _recognized_text


def call_kodi_jsonrpc(method: str, params: dict) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    response = requests.post(
        KODI_HTTP_URL,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        auth=(KODI_USER, KODI_PASS),
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def keyboard_is_open() -> bool:
    """True if Kodi's on-screen keyboard dialog is currently showing.
    'virtualkeyboard' is the official registered name for window ID
    10103 (DialogKeyboard.xml), confirmed via Kodi's own Window IDs
    reference."""
    result = call_kodi_jsonrpc(
        "XBMC.GetInfoBooleans", {"booleans": ["Window.IsActive(virtualkeyboard)"]}
    )
    try:
        return bool(result["result"]["Window.IsActive(virtualkeyboard)"])
    except (KeyError, TypeError):
        # If we can't tell, don't block a normal confirm over it.
        return True


def trigger_nimbus_search() -> dict:
    """Re-open Nimbus's search keyboard -- the same call its own 'new
    search' button makes. Used to auto-restart voice search after a
    cancel (see MAX_RETRIES note above)."""
    return call_kodi_jsonrpc(
        "Addons.ExecuteAddon",
        {"addonid": "script.nimbus.helper", "params": {"mode": "search_input"}},
    )


def get_nimbus_history_count() -> str:
    """DIAGNOSTIC ONLY -- reads nothing we act on, just logs it.
    Nimbus's own source (search_utils.py) only increments
    Window(10000).Property('nimbus.search.history.count') when its
    add_spath_to_database() actually runs, which only happens if
    keyboard.isConfirmed() was True on NIMBUS's side. Comparing this
    value before and after our confirm is a USEFUL but NOT fully
    reliable signal for whether the search registered -- it has shown
    false negatives (kodi.log has confirmed a search's provider
    queries firing correctly when this read UNCHANGED), most likely
    due to Kodi's info-label caching. Treat "changed" as a good sign
    and "unchanged" as inconclusive, not proof of failure."""
    result = call_kodi_jsonrpc(
        "XBMC.GetInfoLabels",
        {"labels": ["Window(10000).Property(nimbus.search.history.count)"]},
    )
    try:
        return result["result"]["Window(10000).Property(nimbus.search.history.count)"]
    except (KeyError, TypeError):
        return "?"


def send_text_and_wait(text: str) -> str:
    """Type the recognised text, then watch during CONFIRM_DELAY_SECONDS:
    - if ENABLE_CANCEL_DETECTION is on and the keyboard gets cancelled
      (closed) during that window, return "cancelled" without
      confirming.
    - otherwise confirm (press OK) once the delay elapses and return
      "confirmed".
    - if CONFIRM_DELAY_SECONDS is None, just types and returns "manual"
      -- you press OK yourself.
    """
    history_before = get_nimbus_history_count()

    type_result = call_kodi_jsonrpc("Input.SendText", {"text": text, "done": False})
    log(f"Typed text via Input.SendText, response: {type_result}")

    if CONFIRM_DELAY_SECONDS is None:
        return "manual"

    if ENABLE_CANCEL_DETECTION:
        poll_interval = 0.15
        elapsed = 0.0
        while elapsed < CONFIRM_DELAY_SECONDS:
            time.sleep(poll_interval)
            elapsed += poll_interval
            if not keyboard_is_open():
                return "cancelled"
        if not keyboard_is_open():
            return "cancelled"
    else:
        time.sleep(CONFIRM_DELAY_SECONDS)

    if USE_INPUT_SELECT_TO_CONFIRM:
        confirm_result = call_kodi_jsonrpc("Input.Select", {})
        log(f"Confirmed via Input.Select, response: {confirm_result}")
    else:
        confirm_result = call_kodi_jsonrpc("Input.SendText", {"text": text, "done": True})
        log(f"Confirmed via Input.SendText, response: {confirm_result}")

    history_after = get_nimbus_history_count()
    log(
        f"Nimbus search history count -- before: {history_before!r}, "
        f"after: {history_after!r} "
        f"({'CHANGED' if history_after != history_before else 'UNCHANGED (inconclusive -- see get_nimbus_history_count)'})"
    )
    return "confirmed"


def get_current_window_name() -> str:
    result = call_kodi_jsonrpc("GUI.GetProperties", {"properties": ["currentwindow"]})
    try:
        return result["result"]["currentwindow"]["label"]
    except (KeyError, TypeError):
        return ""


def handle_input_requested():
    global _last_completed_time
    log("Input.OnInputRequested received -- keyboard opened.")

    # Skip (rather than queue up behind) an overlapping trigger --
    # e.g. a second keyboard-opened notification arriving while we're
    # already mid-listen for a previous one.
    if not _listen_lock.acquire(blocking=False):
        log("Already listening for a previous request -- ignoring this one.")
        return

    # SAPI is a COM component. Every thread that touches COM must
    # initialise it first -- it is NOT automatic on a freshly spawned
    # thread, and skipping this raises "CoInitialize has not been
    # called" the moment SAPI is touched below.
    pythoncom.CoInitialize()
    try:
        # Real-world evidence (watcher_log.txt, Google engine) showed a
        # fresh Input.OnInputRequested arriving within ~0-1 second of
        # our OWN confirm completing, consistent with our own
        # Input.SendText confirm somehow causing Kodi to broadcast
        # another "keyboard opened" notification.
        #
        # IMPORTANT: this check MUST happen here, inside the lock, not
        # before acquiring it. Checking it beforehand created a race
        # (confirmed happening in practice on the Google engine): an
        # echo notification arriving while the original request was
        # still finishing could read a stale timestamp, wrongly pass
        # the check, then acquire the lock a moment later once the
        # original thread released it. Checking only after the lock is
        # held closes that gap.
        since_last = time.time() - _last_completed_time
        if since_last < RETRIGGER_COOLDOWN_SECONDS:
            log(
                f"Ignoring keyboard -- fired only {since_last:.1f}s after the "
                "previous request finished (likely an echo of our own confirm, "
                "not a real new search)."
            )
            return

        if CURRENT_WINDOW_FILTER is not None:
            current = get_current_window_name()
            if CURRENT_WINDOW_FILTER.lower() not in current.lower():
                log(f"Ignoring keyboard (current window: {current!r})")
                return

        attempts = 0
        while True:
            attempts += 1
            text = listen_once()
            if not text:
                log("No speech recognised in time.")
                return

            log(f"Recognised: {text!r}")
            outcome = send_text_and_wait(text)

            if outcome == "confirmed":
                log("Search confirmed.")
                return
            if outcome == "manual":
                log("Text typed -- press OK on the keyboard to search.")
                return
            if outcome == "cancelled":
                if attempts > MAX_RETRIES:
                    log(f"Gave up after {attempts} cancelled attempt(s).")
                    return
                log("Keyboard was cancelled -- restarting voice search.")
                trigger_nimbus_search()
                time.sleep(0.6)  # give the fresh keyboard a moment to open
                continue
    except Exception as e:
        # Never let this thread die silently -- always leave a trace
        # in the console explaining what went wrong.
        log(f"Error while handling input request: {e}")
    finally:
        pythoncom.CoUninitialize()
        _last_completed_time = time.time()
        _listen_lock.release()
        _handled_one_request.set()


def on_message(ws, message):
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return
    if data.get("method") == "Input.OnInputRequested":
        # Run in a separate thread so the websocket loop keeps pumping
        # (SAPI's event loop and the listen timeout would otherwise
        # block message processing).
        threading.Thread(target=handle_input_requested, daemon=True).start()


def on_error(ws, error):
    log(f"WebSocket error: {error}")


def on_close(ws, close_status_code, close_msg):
    log("Disconnected from Kodi.")


def on_open(ws):
    log(f"Connected to Kodi at {KODI_WS_URL}. Waiting for a keyboard to open...")


def start_watcher():
    if EXIT_AFTER_ONE_REQUEST:
        # Connect, handle exactly one real request, then let the whole
        # script terminate -- service.py's respawn loop starts a fresh
        # instance immediately after. See the comment on
        # EXIT_AFTER_ONE_REQUEST above for why.
        ws = websocket.WebSocketApp(
            KODI_WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        def watchdog():
            _handled_one_request.wait()
            log("Handled one request -- closing connection so this process can exit.")
            ws.close()

        threading.Thread(target=watchdog, daemon=True).start()
        ws.run_forever()
        return

    # Loop rather than reconnecting via recursion -- this script is
    # meant to run indefinitely (days/weeks), and recursive reconnects
    # would slowly grow the call stack until Python's recursion limit
    # is hit.
    while True:
        ws = websocket.WebSocketApp(
            KODI_WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        ws.run_forever()
        log("Reconnecting in 5s...")
        time.sleep(5)


if __name__ == "__main__":
    start_watcher()
