# -*- coding: utf-8 -*-
r"""
Minimal client for mpv's JSON IPC protocol over a Windows named pipe.
mpv must be launched with --input-ipc-server=\\.\pipe\<name>.

This is intentionally minimal: fire-and-forget command sending, short
timeout, no persistent connection. Good enough for occasional mute
toggles; not a general-purpose mpv control library.
"""
import json
import time

PIPE_NAME = r"\\.\pipe\loop_pip_mpv"


def send(command_list, timeout=0.5):
    """
    command_list: e.g. ["set_property", "mute", True]
    Returns True if the write succeeded, False otherwise (mpv not ready,
    pipe not open yet, etc). Does not guarantee mpv acted on it.
    """
    payload = json.dumps({"command": command_list}) + "\n"
    end = time.time() + timeout
    while time.time() < end:
        try:
            with open(PIPE_NAME, "r+b", buffering=0) as pipe:
                pipe.write(payload.encode("utf-8"))
            return True
        except OSError:
            time.sleep(0.1)
    return False


def set_mute(muted):
    return send(["set_property", "mute", bool(muted)])
