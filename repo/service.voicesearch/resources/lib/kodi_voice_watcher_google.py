"""
Version: 1.4.11

Background watcher: automatically starts voice capture (Google's free web speech API,
via the SpeechRecognition library) whenever Kodi opens an on-screen keyboard, and
fills it with the recognised text.

HOW THIS WORKS
Kodi broadcasts a notification called "Input.OnInputRequested" over its
TCP/WebSocket JSON-RPC port every time ANY keyboard dialog opens
(search, renaming, passwords, addon settings, etc.). This script stays
connected and listens for that notification; when it arrives, it
captures one phrase via Google's speech API and sends it back
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
  - An internet connection (audio is sent to Google's speech API).
  - pip install SpeechRecognition pyaudio websocket-client requests
"""

import json
import os
import sys
import threading
import time

import requests
import speech_recognition as sr
import websocket

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
# How long a silence has to last before the recognizer decides you've
# finished speaking and stops recording. The library's own default is
# 0.8. Kept at the default here since the actual cause of cut-off
# endings turned out to be the energy threshold drifting during
# speech (see ENERGY_THRESHOLD_MARGIN / dynamic_energy_threshold
# below), not this value -- raising this further mainly adds delay
# between finishing speaking and the result appearing, without fixing
# cutoffs on its own. Raise it only if cutoffs return after testing.
PAUSE_THRESHOLD_SECONDS = 0.8

# Multiplies the auto-calibrated energy threshold after calibration --
# lower means more sensitive (picks up quieter/more distant speech,
# but also more prone to picking up background noise as speech).
# 1.0 = no adjustment, use the calibrated value as-is. Lower this
# (e.g. 0.6) if quiet trailing syllables are still getting missed
# with a distant mic; raise it (e.g. 1.2) if background noise is
# being mistaken for speech.
ENERGY_THRESHOLD_MARGIN = 0.8

MAX_RETRIES = 3

_listen_lock = threading.Lock()


def listen_once():
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = PAUSE_THRESHOLD_SECONDS
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        recognizer.energy_threshold *= ENERGY_THRESHOLD_MARGIN

        # By default the recognizer keeps adjusting its volume
        # threshold WHILE you're talking. With a distant mic, the
        # loud start of a word can push that threshold up, and then
        # the quieter tail end of the phrase falls below it and gets
        # read as silence -- cutting the word short (worse the
        # further you are from the mic, exactly the symptom this
        # fixes). Freezing the threshold right after calibration
        # avoids that: it's set once, from the actual room's ambient
        # noise, and doesn't drift upward mid-phrase.
        recognizer.dynamic_energy_threshold = False

        print("Keyboard opened -- listening (Google speech API)...")
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=6)
        except sr.WaitTimeoutError:
            return None

    try:
        return recognizer.recognize_google(audio)
    except sr.UnknownValueError:
        print("Could not understand audio.")
        return None
    except sr.RequestError as e:
        # Raised when Google's API can't be reached (no internet,
        # rate-limited, etc.) -- distinct from "didn't understand you".
        print(f"Could not reach Google's speech API: {e}")
        return None


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
    # already mid-listen for a previous one. Also avoids two
    # simultaneous sr.Microphone() opens fighting over the same
    # input device.
    if not _listen_lock.acquire(blocking=False):
        print("Already listening for a previous request -- ignoring this one.")
        return

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
        _listen_lock.release()


def on_message(ws, message):
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return
    if data.get("method") == "Input.OnInputRequested":
        # Run in a separate thread so the websocket loop keeps pumping
        # while we block waiting for the microphone/API.
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
