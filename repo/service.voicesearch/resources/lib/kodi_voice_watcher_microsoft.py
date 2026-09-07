"""
Version: 1.4.8

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

_recognized_text = None
_listen_lock = threading.Lock()


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

    print("Keyboard opened -- listening (Windows Speech Recognition)...")
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


def send_text_and_wait(text: str) -> str:
    """Type the recognised text, then watch during CONFIRM_DELAY_SECONDS:
    - if the keyboard gets cancelled (closed) during that window,
      return "cancelled" without confirming.
    - otherwise confirm (press OK) once the delay elapses and return
      "confirmed".
    - if CONFIRM_DELAY_SECONDS is None, just types and returns "manual"
      -- you press OK yourself.
    """
    call_kodi_jsonrpc("Input.SendText", {"text": text, "done": False})

    if CONFIRM_DELAY_SECONDS is None:
        return "manual"

    poll_interval = 0.15
    elapsed = 0.0
    while elapsed < CONFIRM_DELAY_SECONDS:
        time.sleep(poll_interval)
        elapsed += poll_interval
        if not keyboard_is_open():
            return "cancelled"

    if not keyboard_is_open():
        return "cancelled"

    call_kodi_jsonrpc("Input.SendText", {"text": text, "done": True})
    return "confirmed"


def get_current_window_name() -> str:
    result = call_kodi_jsonrpc("GUI.GetProperties", {"properties": ["currentwindow"]})
    try:
        return result["result"]["currentwindow"]["label"]
    except (KeyError, TypeError):
        return ""


def handle_input_requested():
    # Skip (rather than queue up behind) an overlapping trigger --
    # e.g. a second keyboard-opened notification arriving while we're
    # already mid-listen for a previous one.
    if not _listen_lock.acquire(blocking=False):
        print("Already listening for a previous request -- ignoring this one.")
        return

    # SAPI is a COM component. Every thread that touches COM must
    # initialise it first -- it is NOT automatic on a freshly spawned
    # thread, and skipping this raises "CoInitialize has not been
    # called" the moment SAPI is touched below.
    pythoncom.CoInitialize()
    try:
        if CURRENT_WINDOW_FILTER is not None:
            current = get_current_window_name()
            if CURRENT_WINDOW_FILTER.lower() not in current.lower():
                print(f"Ignoring keyboard (current window: {current!r})")
                return

        attempts = 0
        while True:
            attempts += 1
            text = listen_once()
            if not text:
                print("No speech recognised in time.")
                return

            print(f"Recognised: {text!r}")
            outcome = send_text_and_wait(text)

            if outcome == "confirmed":
                print("Search confirmed.")
                return
            if outcome == "manual":
                print("Text typed -- press OK on the keyboard to search.")
                return
            if outcome == "cancelled":
                if attempts > MAX_RETRIES:
                    print(f"Gave up after {attempts} cancelled attempt(s).")
                    return
                print("Keyboard was cancelled -- restarting voice search.")
                trigger_nimbus_search()
                time.sleep(0.6)  # give the fresh keyboard a moment to open
                continue
    except Exception as e:
        # Never let this thread die silently -- always leave a trace
        # in the console explaining what went wrong.
        print(f"Error while handling input request: {e}")
    finally:
        pythoncom.CoUninitialize()
        _listen_lock.release()


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
    print("WebSocket error:", error)


def on_close(ws, close_status_code, close_msg):
    print("Disconnected from Kodi.")


def on_open(ws):
    print(f"Connected to Kodi at {KODI_WS_URL}. Waiting for a keyboard to open...")


def start_watcher():
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
        print("Reconnecting in 5s...")
        time.sleep(5)


if __name__ == "__main__":
    start_watcher()
