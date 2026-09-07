# -*- coding: utf-8 -*-
import json
import os
import subprocess
import urllib.parse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import winctl
from . import mpvipc

ADDON = xbmcaddon.Addon()

PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
if not xbmcvfs.exists(PROFILE):
    xbmcvfs.mkdirs(PROFILE)
STATE_FILE = os.path.join(PROFILE, "pip_state.json")

KODI_WINDOW_TITLE_DEFAULT = "Kodi"        # exact window title Kodi normally uses
MPV_WINDOW_TITLE = "Kodi PiP"             # forced via --title on launch


def kodi_window_title():
    """
    Custom/rebranded Kodi builds sometimes title their window differently
    than plain "Kodi" (the addon's install path here shows a "Red Wizard"
    build, for instance). find_window() needs an exact match, so if swap
    can't find Kodi's window, check the real title (Task Manager > Details
    > right-click column headers > enable "Window Title", or a tool like
    Spy++) and set it here rather than needing a code change.
    """
    return ADDON.getSetting("kodi_window_title") or KODI_WINDOW_TITLE_DEFAULT


def log(msg):
    xbmc.log("[service.pip] %s" % msg, xbmc.LOGINFO)


def verbose_logging_enabled():
    return ADDON.getSetting("verbose_logging") == "true"


def verbose_log(msg):
    """Extra detail beyond what's always logged - full mpv launch
    arguments, per-step reposition rects, successful JSON-RPC calls
    (only failures are logged unconditionally elsewhere), service.py's
    routine hide/show transitions, and the mpv install/download steps.
    Gated behind the verbose_logging setting so normal use doesn't
    accumulate this level of detail by default."""
    if verbose_logging_enabled():
        log("[VERBOSE] %s" % msg)


def get_kodi_debug_logging():
    """Reads Kodi's own core debug-logging setting (Settings > System >
    Logging > Enable debug logging), confirmed as the real underlying
    setting id via Kodi's own guisettings.xml structure - NOT an addon
    setting, this affects every addon's logging and Kodi's own internal
    log detail, not just ours.

    Returns True/False, or None if the read couldn't be trusted (either
    a Python-level exception, or a JSON-RPC-level error response, which
    executeJSONRPC never raises for - it always returns a valid string,
    just one containing an "error" key instead of "result" when Kodi
    rejects the call). Returning None rather than silently defaulting to
    False matters here: the caller uses this value to decide what to
    restore Kodi's setting to later, and treating an unknown state as a
    confident False could restore the wrong thing.
    """
    req = {
        "jsonrpc": "2.0", "method": "Settings.GetSettingValue",
        "params": {"setting": "debug.showloginfo"}, "id": 1,
    }
    try:
        resp = json.loads(xbmc.executeJSONRPC(json.dumps(req)))
    except Exception as e:
        log("failed to read Kodi's debug logging setting: %s" % e)
        return None

    if "error" in resp:
        log("Kodi rejected the debug-logging read: %s" % resp["error"])
        return None

    return bool(resp.get("result", {}).get("value", False))


def set_kodi_debug_logging(value):
    """Returns True only if Kodi's response genuinely confirmed the
    change, not just that the call didn't raise an exception -
    executeJSONRPC returns a valid string even when Kodi rejects the
    call at the JSON-RPC level, so the previous version (which only
    caught Python-level exceptions and otherwise assumed success) could
    never detect that kind of failure at all, silently proceeding as if
    Kodi's setting had genuinely changed when it hadn't."""
    req = {
        "jsonrpc": "2.0", "method": "Settings.SetSettingValue",
        "params": {"setting": "debug.showloginfo", "value": bool(value)}, "id": 1,
    }
    try:
        resp = json.loads(xbmc.executeJSONRPC(json.dumps(req)))
    except Exception as e:
        log("failed to set Kodi's debug logging setting: %s" % e)
        return False

    if "error" in resp:
        log("Kodi rejected the debug-logging write: %s" % resp["error"])
        return False

    return True


def sync_kodi_debug_logging():
    """
    Keeps Kodi's own debug logging in step with our verbose_logging
    setting, without stomping on a preference the user set independently
    for some other reason. Remembers whether Kodi's debug logging was
    already on the moment verbose_logging is turned on; if it wasn't,
    turns it on and remembers that we're the one who did so, then turns
    it back off (only if we were the one who turned it on) the moment
    verbose_logging is turned off again. Addon settings have no native
    on-change callback for a script-invoked architecture like this one,
    so this is meant to be called periodically from the background
    service's own poll loop rather than reacting instantly.

    Confirmed via direct code review (no way to reproduce Kodi's own
    JSON-RPC failures live from here) that a failed read or write here
    was previously indistinguishable from a successful one - "synced"
    got marked True unconditionally, regardless of whether Kodi's
    setting actually changed, and since the transition check below only
    re-fires on an OFF-to-ON change of verbose_logging itself, a failed
    attempt would never retry until the user toggled the setting off and
    back on again. This is exactly the shape of an intermittent fault:
    an occasional JSON-RPC-level failure looks identical to success from
    this function's perspective, permanently, until manually re-triggered.
    Now a failed read or write simply returns without persisting
    anything, so the unconditional per-tick call from the service's poll
    loop naturally retries on the very next tick instead of needing any
    dedicated retry logic here.

    Uses its own dedicated state file, not the PiP session one - that
    file gets fully replaced (not merged) at several call sites
    (start_pip, close_pip), which would silently wipe this tracking out
    every time a PiP session starts or stops.
    """
    verbose_state_file = os.path.join(PROFILE, "verbose_state.json")
    try:
        with open(verbose_state_file, "r", encoding="utf-8") as f:
            v_state = json.load(f)
    except Exception:
        v_state = {"synced": False, "kodi_debug_was_on_before": False}

    currently_verbose = verbose_logging_enabled()
    was_verbose = v_state.get("synced", False)

    if currently_verbose and not was_verbose:
        kodi_debug_before = get_kodi_debug_logging()
        if kodi_debug_before is None:
            return  # couldn't determine current state - retry next tick
        if not kodi_debug_before:
            if not set_kodi_debug_logging(True):
                return  # write failed - retry next tick
        v_state["kodi_debug_was_on_before"] = kodi_debug_before
        v_state["synced"] = True
    elif not currently_verbose and was_verbose:
        if not v_state.get("kodi_debug_was_on_before", False):
            if not set_kodi_debug_logging(False):
                return  # write failed - retry next tick
        v_state["synced"] = False
    else:
        return  # no transition, nothing to persist

    try:
        with open(verbose_state_file, "w", encoding="utf-8") as f:
            json.dump(v_state, f)
    except Exception as e:
        log("failed to save verbose-logging sync state: %s" % e)


# ---------------------------------------------------------------- state ----

def _default_state():
    return {"active": False, "mpv_pid": None, "audio_on_pip": False}


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default_state()


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        log("failed to save state: %s" % e)


# ------------------------------------------------------------- settings ----

def mpv_path():
    p = ADDON.getSetting("mpv_path")
    return p if p else r"C:\mpv\mpv.exe"


def pip_width_pct():
    try:
        return float(ADDON.getSetting("pip_width_pct")) / 100.0
    except Exception:
        return 0.40


def pip_corner():
    return ADDON.getSetting("pip_corner") or "3"  # enum index string, see settings.xml


def start_muted():
    return ADDON.getSetting("pip_muted") == "true"


def is_android():
    return xbmc.getCondVisibility("System.Platform.Android")


def android_mpv_package():
    return ADDON.getSetting("android_mpv_package") or "is.xyz.mpv"


def set_kodi_mute(muted, context):
    """Sets Kodi's own main-player mute state via Application.SetMute,
    checking the actual JSON-RPC response for an error rather than
    assuming success from a lack of exception - same rigor as
    get/set_kodi_debug_logging() above, and replaces what was previously
    duplicated, nearly identically, at two call sites (start_pip()'s
    launch-time main-stream mute, and swap_audio()'s Kodi-side mute).
    Returns True only if Kodi's response genuinely confirmed the change.
    `context` is a short label used only in the log message on failure,
    so a rejected call is traceable to which specific call site it came
    from (e.g. "muting the main stream" vs "the audio-swap mute call")."""
    req = {
        "jsonrpc": "2.0", "method": "Application.SetMute",
        "params": {"mute": bool(muted)}, "id": 1,
    }
    try:
        resp = json.loads(xbmc.executeJSONRPC(json.dumps(req)))
    except Exception as e:
        log("failed to set Kodi's mute state (%s): %s" % (context, e))
        return False

    if "error" in resp:
        log("Kodi rejected the mute call (%s): %s" % (context, resp["error"]))
        return False

    verbose_log("Application.SetMute(mute=%s, %s) succeeded" % (muted, context))
    return True


# ------------------------------------------------------------ resolving ----

def resolve_via_jsonrpc(plugin_path):
    """
    Try Files.PrepareDownload, which asks Kodi to resolve a plugin:// path
    to its underlying stream without starting playback. Works cleanly for
    add-ons that resolve to a plain http(s) URL. Returns a URL string or
    None if this approach didn't yield one.
    """
    req = {
        "jsonrpc": "2.0",
        "method": "Files.PrepareDownload",
        "params": {"path": plugin_path},
        "id": 1,
    }
    try:
        raw = xbmc.executeJSONRPC(json.dumps(req))
        resp = json.loads(raw)
    except Exception as e:
        log("PrepareDownload call failed: %s" % e)
        return None

    result = resp.get("result")
    if not result:
        log("PrepareDownload returned no result: %s" % resp)
        return None

    protocol = result.get("protocol")
    details = result.get("details", {})
    path = details.get("path")

    if protocol == "http" and path and path.startswith(("http://", "https://")):
        verbose_log("PrepareDownload resolved directly: %s" % path)
        return path

    # Some add-ons resolve to a path Kodi wraps for internal vfs proxying
    # instead of handing back a raw URL. That's not directly usable by an
    # external player, so treat it as "didn't work" and let the caller
    # fall back.
    log("PrepareDownload gave a non-direct result (protocol=%s path=%s); "
        "will need the fallback resolver" % (protocol, path))
    return None


def resolve_via_play_capture(plugin_path, timeout=90):
    """
    Fallback resolver: briefly ask Kodi's own player to play the plugin
    path (forcing the add-on to resolve it), grab the resolved file the
    instant playback starts, then stop it and resume whatever was
    playing before.

    Kodi only has one video player, so this genuinely stops the main
    stream rather than pausing it - there's no way around that with this
    technique. What this function DOES do is remember what was playing
    and restart it afterward, rather than leaving it stopped.

    A blank screen for up to `timeout` seconds with no ongoing feedback
    looks exactly like a failure - confirmed from a real report where
    that's exactly what happened: the wait was still legitimately in
    progress, but with nothing on screen to say so, so the natural
    (and reasonable) response was to force-close Kodi entirely rather
    than wait it out. A persistent progress dialog for the whole wait,
    with a working Cancel button, replaces a single brief notification
    at the start - it gives a safe way to bail out early that still
    triggers the normal resume/cleanup below, rather than the only
    escape being to kill Kodi itself.

    For a genuinely live stream, restarting its URL normally just
    rejoins at the live point, since there's no fixed timeline to have
    fallen behind on. For on-demand content, this restarts from
    wherever Kodi/the source naturally begins playback - it does not
    attempt to seek back to the exact previous position, since I can't
    reliably tell live from on-demand content here and a seek attempt
    on a live source could misbehave.

    The Loop pops its own native "Choose a Link" dialog (a plain
    xbmcgui.Dialog().select(), confirmed from its pre_play.py) for any
    item with more than one link, as part of resolving ANY play attempt
    on that item — including this automated one. That dialog needs a
    real person to actually look at the screen and pick an option, which
    can take much longer than a scraper's own resolve time. 90 seconds
    is a guess at "long enough for a person to notice and click," not a
    measured figure — adjust if it's still cutting people off. The main
    stream stays stopped for the full duration of that wait.
    """
    player = xbmc.Player()
    was_playing = player.isPlayingVideo()
    resume_url = None
    if was_playing:
        try:
            resume_url = player.getPlayingFile()
        except Exception:
            resume_url = None

    resolved = {"url": None}
    capturing = {"active": True}

    class _Catcher(xbmc.Player):
        def onAVStarted(self):
            # Kodi's player callbacks fire globally for ANY playback event
            # on Kodi's one player, not just playback this instance itself
            # started - catcher stays alive through the whole function,
            # including the finally block below where the main stream
            # gets resumed via a SEPARATE xbmc.Player().play(resume_url)
            # call. That resume also fires onAVStarted, and catcher
            # receives it too. Confirmed via a real log (Kodi's own
            # VideoPlayer::OpenFile lines, independent of this addon's own
            # tracking): the correct PiP target was genuinely resolved and
            # opened, but the main stream's own resume then silently
            # overwrote resolved["url"] with ITS OWN url right before this
            # function returned it - so mpv launched with the main
            # stream's channel instead of the actual PiP target, every
            # time the two differed.
            #
            # Only accepting the first firing (resolved["url"] is None)
            # fixes THAT case, but confirmed via a direct test to still
            # be wrong in a different one: if the PiP target's resolve
            # never fires at all - genuinely timed out, cancelled, or
            # aborted, never reaching onAVStarted even once - resolved
            # ["url"] is STILL None by the time the main stream's own
            # resume happens, so that guard alone would let the resume's
            # firing be wrongly accepted as if it were a successful
            # resolve of the PiP target, returning the main stream's own
            # channel as the supposed result. The capturing flag closes
            # this properly: it's explicitly turned off before the main
            # stream resume is even attempted, so nothing from that point
            # onward can be captured, regardless of whether the PiP
            # target's own resolve already succeeded, failed, or never
            # fired at all.
            try:
                if capturing["active"] and resolved["url"] is None:
                    resolved["url"] = self.getPlayingFile()
            except Exception:
                pass

    catcher = _Catcher()

    dialog = xbmcgui.DialogProgress()
    dialog.create(
        "Picture in Picture",
        "Resolving second stream - main stream will resume automatically.\n"
        "If a link-choice popup appears, select one.\n"
        "Cancel to give up and resume the main stream now."
    )

    # Created here, before the try block, so it's guaranteed available in
    # the finally block below regardless of what happens inside the try -
    # confirmed via a real test that catcher.play() raising before this
    # line was previously assigned would otherwise leave it undefined,
    # causing an UnboundLocalError inside finally's own resume-wait loop
    # and crashing the one function this addon most needs to never crash.
    monitor = xbmc.Monitor()

    try:
        catcher.play(plugin_path)

        waited = 0.0
        while waited < timeout and resolved["url"] is None:
            if dialog.iscanceled():
                break
            dialog.update(int(waited / timeout * 100))
            # waitForAbort cooperates with Kodi's shutdown/reload signal,
            # unlike a plain xbmc.sleep() loop. Confirmed from a real crash:
            # Kodi asked this script to stop (addon being reinstalled or
            # Kodi shutting down) while a plain-sleep version of this loop
            # was running; since that version never checked for the
            # request, Kodi waited its standard 5-second grace period, got
            # no response, and force-killed the script outright - which
            # happens instantly, mid-execution, giving the resume/cleanup
            # code below zero chance to run at all. That's exactly why the
            # main stream never came back afterward. Breaking out here the
            # moment an abort is requested means that cleanup gets a real
            # chance to run during a cooperative shutdown instead.
            if monitor.waitForAbort(0.2):
                break
            waited += 0.2
    except Exception as e:
        # catcher.play() itself failing outright (unlikely, but not
        # impossible) should be treated the same as any other resolve
        # failure - logged and returned as None - rather than propagating
        # an unhandled exception out of this function after cleanup runs.
        log("play-capture attempt raised an exception: %s" % e)
    finally:
        # This whole block is the actual resilience guarantee: it runs
        # regardless of whether resolving succeeded, timed out, was
        # cancelled, was aborted, or catcher.play() itself raised outright
        # (the one call above that isn't individually wrapped in its own
        # try/except) - a plain sequence of statements after the wait
        # loop would skip all of this if anything earlier raised, which
        # is exactly the class of bug that caused the main stream to
        # stay lost in the first place.
        dialog.close()
        capturing["active"] = False

        try:
            catcher.stop()
        except Exception:
            pass

        if resume_url:
            try:
                xbmc.Player().play(resume_url)
            except Exception as e:
                log("failed to resume main stream after PiP resolve: %s" % e)

            # play() is asynchronous - checking isPlayingVideo() with zero
            # delay risks catching it before playback has genuinely
            # started. Poll for a few seconds before concluding the
            # resume actually failed.
            resumed = False
            resume_wait = 0.0
            while resume_wait < 5.0:
                if xbmc.Player().isPlayingVideo():
                    resumed = True
                    break
                if monitor.waitForAbort(0.25):
                    break
                resume_wait += 0.25

            if not resumed:
                # A previous version tried a further fallback here,
                # re-resolving via ListItem.FileNameAndPath on the theory
                # that it captured the main stream's own original path.
                # Confirmed via a real log to be wrong: in this addon's
                # actual invocation - opening a SECOND item's context
                # menu to select it for PiP - that label reflects the
                # item the context menu is currently acting on (the PiP
                # target), not the main stream. Using it played the PiP
                # target's own path onto the main screen, so the "second
                # channel" ended up playing in both places at once. That
                # mechanism has been removed entirely rather than patched,
                # since the assumption it relied on was unsound generally,
                # not just wrong in one specific case - reporting the
                # failure honestly is safer than a further automated
                # attempt that could again play the wrong content.
                log("main stream failed to resume: %s" % resume_url)
                xbmcgui.Dialog().notification(
                    "Picture in Picture",
                    "Main stream failed to resume - it may be temporarily unavailable",
                    xbmcgui.NOTIFICATION_ERROR
                )

        # Force the visual return to fullscreen video, not just resuming
        # playback in the background - our own catcher.play(B) moments
        # earlier will have already pulled Kodi's GUI toward B's
        # (possibly failed) playback attempt, and simply restarting A's
        # playback in code doesn't by itself guarantee the GUI follows
        # it back. isPlayingVideo() makes this a safe no-op if nothing
        # ended up playing at all.
        if xbmc.Player().isPlayingVideo():
            xbmc.executebuiltin("ActivateWindow(fullscreenvideo)")

    if resolved["url"] is None:
        log("play-capture fallback timed out or was interrupted without resolving a URL")
        return None

    log("play-capture fallback resolved: %s" % resolved["url"])
    if was_playing:
        log("main stream was stopped and resume was attempted for: %s" % resume_url)
    return resolved["url"]


def resolve_stream(plugin_path):
    url = resolve_via_jsonrpc(plugin_path)
    if url:
        return url
    return resolve_via_play_capture(plugin_path)


def split_kodi_url(url):
    """
    Some resolved streams (confirmed: live TV via inputstream.ffmpegdirect
    / IPTV Simple) come back in Kodi's own pipe-delimited protocol-options
    syntax: <real_url>|Referer=<url-encoded>&User-Agent=<url-encoded>&...
    This is real, documented Kodi behaviour for passing custom HTTP
    headers alongside a URL (kodi.wiki/view/HTTP) - it is NOT understood
    by mpv at all. Without splitting this out, mpv just tries to open the
    entire pipe-and-headers string as one literal (and invalid) path,
    which fails silently on mpv's own side - nothing shows up in Kodi's
    log, since Kodi's own player already correctly stopped and resumed;
    mpv is the one choking, in its own separate process.

    Returns (clean_url, headers_dict). headers_dict is empty if there was
    no pipe section to parse (this is the normal case for on-demand
    sources like TorBox, which resolve to a plain URL already).
    """
    if "|" not in url:
        return url, {}

    clean_url, _, header_str = url.partition("|")
    headers = {}
    for pair in header_str.split("&"):
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        headers[key] = urllib.parse.unquote_plus(value)
    return clean_url, headers


def mpv_header_args(headers):
    """
    Translates Kodi's header dict into mpv's own, completely different
    syntax: --referrer and --user-agent are dedicated options for those
    two specific headers; every other header goes through
    --http-header-fields as comma-separated "Name: value" pairs. These
    are passed as individual argv elements directly to subprocess.Popen
    (never through a shell), so no extra quoting is needed around each
    field the way mpv's own shell-invocation examples show it.
    """
    args = []
    other_fields = []
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower == "referer":
            args.append("--referrer=%s" % value)
        elif key_lower == "user-agent":
            args.append("--user-agent=%s" % value)
        else:
            other_fields.append("%s: %s" % (key, value))
    if other_fields:
        args.append("--http-header-fields=%s" % ",".join(other_fields))
    return args


# --------------------------------------------------------------- launch ----

MARGIN = 0  # no gap between the PiP and the screen edge it's pinned to

PIP_ASPECT_RATIO = 9.0 / 16.0  # height/width - matches standard video aspect
                                # regardless of the screen's own aspect ratio


def _corner_position(corner_key, w, h):
    """(x, y) for a given corner key and window size. Corner keys match the
    pip_corner setting's enum indices: 0=TL, 1=TR, 2=BL, 3=BR."""
    sw, sh = winctl.get_screen_size()
    positions = {
        "0": (MARGIN, MARGIN),                              # top-left
        "1": (sw - w - MARGIN, MARGIN),                      # top-right
        "2": (MARGIN, sh - h - MARGIN),                      # bottom-left
        "3": (sw - w - MARGIN, sh - h - MARGIN),              # bottom-right
    }
    return positions.get(corner_key, positions["3"])


MAX_WIDTH_PCT = 1.0   # no longer capped below full screen width - the
                       # 50% ceiling this used to be existed only to keep
                       # the context menu visible, which is now handled
                       # by hiding the PiP while the menu is open instead,
                       # so it no longer needs to be avoided by size alone
MAX_HEIGHT_PCT = 1.0  # matches MAX_WIDTH_PCT's reasoning - the real
                       # off-screen prevention is the explicit clamping
                       # in _resize_from_corner below, not these percentages


def _base_size_px():
    """
    A maximum bounding box passed to mpv's --autofit as a size ceiling at
    launch - NOT the enforced final shape. mpv fits the real video within
    this box while preserving its actual aspect ratio, so the real result
    can end up smaller than this on one axis (a 4:3 stream, a vertical
    stream, whatever it actually is). Width is capped at MAX_WIDTH_PCT
    (effectively the full screen - see that constant's comment) regardless
    of what pip_width_pct is set to. 16:9 here is just a reasonable
    starting canvas guess for the height side of the ceiling; since
    autofit only ever constrains and never stretches, any real aspect
    ratio still ends up correctly sized within it.
    """
    sw = winctl.get_screen_size()[0]
    w = int(sw * min(pip_width_pct(), MAX_WIDTH_PCT))
    h = int(w * PIP_ASPECT_RATIO)
    return w, h


def start_pip(plugin_path):
    # Check this up front, not after resolving - resolving can now take up
    # to 90 seconds (see resolve_via_play_capture) and briefly interrupts
    # the main stream, so there's no reason to pay that cost only to reject
    # the request afterward. Android has no "active" concept to check since
    # it doesn't track a PiP session at all (launch-and-forget).
    #
    # This checks whether the mpv window is REALLY there right now, rather
    # than trusting the state file - if mpv was closed via its own window
    # controls instead of "Close PiP", the state file would still say
    # "active" forever with nothing to actually reject the request against.
    if not is_android():
        if winctl.find_window(MPV_WINDOW_TITLE):
            xbmcgui.Dialog().notification("Picture in Picture", "A PiP session is already running", icon=xbmcgui.NOTIFICATION_WARNING)
            return
        # Nothing's actually running - if the state file disagrees (stale
        # from an externally-closed mpv), quietly correct it rather than
        # carry that staleness forward into the new session.
        if load_state().get("active"):
            save_state(_default_state())

    url = resolve_stream(plugin_path)
    if not url:
        xbmcgui.Dialog().notification("Picture in Picture", "Could not resolve a stream URL", icon=xbmcgui.NOTIFICATION_ERROR)
        return

    clean_url, stream_headers = split_kodi_url(url)

    if is_android():
        # Strip Kodi's header syntax before handing off - mpv-android
        # receives a plain ACTION_VIEW intent, and there's no confirmed
        # way to attach custom HTTP headers through that mechanism, so a
        # stream whose server enforces a Referer/User-Agent check may
        # still fail here even with this fix. This at least gives a
        # working bare URL to streams that don't need those headers,
        # rather than the literal pipe-and-headers string, which would
        # never have worked regardless.
        package = android_mpv_package()
        cmd = "StartAndroidActivity(%s,android.intent.action.VIEW,video/*,%s)" % (package, clean_url)
        xbmc.executebuiltin(cmd)
        xbmcgui.Dialog().notification("Picture in Picture", "Sent to %s" % package)
        return

    max_w, max_h = _base_size_px()
    args = [
        mpv_path(),
        clean_url,
    ] + mpv_header_args(stream_headers) + [
        "--title=%s" % MPV_WINDOW_TITLE,
        "--autofit=%dx%d" % (max_w, max_h),
        "--geometry=+%d+%d" % (MARGIN, MARGIN),
        "--ontop",
        "--no-border",
        "--input-ipc-server=%s" % mpvipc.PIPE_NAME,
    ]
    verbose_log("mpv launch argv: %s" % args)
    try:
        proc = subprocess.Popen(args)
    except FileNotFoundError:
        if xbmcgui.Dialog().yesno("Picture in Picture", "mpv.exe not found. Download and install it automatically now?"):
            from . import mpv_installer
            if not mpv_installer.install_mpv_windows():
                return
            try:
                proc = subprocess.Popen(args)
            except Exception as e:
                log("failed to launch mpv after auto-install: %s" % e)
                xbmcgui.Dialog().notification("Picture in Picture", "Installed, but still couldn't launch mpv", icon=xbmcgui.NOTIFICATION_ERROR)
                return
        else:
            xbmcgui.Dialog().notification("Picture in Picture", "mpv.exe not found — check the mpv path in settings", icon=xbmcgui.NOTIFICATION_ERROR)
            return
    except Exception as e:
        log("failed to launch mpv: %s" % e)
        xbmcgui.Dialog().notification("Picture in Picture", "Failed to launch mpv", icon=xbmcgui.NOTIFICATION_ERROR)
        return

    # --autofit only sets a maximum bounding box - mpv fits the real video
    # inside it while preserving its actual aspect ratio, so the window
    # could end up smaller than max_w/max_h on one axis (a 4:3 stream, a
    # vertical stream, whatever it actually is). Wait for mpv to open the
    # file and settle into that real size, then position precisely based
    # on the ACTUAL result - not the guessed ceiling - so corner-pinning
    # stays flush regardless of the real shape.
    #
    # A single fixed-length wait isn't reliable - a live stream can take
    # much longer to connect and start rendering than an on-demand file
    # does, and if the window isn't ready yet when the single check
    # fires, this whole step silently does nothing, leaving the PiP
    # stuck at its initial top-left launch position forever regardless
    # of the corner actually configured in settings. Polling repeatedly
    # up to a generous timeout instead means a slow-starting stream still
    # gets correctly positioned once it's actually ready.
    hwnd = None
    waited = 0.0
    monitor = xbmc.Monitor()
    poll_interval = 0.3
    max_wait = 8.0
    while waited < max_wait:
        hwnd = winctl.find_window(MPV_WINDOW_TITLE)
        if hwnd:
            real_rect = winctl.get_rect(hwnd)
            if real_rect and real_rect[2] > 0 and real_rect[3] > 0:
                break
        if monitor.waitForAbort(poll_interval):
            break
        waited += poll_interval

    if not hwnd:
        # mpv's process launched, but its window never appeared within a
        # generous timeout - without --force-window, this now means mpv
        # most likely failed to open the stream at all and has already
        # exited (rather than the old behaviour of --force-window
        # keeping an empty window open indefinitely regardless, which
        # was almost certainly the actual cause of the main stream
        # appearing to "disappear": it wasn't stopped, it was hidden
        # behind that permanently-open blank always-on-top window).
        # Kodi's own main stream was never touched anywhere in this
        # launch path, so it should still genuinely be playing - this
        # just makes sure the GUI is actually showing it, in case
        # browsing to reach this item left the GUI somewhere else.
        log("mpv window never appeared - stream likely failed to open")
        xbmcgui.Dialog().notification("Picture in Picture", "PiP failed to start - stream may be unavailable", icon=xbmcgui.NOTIFICATION_ERROR)
        # Don't leave this process in limbo - if it's merely slow rather
        # than actually dead, it could still create a window later,
        # completely untracked by our own state (which never gets set to
        # active here). Terminating it now means "declared as failed"
        # and "actually stopped" can't drift apart.
        try:
            proc.kill()
        except Exception:
            pass
        if xbmc.Player().isPlayingVideo():
            xbmc.executebuiltin("ActivateWindow(fullscreenvideo)")
        return

    # Reassert the configured corner several times over the next few
    # seconds, not just once. mpv's own --autofit sizing only
    # finalizes once it has actually connected to the stream and
    # knows the real video dimensions - for a live network stream
    # that can happen well after the window itself first appears
    # with some placeholder size, meaning a single reposition right
    # here can land on that placeholder state, only for mpv to
    # quietly resize/reposition itself again moments later once the
    # real stream connects - landing back at whatever mpv's own
    # default position is, not the configured corner. Log evidence:
    # a real launch went from "URL resolved" to "script finished" in
    # under 2 seconds total, which is faster than a live HLS
    # connection genuinely settles, pointing at exactly this. Each
    # pass re-reads the current rect fresh, in case size changed
    # too, not just position.
    for step in range(6):
        real_rect = winctl.get_rect(hwnd)
        if real_rect:
            _, _, real_w, real_h = real_rect
            px, py = _corner_position(pip_corner(), real_w, real_h)
            winctl.set_rect(hwnd, px, py, real_w, real_h, topmost=True)
            verbose_log("reposition step %d: rect was %s, set to (%d, %d, %d, %d)" % (step + 1, real_rect, px, py, real_w, real_h))
        if monitor.waitForAbort(0.5):
            break

    if start_muted():
        if not mpvipc.set_mute(True):
            log("failed to mute mpv's own audio at launch - PiP may start audible unexpectedly")
        audio_on_pip = False
    else:
        # PiP starts audible - mute the main stream to preserve "exactly
        # one stream has audio" from the very first moment, not just
        # after the first Swap audio toggle. Without this, an unmuted
        # mpv launches alongside a main stream that was never told to
        # mute, and both play simultaneously.
        set_kodi_mute(True, "muting the main stream")
        audio_on_pip = True

    save_state({"active": True, "mpv_pid": proc.pid, "audio_on_pip": audio_on_pip})
    xbmcgui.Dialog().notification("Picture in Picture", "PiP started")

    # snap back to the main stream's fullscreen view now that B is running,
    # if there was a main stream playing at all
    if xbmc.Player().isPlayingVideo():
        xbmc.executebuiltin("ActivateWindow(fullscreenvideo)")


def close_pip(silent=False):
    """
    Tries a polite IPC "quit" first, then force-terminates by PID
    regardless of whether that worked — relying on IPC alone risks
    leaving mpv running as an orphan if its pipe isn't responding, while
    our own state would incorrectly say "closed". silent=True is for the
    automatic startup cleanup, so a normal Kodi launch (the common case,
    nothing to close) doesn't produce a notification every single time.
    """
    state = load_state()
    hwnd = winctl.find_window(MPV_WINDOW_TITLE)

    if hwnd:
        mpvipc.send(["quit"])
        pid = winctl.get_pid(hwnd)
    else:
        # No window found. state["mpv_pid"] is only ever non-None here if
        # a previous session ended uncleanly (a normal close always resets
        # it) - so this is specifically the "clean up after a crash" case.
        pid = state.get("mpv_pid")

    if pid:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            log("taskkill on PiP process failed: %s" % e)

    save_state(_default_state())

    # Every other cleanup path (start_pip's own success/failure branches,
    # the resolve fallback, service.py's automatic health-check) already
    # forces Kodi's GUI back to fullscreen video after closing PiP - this
    # was the one path that didn't, since a user-initiated "Close PiP"
    # never went through any of those. isPlayingVideo() makes this a safe
    # no-op if nothing's actually playing.
    if xbmc.Player().isPlayingVideo():
        xbmc.executebuiltin("ActivateWindow(fullscreenvideo)")

    if not silent:
        if hwnd or pid:
            xbmcgui.Dialog().notification("Picture in Picture", "PiP closed")
        else:
            xbmcgui.Dialog().notification("Picture in Picture", "No PiP was running")


# -------------------------------------------------------- move / resize ----

def _current_quadrant(x, y, w, h, sw, sh):
    """Which quadrant of the screen a window's center currently falls in,
    as (is_left, is_top). Shared by snap_direction() and
    _resize_from_corner(), which both need to know this same thing about
    the PiP's current position - previously computed identically but
    separately in each, which worked but meant nothing would ever catch
    them being edited to disagree."""
    is_left = (x + w / 2.0) < (sw / 2.0)
    is_top = (y + h / 2.0) < (sh / 2.0)
    return is_left, is_top


def snap_direction(direction):
    """
    Moves the PiP to whichever corner matches this direction, keeping it on
    its current side otherwise - e.g. "up" snaps to top-left if the PiP is
    currently on the left half of the screen, top-right if on the right
    half. Two presses reach any corner. Position only - size is untouched.
    """
    hwnd = winctl.find_window(MPV_WINDOW_TITLE)
    rect = winctl.get_rect(hwnd) if hwnd else None
    if not rect:
        xbmcgui.Dialog().notification("Picture in Picture", "No PiP window found")
        return

    x, y, w, h = rect
    sw, sh = winctl.get_screen_size()
    is_left, is_top = _current_quadrant(x, y, w, h, sw, sh)

    corner_for_direction = {
        "up": "0" if is_left else "1",
        "down": "2" if is_left else "3",
        "left": "0" if is_top else "2",
        "right": "1" if is_top else "3",
    }
    corner_key = corner_for_direction.get(direction)
    if corner_key is None:
        return

    tx, ty = _corner_position(corner_key, w, h)
    winctl.set_rect(hwnd, tx, ty, w, h, topmost=True)
    winctl.show(hwnd)  # undo any hide the service applied while the menu was open


def _resize_step():
    """Grow/shrink step size: 50% of the configured base PiP width, e.g.
    20% of screen width at the 40% default - a fixed amount tied to the
    settings, not a compounding percentage of the current size."""
    base_w, _ = _base_size_px()
    return int(base_w * 0.5)


def _resize_from_corner(dw):
    """
    Resizes by keeping whichever corner the PiP currently favours fixed
    in place - only the far edges move as it grows or shrinks. A
    previous version resized around the window's geometric center
    instead, relying on the off-screen clamp below to incidentally keep
    it flush against its starting corner - that worked while the box was
    still touching both of that corner's edges, but once it grew large
    enough (or its aspect ratio didn't match the screen's) that it
    stopped touching one of them, "center" and "corner" stopped being
    the same reference point, and Shrink would pull back toward wherever
    the center had drifted to rather than back toward home.

    Takes a single width delta - height is derived from the resulting
    width using the window's OWN CURRENT aspect ratio (read fresh from
    its live size each call), which reflects whatever the actual playing
    video's real shape is - not a fixed assumption - so growing/shrinking
    a 4:3 stream stays 4:3, a 21:9 stream stays 21:9, a vertical stream
    stays vertical, etc.

    Also clamps the final position so the window can never end up partly
    off-screen, and caps the maximum size (checked against both screen
    dimensions, since the derived height could hit the screen's height
    limit before the width hits its own).
    """
    hwnd = winctl.find_window(MPV_WINDOW_TITLE)
    rect = winctl.get_rect(hwnd) if hwnd else None
    if not rect:
        xbmcgui.Dialog().notification("Picture in Picture", "No PiP window found")
        return

    x, y, w, h = rect
    if w <= 0:
        return
    ratio = h / float(w)  # the video's actual current on-screen shape

    sw, sh = winctl.get_screen_size()

    # Which corner is this PiP currently closer to? Same quadrant test
    # snap_direction uses - resize extends away from that corner, keeping
    # its pixel position exactly fixed, rather than from the window's
    # geometric center.
    is_left, is_top = _current_quadrant(x, y, w, h, sw, sh)

    max_w_for_width_cap = int(sw * MAX_WIDTH_PCT)
    max_w_for_height_cap = int(sh * MAX_HEIGHT_PCT / ratio) if ratio > 0 else max_w_for_width_cap
    max_w = min(max_w_for_width_cap, max_w_for_height_cap)
    min_w = 160

    new_w = min(max_w, max(min_w, w + dw))
    new_h = int(new_w * ratio)

    new_x = x if is_left else x + w - new_w
    new_y = y if is_top else y + h - new_h
    new_x = max(0, min(new_x, sw - new_w))
    new_y = max(0, min(new_y, sh - new_h))

    winctl.set_rect(hwnd, new_x, new_y, new_w, new_h, topmost=True)
    winctl.show(hwnd)  # undo any hide the service applied while the menu was open


def grow():
    _resize_from_corner(_resize_step())


def shrink():
    _resize_from_corner(-_resize_step())


# -------------------------------------------------------------- swap -----

def swap():
    """
    Swaps the on-screen geometry of Kodi's window and mpv's PiP window -
    position/size only. Audio is controlled independently via
    swap_audio() and is not affected by this at all, so swapping which
    window is "big" doesn't also move the sound around unless you
    separately choose to.
    Requires Kodi to be running in Windowed / Full screen window mode —
    if Kodi owns the full exclusive-fullscreen surface it isn't a normal
    movable OS window and this will silently fail to find/move it.
    Windows only — this whole function is unreachable on Android since
    the context menu hides the swap item there.
    """
    kodi_hwnd = winctl.find_window(kodi_window_title())
    mpv_hwnd = winctl.find_window(MPV_WINDOW_TITLE)
    if not kodi_hwnd or not mpv_hwnd:
        xbmcgui.Dialog().notification(
            "Picture in Picture",
            "Couldn't find both windows — check Kodi is windowed, and the "
            "Kodi window title setting matches (Task Manager > Details)",
            icon=xbmcgui.NOTIFICATION_ERROR
        )
        return

    # mpv keeps its always-on-top flag regardless of which side of the
    # swap it ends up on; Kodi's window never needs to be forced topmost.
    if not winctl.swap_rects(kodi_hwnd, mpv_hwnd, topmost_a=False, topmost_b=True):
        xbmcgui.Dialog().notification("Picture in Picture", "Swap failed")
        return
    winctl.show(mpv_hwnd)  # undo any hide the service applied while the menu was open

    xbmcgui.Dialog().notification("Picture in Picture", "Swapped main/PiP")


def swap_audio():
    """
    Toggles which of the two streams has audio, independent of window
    position/size. Exactly one side is ever audible - the other is
    explicitly muted. This always SETS both mute states outright based on
    its own tracked flag, rather than toggling either player's mute
    relatively, so it self-corrects even if something else changed either
    player's mute state in between calls - reading mpv's live mute state
    back over its IPC pipe was avoided deliberately, since that risks a
    blocking read with no confirmed-safe timeout behaviour.
    """
    hwnd = winctl.find_window(MPV_WINDOW_TITLE)
    if not hwnd:
        xbmcgui.Dialog().notification("Picture in Picture", "No PiP window found")
        return

    state = load_state()
    now_audio_on_pip = not state.get("audio_on_pip", False)
    state["audio_on_pip"] = now_audio_on_pip
    save_state(state)

    if not mpvipc.set_mute(not now_audio_on_pip):  # mpv audible only when audio is on PiP
        log("failed to set mpv's own mute state during audio swap - mpv's audio may not match what was requested")

    set_kodi_mute(now_audio_on_pip, "the audio-swap mute call")  # Kodi muted when audio is on PiP

    xbmcgui.Dialog().notification(
        "Picture in Picture", "Audio: %s" % ("PiP" if now_audio_on_pip else "Main stream")
    )
    winctl.show(hwnd)  # undo any hide the service applied while the menu was open - same
                        # immediate reveal every other menu action gets, rather than
                        # waiting on the service's slower safety-net poll to catch it
