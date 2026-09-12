# -*- coding: utf-8 -*-
"""
A minimal local HTTP server (stdlib only, no new dependencies) that
receives real navigation-depth reports from the Chrome Navigation
Tracker extension (resources/chrome_extension/), loaded into this
addon's isolated Chrome profile via a one-time manual "Load unpacked"
step (see README.md) - not via --load-extension, which Chrome no
longer supports (see default.py's launch_chrome() comments for why).
Also lets this addon request an actual back-navigation performed by
the extension itself (chrome.tabs.goBack()), rather than a synthetic
Alt+Left keystroke.

Why this exists: the addon's own Back-handling in controlwindow.py
previously counted its own simulated clicks as an approximation of
navigation depth, which drifts out of sync on sites whose internal
navigation doesn't create real, back-able history entries (confirmed
on a real device with PPV.st - Back would arm and then exit without
the page ever visibly changing, since Alt+Left had nowhere real to
go). The extension listens to Chrome's own navigation events instead
of guessing from clicks, and reports the real depth here.

Separately, and confirmed as the actual root cause on that same real
device: a site's own page JavaScript can call preventDefault() on the
Alt+Left keydown event to silently swallow it - a plain keydown
listener is sufficient, no fullscreen or Keyboard Lock API needed.
chrome.tabs.goBack(), called from the extension, operates at the same
browser-chrome level as clicking a real back button - page content
has no keydown event to intercept in the first place. This server's
/poll endpoint lets the extension check whether a back-navigation has
been requested, so it can perform it directly instead of this addon
sending a keystroke that the page can defeat.

Chrome extensions cannot write files to disk directly (no filesystem
access from a background service worker) - that's what Chrome's
Native Messaging system exists to bridge, but Native Messaging
requires registering a host in the Windows Registry, which is real
extra fragility for comparatively little benefit here. A plain local
HTTP server the extension fetch()es to needs no registration at all.

Mandatory fallback: if the extension never successfully reports (not
loaded, blocked, Chrome version mismatch, this server failed to
bind), has_reported() stays False and callers should fall back to
the existing click-counting + Alt+Left keystroke behaviour entirely -
this must never be the only way Back can work.
"""

import json
import sys
import threading

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import xbmc

REPORT_PORT = 19872


class _QuietHTTPServer(HTTPServer):
    """
    HTTPServer with a quieter handle_error(): the stdlib default
    prints a full traceback to stderr (which shows up in Kodi's log
    as a scary-looking error block) for what's usually a harmless,
    expected event - Chrome disconnecting abruptly while this server
    is mid-request, e.g. because this addon just terminated the
    Chrome process. Confirmed on a real device: a ConnectionResetError
    at the exact moment "Chrome process ended" was logged, immediately
    after this addon's own process.terminate() call - not a real
    problem, just noisy. Logs a single quiet line instead; anything
    other than the expected connection-reset case still gets a full
    traceback, since that could be a genuine bug worth seeing.
    """

    def handle_error(self, request, client_address):
        exc_type = sys.exc_info()[0]
        if exc_type in (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            xbmc.log(
                '[plugin.program.quickbrowser] nav-depth server: client {} disconnected '
                'mid-request (expected if Chrome was closing at the time)'.format(
                    client_address
                ),
                xbmc.LOGDEBUG,
            )
        else:
            super(_QuietHTTPServer, self).handle_error(request, client_address)


class _NavDepthState(object):
    """Thread-safe holder for the latest reported depth and any
    pending go-back request."""

    def __init__(self):
        self._lock = threading.Lock()
        self._depth = None
        self._reported = False
        self._go_back_requested = False

    def set_depth(self, depth):
        with self._lock:
            self._depth = depth
            self._reported = True

    def get_depth(self):
        with self._lock:
            return self._depth

    def has_reported(self):
        with self._lock:
            return self._reported

    def request_go_back(self):
        with self._lock:
            self._go_back_requested = True

    def pop_go_back_request(self):
        """
        Returns whether a go-back was requested, and clears the flag
        in the same call - the extension's next /poll after this one
        will see False again, so a single request only fires once.
        """
        with self._lock:
            requested = self._go_back_requested
            self._go_back_requested = False
            return requested


class _ReportHandler(BaseHTTPRequestHandler):
    # Silence BaseHTTPRequestHandler's default per-request stderr
    # logging - /report fires on every navigation and /poll fires
    # every POLL_INTERVAL_MS from the extension, which would otherwise
    # spam Kodi's log at a volume out of proportion to its value.
    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/report':
            self._handle_report(parsed)
        elif parsed.path == '/poll':
            self._handle_poll()
        elif parsed.path == '/goback_result':
            self._handle_goback_result(parsed)
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_goback_result(self, parsed):
        """
        Surfaces the actual outcome of the extension's
        chrome.tabs.goBack() call straight into Kodi's own log - this
        has been the actual open question across several rounds of
        real-device testing, and the extension's own console isn't
        visible from Kodi's log without a separate manual check each
        time.
        """
        params = parse_qs(parsed.query)
        ok = params.get('ok', ['0'])[0] == '1'
        error = params.get('error', [None])[0]

        if ok:
            xbmc.log(
                '[plugin.program.quickbrowser] chrome.tabs.goBack() reported success',
                xbmc.LOGINFO,
            )
        else:
            xbmc.log(
                '[plugin.program.quickbrowser] chrome.tabs.goBack() reported FAILURE: {}'.format(
                    error or '(no error message)'
                ),
                xbmc.LOGWARNING,
            )

        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _handle_report(self, parsed):
        params = parse_qs(parsed.query)
        try:
            depth = int(params.get('depth', ['0'])[0])
        except (ValueError, IndexError):
            self.send_response(400)
            self.end_headers()
            return

        # Logged at INFO (not DEBUG) - this is exactly the raw event
        # data needed to diagnose depth jumping back up unexpectedly
        # between Back presses, confirmed happening on a real device
        # on both YouTube and PPV.st. Reporting it directly here means
        # it shows up in a normal log capture, rather than needing a
        # separate manual check of the extension's own Chrome-side
        # console every time this needs investigating further.
        transition_type = params.get('transitionType', [''])[0]
        qualifiers = params.get('qualifiers', ['[]'])[0]
        xbmc.log(
            '[plugin.program.quickbrowser] nav event report: depth={} transitionType={} '
            'qualifiers={}'.format(depth, transition_type, qualifiers),
            xbmc.LOGINFO,
        )

        self.server.nav_depth_state.set_depth(depth)

        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _handle_poll(self):
        go_back = self.server.nav_depth_state.pop_go_back_request()
        body = json.dumps({'goBack': go_back}).encode('utf-8')

        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class NavDepthServer(object):
    """
    Wraps HTTPServer + a background thread running it, plus the
    shared state the extension's reports are written into. start()
    returns False (and logs why) if the port couldn't be bound,
    rather than raising - callers should treat that exactly like the
    extension never having loaded, and fall back accordingly.
    """

    def __init__(self, port=REPORT_PORT):
        self.port = port
        self._httpd = None
        self._thread = None
        self.state = _NavDepthState()

    def start(self):
        try:
            self._httpd = _QuietHTTPServer(('127.0.0.1', self.port), _ReportHandler)
        except OSError as exc:
            xbmc.log(
                '[plugin.program.quickbrowser] Could not start nav-depth server on port {}: {} '
                '- falling back to click-based depth counting'.format(self.port, exc),
                xbmc.LOGWARNING,
            )
            return False

        self._httpd.nav_depth_state = self.state
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        xbmc.log(
            '[plugin.program.quickbrowser] Nav-depth server listening on 127.0.0.1:{}'.format(
                self.port
            ),
            xbmc.LOGINFO,
        )
        return True

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def has_reported(self):
        return self.state.has_reported()

    def get_depth(self):
        return self.state.get_depth()

    def request_go_back(self):
        self.state.request_go_back()
