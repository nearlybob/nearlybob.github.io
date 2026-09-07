# -*- coding: utf-8 -*-
"""
Automated mpv acquisition, so "no mpv found" doesn't have to mean "go
find the right file on GitHub yourself."

Windows: downloads the latest plain x86_64 build from shinchiro's project
and extracts it automatically using a bundled 7zr.exe (LZMA SDK, public
domain - see resources/bin/README.txt). No .zip-format mpv build exists
anywhere (checked), so a .7z-capable extractor is unavoidable if this is
to be fully automatic rather than "download it, then go install 7-Zip
yourself."

Android: there's no equivalent "extract and run" step to automate - APK
installation always requires at least one OS-level confirmation tap, by
design, on every Android version. What this DOES automate is skipping
the "find the right release page and right asset" step: it queries
GitHub directly for the latest APK and opens that exact file's URL,
which starts the download immediately in the browser.
"""
import json
import os
import re
import subprocess
import urllib.request

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import pip_core

MPV_WINDOWS_API = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
MPV_ANDROID_API = "https://api.github.com/repos/mpv-android/mpv-android/releases/latest"
MPVNOVA_API = "https://api.github.com/repos/Laskco/mpvNova/releases/latest"

MPV_ANDROID_PACKAGE = "is.xyz.mpv"
MPVNOVA_PACKAGE = "app.mpvnova.player"

# Matches e.g. mpv-x86_64-20260830-git-e8673660ab.7z - the plain 64-bit
# build. Deliberately excludes mpv-dev-*, mpv-x86_64-v3-*, mpv-i686-*,
# mpv-aarch64-*, and the standalone ffmpeg-*.7z assets in the same release.
WINDOWS_ASSET_PATTERN = re.compile(r"^mpv-x86_64-\d{8}-git-[0-9a-f]+\.7z$")

USER_AGENT = "service.pip"


def _addon():
    return xbmcaddon.Addon()


def _addon_path():
    return xbmcvfs.translatePath(_addon().getAddonInfo("path"))


def _profile_path():
    p = xbmcvfs.translatePath(_addon().getAddonInfo("profile"))
    if not xbmcvfs.exists(p):
        xbmcvfs.mkdirs(p)
    return p


def _fetch_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        pip_core.log("mpv_installer: failed to fetch %s: %s" % (url, e))
        return None


# --------------------------------------------------------------- Windows ---

def _bundled_extractor():
    candidate = os.path.join(_addon_path(), "resources", "bin", "7zr.exe")
    return candidate if os.path.isfile(candidate) else None


def _system_extractor():
    """Fallback if the bundled 7zr.exe isn't present for some reason -
    checks common 7-Zip install locations and PATH."""
    candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        c = os.path.join(path_dir, "7z.exe")
        if os.path.isfile(c):
            return c
    return None


def _get_extractor():
    return _bundled_extractor() or _system_extractor()


def find_latest_windows_asset():
    """Returns (download_url, filename) for the latest plain x86_64 mpv
    build, or (None, None) if the lookup or matching failed."""
    data = _fetch_json(MPV_WINDOWS_API)
    if not data:
        return None, None
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if WINDOWS_ASSET_PATTERN.match(name):
            return asset.get("browser_download_url"), name
    pip_core.log("mpv_installer: no matching Windows asset in latest release")
    return None, None


def install_mpv_windows():
    """
    Downloads and extracts the latest mpv build to the folder implied by
    the mpv_path setting (or C:\\mpv if that's still unset/default).
    Returns True on success.
    """
    extractor = _get_extractor()
    if not extractor:
        xbmcgui.Dialog().notification(
            "Picture in Picture",
            "No 7z extractor found - see resources/bin/README.txt",
            icon=xbmcgui.NOTIFICATION_ERROR
        )
        return False
    pip_core.verbose_log("using extractor: %s" % extractor)

    url, filename = find_latest_windows_asset()
    pip_core.verbose_log("latest windows asset resolved to: %s (%s)" % (filename, url))
    if not url:
        xbmcgui.Dialog().notification("Picture in Picture", "Could not find an mpv build to download", icon=xbmcgui.NOTIFICATION_ERROR)
        return False

    download_path = os.path.join(_profile_path(), filename)

    dialog = xbmcgui.DialogProgress()
    dialog.create("Picture in Picture", "Downloading mpv...")

    def _report(block_num, block_size, total_size):
        if total_size > 0:
            pct = min(100, int(block_num * block_size * 100 / total_size))
            dialog.update(pct, "Downloading mpv...")
        if dialog.iscanceled():
            raise RuntimeError("cancelled by user")

    try:
        urllib.request.urlretrieve(url, download_path, reporthook=_report)
    except Exception as e:
        dialog.close()
        pip_core.log("mpv_installer: download failed: %s" % e)
        xbmcgui.Dialog().notification("Picture in Picture", "mpv download failed or was cancelled", icon=xbmcgui.NOTIFICATION_ERROR)
        return False

    dialog.update(100, "Extracting...")

    target_dir = os.path.dirname(pip_core.mpv_path()) or r"C:\mpv"
    try:
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir)
    except Exception as e:
        dialog.close()
        pip_core.log("mpv_installer: could not create target dir %s: %s" % (target_dir, e))
        xbmcgui.Dialog().notification("Picture in Picture", "Could not create the mpv folder", icon=xbmcgui.NOTIFICATION_ERROR)
        return False

    try:
        result = subprocess.run(
            [extractor, "x", download_path, "-o%s" % target_dir, "-y"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return_code = result.returncode
    except Exception as e:
        dialog.close()
        pip_core.log("mpv_installer: extraction failed to run: %s" % e)
        xbmcgui.Dialog().notification("Picture in Picture", "mpv extraction failed to run", icon=xbmcgui.NOTIFICATION_ERROR)
        return False

    dialog.close()

    try:
        os.remove(download_path)
    except Exception:
        pass

    exe_path = os.path.join(target_dir, "mpv.exe")
    pip_core.verbose_log("extractor return code: %s, expected mpv.exe at: %s" % (return_code, exe_path))
    if return_code == 0 and os.path.isfile(exe_path):
        xbmcgui.Dialog().notification("Picture in Picture", "mpv installed to %s" % target_dir)
        return True

    xbmcgui.Dialog().notification("Picture in Picture", "mpv extraction did not produce mpv.exe", icon=xbmcgui.NOTIFICATION_ERROR)
    return False


# --------------------------------------------------------------- Android ---

def _android_variant_is_nova():
    return _addon().getSetting("android_mpv_variant") == "1"


def find_latest_android_apk():
    """Returns a direct APK download URL from the selected variant's
    (mpv-android or mpvNova) latest release, preferring a universal
    build where available, or None if the lookup failed."""
    api_url = MPVNOVA_API if _android_variant_is_nova() else MPV_ANDROID_API
    data = _fetch_json(api_url)
    if not data:
        return None
    assets = [a for a in data.get("assets", []) if a.get("name", "").endswith(".apk")]
    for a in assets:
        if "universal" in a.get("name", "").lower():
            return a.get("browser_download_url")
    return assets[0].get("browser_download_url") if assets else None


def open_android_download():
    """
    Opens the latest APK's direct download URL for whichever variant is
    selected in settings, and updates android_mpv_package to match
    automatically - so picking a variant and clicking this once keeps
    the download and the package the addon later launches in sync,
    rather than needing a separate manual step to update both.

    Does not and cannot skip Android's own install-confirmation tap(s)
    afterward - that's an OS-level requirement, not something any app
    can automate around.
    """
    url = find_latest_android_apk()
    if not url:
        xbmcgui.Dialog().notification("Picture in Picture", "Could not find an APK to download", icon=xbmcgui.NOTIFICATION_ERROR)
        return

    is_nova = _android_variant_is_nova()
    correct_package = MPVNOVA_PACKAGE if is_nova else MPV_ANDROID_PACKAGE
    try:
        _addon().setSetting("android_mpv_package", correct_package)
    except Exception as e:
        pip_core.log("mpv_installer: failed to auto-update android_mpv_package: %s" % e)

    # Empty package lets Android resolve this the normal way (whatever
    # handles http/https links, same as tapping the link yourself) rather
    # than hardcoding a specific browser that might not be installed.
    xbmc.executebuiltin("StartAndroidActivity(,android.intent.action.VIEW,,%s)" % url)
    xbmcgui.Dialog().notification("Picture in Picture", "Opening %s download..." % ("mpvNova" if is_nova else "mpv-android"))
