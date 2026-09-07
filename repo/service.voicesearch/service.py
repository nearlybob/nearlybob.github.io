# -*- coding: utf-8 -*-
"""
Kodi service addon: launches the external voice-search watcher script
(running on Windows' own system Python, NOT Kodi's bundled Python
interpreter) when Kodi starts, and terminates it cleanly when Kodi
shuts down.

If the required Python/packages aren't present yet, this automatically
runs the bundled setup .bat in the background (no menu click needed),
shows a Kodi notification while it works, and starts the watcher the
moment setup finishes -- using the exact Python path the .bat resolved
and wrote back, so no Kodi restart is needed even on a fresh install.

This addon does no speech recognition itself -- it only starts and
stops an external process, the same way a service addon might launch
an external player binary. All the actual dependencies
(pywin32 / SpeechRecognition / pyaudio / websocket-client / requests)
live in the separate system Python environment the .bat sets up.

FILES this addon reads/writes, all under this addon's userdata folder
(special://userdata/addon_data/service.voicesearch/):
  - config.txt          : engine=microsoft|google, kodi_username,
                           kodi_password, optional manual python_path
                           override. Created with defaults on first
                           run. kodi_username/kodi_password are
                           overwritten every startup from this addon's
                           own Settings (Configure screen) -- set them
                           there, not by editing this file.
  - python_path.txt      : written automatically by the setup .bat once
                            it resolves where Python actually is.
  - setup_log.txt         : full output of the last setup run, for
                             troubleshooting.
  - setup_failed.flag     : written if automatic setup fails, to avoid
                             retrying (and re-downloading) every single
                             Kodi startup. Delete this file (or run the
                             addon manually from Program Add-ons) to
                             force another attempt.
  - installed_version.txt : tracks the last-run addon version, used to
                             show a one-time "please restart Kodi" note
                             after an update.
"""

import os
import subprocess
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("name")
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
BAT_PATH = os.path.join(ADDON_PATH, "resources", "setup_kodi_voice_search.bat")

LOG_PREFIX = "[service.voicesearch] "

DEFAULT_CONFIG = (
    "# Kodi Voice Search configuration\n"
    "# engine: microsoft  OR  google\n"
    "engine=google\n"
    "\n"
    "# Leave blank to use the path auto-detected by setup (see\n"
    "# python_path.txt in this same folder). Set this only if you need\n"
    "# to override that, e.g. a non-standard Python install location:\n"
    "# python_path=C:\\Users\\YourName\\AppData\\Local\\Programs\\Python\\Python313\\pythonw.exe\n"
    "python_path=\n"
    "\n"
    "# Kodi web server credentials (Settings > Services > Control).\n"
    "# These are normally set via this addon's own Settings screen\n"
    "# (Add-ons > Kodi Voice Search > Configure) rather than edited\n"
    "# here directly -- that screen overwrites these two lines on every\n"
    "# Kodi startup, so a manual edit here won't stick.\n"
    "kodi_username=kodi\n"
    "kodi_password=\n"
)


def log(message, level=xbmc.LOGINFO):
    xbmc.log(LOG_PREFIX + message, level)


def notify(message, time_ms=6000):
    xbmcgui.Dialog().notification(ADDON_NAME, message, xbmcgui.NOTIFICATION_INFO, time_ms)


def ensure_config_exists():
    if not xbmcvfs.exists(PROFILE_PATH):
        xbmcvfs.mkdirs(PROFILE_PATH)
    config_path = os.path.join(PROFILE_PATH, "config.txt")
    if not xbmcvfs.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG)
        log(f"Created default config at {config_path}")
    return config_path


def read_config(config_path):
    settings = {}
    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                settings[key.strip()] = value.strip()
    return settings


def sync_config_from_settings(config_path):
    """Overwrite kodi_username/kodi_password in config.txt with whatever
    is currently set in this addon's own Settings (Add-ons > Kodi Voice
    Search > Configure), so users configure web server credentials
    through Kodi's UI instead of hand-editing config.txt. Every other
    line in config.txt (engine, python_path, comments) is preserved
    exactly as-is."""
    username = ADDON.getSettingString("kodi_username").strip() or "kodi"
    password = ADDON.getSettingString("kodi_password")
    values_to_set = {"kodi_username": username, "kodi_password": password}

    with open(config_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    written_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        key = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
        if key in values_to_set:
            new_lines.append(f"{key}={values_to_set[key]}\n")
            written_keys.add(key)
        else:
            new_lines.append(line)

    for key, value in values_to_set.items():
        if key not in written_keys:
            new_lines.append(f"{key}={value}\n")

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def check_for_update_and_notify():
    """If this addon's version differs from the one recorded on its
    last run, an update just happened. Settings/behaviour changes in
    an update -- including a newly-set web server password -- don't
    reliably take effect on an already-running Kodi session (this
    background service itself only runs its startup logic once, at
    Kodi startup). Tell the user plainly rather than leave voice
    search silently not working after an update."""
    version_file = os.path.join(PROFILE_PATH, "installed_version.txt")
    current_version = ADDON.getAddonInfo("version")
    previous_version = None
    if xbmcvfs.exists(version_file):
        with open(version_file, "r", encoding="utf-8") as f:
            previous_version = f.read().strip()

    if previous_version and previous_version != current_version:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            f"Updated from v{previous_version} to v{current_version}.\n\n"
            "Please restart Kodi now for this update to take full effect.",
        )

    with open(version_file, "w", encoding="utf-8") as f:
        f.write(current_version)


def read_auto_detected_python_path():
    path_file = os.path.join(PROFILE_PATH, "python_path.txt")
    if xbmcvfs.exists(path_file):
        with open(path_file, "r", encoding="utf-8") as f:
            value = f.read().strip()
            return value or None
    return None


def resolve_python_exe(config_settings):
    # Priority: explicit manual override in config.txt > auto-detected
    # by the setup .bat > bare "pythonw.exe" relying on PATH as a last
    # resort (only useful if Kodi happens to already share Python's
    # PATH, e.g. after a manual restart).
    manual = config_settings.get("python_path", "").strip()
    if manual:
        return manual
    auto = read_auto_detected_python_path()
    if auto:
        return auto
    return "pythonw.exe"


def resolve_watcher_script(engine):
    filename = (
        "kodi_voice_watcher_google.py"
        if engine == "google"
        else "kodi_voice_watcher_microsoft.py"
    )
    return os.path.join(ADDON_PATH, "resources", "lib", filename)


def setup_failed_flag_path():
    return os.path.join(PROFILE_PATH, "setup_failed.flag")


def run_setup_and_wait():
    """Run the bundled setup .bat unattended, blocking until it
    finishes. Returns True on success."""
    if not xbmcvfs.exists(BAT_PATH):
        log(f"Setup script not found: {BAT_PATH}", xbmc.LOGERROR)
        return False

    log("Running first-time setup in the background (this can take a few minutes)...")
    notify("Installing required software -- this can take a few minutes.")

    # IMPORTANT: cmd.exe's own /c parsing has a well-known bug where
    # "cmd /c "path with spaces\file.bat" extra_arg" can fail to parse
    # correctly and exit almost instantly (seen in practice with
    # portable Kodi installs, e.g. "...\KODI TEST\Kodi\..."). The
    # documented fix is one extra pair of quotes around the whole
    # command. subprocess.run(..., shell=True) on Windows ALREADY adds
    # that outer "cmd /c "..."" wrapping for us automatically -- so we
    # only need normal single-layer quoting here, not an extra layer
    # on top (which was tried in 1.3.2 and still failed: two wrapping
    # layers is one too many).
    command = f'"{BAT_PATH}" silent "{PROFILE_PATH}"'

    try:
        result = subprocess.run(
            command,
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        log(f"Failed to run setup script: {e}", xbmc.LOGERROR)
        return False

    if result.returncode != 0:
        log(
            f"Setup script exited with code {result.returncode}. "
            f"See {os.path.join(PROFILE_PATH, 'setup_log.txt')} for details.",
            xbmc.LOGERROR,
        )
        return False

    log("Setup finished successfully.")
    notify("Setup finished -- voice search is now active.")
    return True


def launch_watcher(python_exe, script_path):
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # PROFILE_PATH is passed as an argument so the watcher (a separate,
    # non-Kodi-API-aware process) can find config.txt and read
    # kodi_username/kodi_password from it -- see sync_config_from_settings.
    return subprocess.Popen(
        [python_exe, script_path, PROFILE_PATH], creationflags=creationflags
    )


def launch_succeeded(proc, settle_seconds=2.0):
    """subprocess.Popen succeeding only means Windows found and started
    the executable -- it does NOT mean the script ran without error.
    If pythonw.exe is found but the required packages aren't installed
    (e.g. Python already existed on this PC before this addon did),
    the process starts and immediately crashes on the first `import`,
    silently (pythonw.exe has no console to show the traceback on).
    Give it a moment, then check it's still alive."""
    time.sleep(settle_seconds)
    return proc.poll() is None  # None means still running


def start_watcher_with_auto_setup(engine, config_settings):
    """Try to launch the watcher. If Python (or its required packages)
    can't be found/working, and setup hasn't already failed this
    install, run setup automatically and retry once."""
    script_path = resolve_watcher_script(engine)
    if not xbmcvfs.exists(script_path):
        log(f"Watcher script not found: {script_path}", xbmc.LOGERROR)
        return None

    python_exe = resolve_python_exe(config_settings)
    log(f"Attempting to start watcher: {python_exe} {script_path} (engine={engine})")

    try:
        proc = launch_watcher(python_exe, script_path)
        if launch_succeeded(proc):
            return proc
        log(
            f"Watcher process exited immediately (code {proc.returncode}) -- "
            "Python was found but the script failed to run, most likely "
            "because required packages aren't installed yet (e.g. Python "
            "already existed on this PC before this addon did).",
            xbmc.LOGWARNING,
        )
    except FileNotFoundError:
        log(f'"{python_exe}" could not be found.', xbmc.LOGWARNING)

    failed_flag = setup_failed_flag_path()
    if xbmcvfs.exists(failed_flag):
        log(
            "Watcher isn't runnable (Python or its packages missing), and a "
            "previous automatic setup attempt already failed. Not retrying "
            "automatically -- run this addon manually from Program Add-ons "
            "to force another attempt, or check "
            f"{os.path.join(PROFILE_PATH, 'setup_log.txt')}.",
            xbmc.LOGWARNING,
        )
        return None

    log("Running first-time setup automatically.")
    success = run_setup_and_wait()

    if not success:
        with open(failed_flag, "w", encoding="utf-8") as f:
            f.write("Automatic setup failed. Delete this file to retry.\n")
        notify("Setup failed -- check the Kodi log for details.", 8000)
        return None

    # Re-resolve now that setup may have written python_path.txt.
    python_exe = resolve_python_exe(config_settings)
    log(f"Retrying watcher launch after setup: {python_exe} {script_path}")
    try:
        proc = launch_watcher(python_exe, script_path)
        if launch_succeeded(proc):
            return proc
        log(
            f"Watcher still exited immediately (code {proc.returncode}) even "
            "after setup completed. Check the addon log above and "
            f"{os.path.join(PROFILE_PATH, 'setup_log.txt')} for what pip "
            "install actually did.",
            xbmc.LOGERROR,
        )
    except FileNotFoundError:
        log(
            f'Still could not find "{python_exe}" after setup completed. '
            "This shouldn't normally happen -- check "
            f"{os.path.join(PROFILE_PATH, 'setup_log.txt')}.",
            xbmc.LOGERROR,
        )

    with open(failed_flag, "w", encoding="utf-8") as f:
        f.write("Watcher launch failed even after setup. Delete this file to retry.\n")
    return None


class VoiceSearchMonitor(xbmc.Monitor):
    """Subclassed specifically to hook onSettingsChanged, which Kodi
    calls when this addon's own Settings dialog (Configure screen) is
    saved -- e.g. after changing the web server username/password.
    Lets us prompt for a restart right when the change happens,
    instead of only the next time Kodi itself starts."""

    def onSettingsChanged(self):
        log("Addon settings changed -- re-syncing config.txt.")
        try:
            config_path = ensure_config_exists()
            sync_config_from_settings(config_path)
        except Exception as e:
            log(f"Error re-syncing config.txt after settings change: {e}", xbmc.LOGERROR)

        xbmcgui.Dialog().ok(
            ADDON_NAME,
            "Settings saved.\n\n"
            "Please restart Kodi now for the change to take effect "
            "(the background watcher only reads these values once, "
            "at Kodi startup).",
        )


def main():
    config_path = ensure_config_exists()
    sync_config_from_settings(config_path)
    config_settings = read_config(config_path)
    engine = config_settings.get("engine", "google").lower()

    monitor = VoiceSearchMonitor()
    proc_holder = {"proc": None}

    def worker():
        try:
            check_for_update_and_notify()
            proc_holder["proc"] = start_watcher_with_auto_setup(engine, config_settings)
        except Exception as e:
            # start_watcher_with_auto_setup only explicitly handles
            # FileNotFoundError -- anything else (PermissionError,
            # OSError, etc.) would otherwise propagate out of this
            # thread silently: no log entry, no notification, nothing.
            # Since this runs in a background thread, an unhandled
            # exception here would be invisible rather than just
            # inconvenient.
            log(f"Unexpected error while starting watcher: {e}", xbmc.LOGERROR)

    # Run in a thread so a first-time setup (which can take minutes)
    # never blocks this service from responding to Kodi shutdown.
    t = threading.Thread(target=worker, daemon=True)
    t.start()

    while not monitor.abortRequested():
        if monitor.waitForAbort(5):
            break

    log("Kodi is shutting down -- stopping watcher process (if running)")
    proc = proc_holder.get("proc")
    if proc is not None:
        try:
            proc.terminate()
        except Exception as e:
            log(f"Error terminating watcher process: {e}", xbmc.LOGWARNING)


if __name__ == "__main__":
    main()
