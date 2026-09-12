// Quick Browser Navigation Tracker - background service worker
//
// Tracks real page-navigation depth per tab, grounded in Chrome's own
// navigation events rather than guessed from click count. Reports the
// current depth to a local helper server run by the Quick Browser Kodi
// addon, which uses it (when available) instead of its own click-based
// counter when deciding whether Back should navigate within the page
// or exit the addon.
//
// ALSO performs the actual back-navigation when asked, via
// chrome.tabs.goBack() - NOT via a synthetic Alt+Left keystroke.
// Confirmed on a real device: a site's own page JavaScript can (and
// on at least one real site, does) call preventDefault() on the
// Alt+Left keydown event to silently swallow it - no fullscreen or
// Keyboard Lock API needed for a page to do this, just a plain
// keydown listener. chrome.tabs.goBack() operates at the same
// browser-chrome level as clicking a real back button, which page
// content has no way to intercept, since there's no keydown event
// for it to listen for in the first place.
//
// Two event types are tracked for depth, both restricted to
// frameId === 0 (the top-level page, not embedded iframes - ad/player
// iframes navigating internally should not count as a step in the
// site's own history):
//
//   - webNavigation.onCommitted: fires for ordinary full-page
//     navigations (a normal link click, a redirect, etc.) AND for
//     back/forward navigation, including our own chrome.tabs.goBack()
//     calls.
//   - webNavigation.onHistoryStateUpdated: fires for same-document
//     SPA-style navigation via history.pushState() - this is the
//     mechanism YouTube's own internal navigation uses, and exactly
//     what the click-counting approach could never see.
//
// HOW BACK-VS-FORWARD IS DETECTED (revised, see history below): our
// own request/response correlation, not Chrome's transitionQualifiers
// metadata. When goBack() is called, pendingGoBackForTab is set to
// that tab's ID; the next top-frame event observed for that tab is
// then treated as the result of that request (decrement) rather than
// a new step forward (increment), then the flag is cleared. A short
// timeout also clears it if no event arrives, in case goBack()
// resolves without producing one (e.g. genuinely nothing to go back
// to) - otherwise the flag would stay stuck waiting for an event that
// never comes, and the NEXT unrelated forward navigation would be
// wrongly treated as a back-step.
//
// Why not transitionQualifiers, which is what an earlier version
// used: Chrome's own documentation is inconsistent about whether
// transitionQualifiers (specifically the 'forward_back' value, meant
// to indicate exactly this case) is populated for
// onHistoryStateUpdated as well as onCommitted - some pages describe
// the property only for onCommitted, others show example code reading
// it from onHistoryStateUpdated. Real device testing settled it:
// confirmed from a full session's logs on two different real sites
// (YouTube and PPV.st), transitionType and transitionQualifiers came
// back completely empty on every single event, including ordinary
// forward navigation, not just goBack()-triggered ones. Whatever the
// cause, relying on that metadata was not viable in practice, so this
// version doesn't depend on it at all - it's still reported to Kodi's
// log for visibility, but no longer used for the depth decision.
//
// Known limitation, stated honestly: onHistoryStateUpdated also fires
// for history.replaceState() calls, which do NOT create a new,
// back-able history entry (they replace the current one). Since this
// version's back/forward detection is based on our own goBack()
// request timing rather than qualifiers, a replaceState() call that
// happens to occur while a goBack() is pending could still be
// misattributed as the result of that request. This is a narrower,
// different edge case than the original click-counting drift - not
// eliminated entirely, but should be far less common in practice than
// the original problem (clicks that do nothing at all).
//
// A further, confirmed real bug (2026-09-11): chrome.tabs.goBack()
// rejects with an explicit error (e.g. "Cannot find a next page in
// history") when there's genuinely nowhere left to go - but a FAILED
// call produces no navigation event, and depth tracking is entirely
// event-driven, so the depth counter was staying stuck at whatever it
// was before the failure, forever, even though the rejection itself
// is exactly the signal needed to know depth is really 0. Fixed by
// explicitly resetting depth to 0 right in the rejection handler,
// rather than waiting for an event that will never come.
//
// A further race, found by tracing through the code rather than from
// a device report: two overlapping goBack() calls to the same tab
// (from rapid repeated Back presses, before the first request's
// promise has resolved) share the same tabId, so a plain tabId
// comparison in the timeout/rejection callbacks couldn't tell "my own
// request" apart from "a different, newer request to the same tab" -
// a stale callback from an older, already-superseded request could
// still match and incorrectly clear or reset state that now belongs
// to a newer one. Fixed with a monotonically incrementing token,
// unique per dispatch, checked instead of (not just alongside) the
// tabId comparison.
//
// The very first navigation event observed for a tab is treated as
// the starting page (depth 0), not counted as a step forward, since
// that's simply the kiosk URL Chrome was launched with.
//
// Command polling and the MV3 service worker lifecycle: MV3 service
// workers are suspended after ~30s of inactivity, and chrome.alarms
// (the "proper" MV3 way to schedule recurring work) has a 1-minute
// minimum period in production - too slow for a responsive Back
// press. Calling an extension API such as fetch() resets that 30s
// idle timer (confirmed against Chrome's own service worker lifecycle
// docs), so a short setInterval polling loop is self-sustaining: each
// poll's own fetch() call resets the timer before the worker can go
// idle. This is the least-tested part of this whole mechanism without
// a real device to confirm against - if it ever does lapse, the next
// real webNavigation event (which Chrome guarantees wakes a
// terminated service worker) restarts this script fresh, including
// the polling loop, as a natural safety net.

const HELPER_PORT = 19872;
const REPORT_URL = `http://localhost:${HELPER_PORT}/report`;
const POLL_URL = `http://localhost:${HELPER_PORT}/poll`;
const POLL_INTERVAL_MS = 500;

// How long to wait for a navigation event after calling goBack()
// before giving up on correlating it and clearing the pending flag
// anyway - see pendingGoBackForTab below for why this exists.
const PENDING_GOBACK_TIMEOUT_MS = 3000;

// tabId -> { depth: number }. Presence of a tabId in this map means
// its baseline (starting page) has already been established.
const tabState = new Map();

// The most recently observed tab - chrome.tabs.goBack() needs a
// target tabId, and a --kiosk session has effectively one tab.
let activeTabId = null;

// Set to a tabId right before calling chrome.tabs.goBack() on it;
// the next top-frame navigation event seen for that tab is treated as
// the result of that call (a step back) rather than a new step
// forward. Cleared either when that event arrives, or by a timeout
// as a safety net if goBack() doesn't produce one.
let pendingGoBackForTab = null;
let pendingGoBackTimeoutId = null;

// Monotonically incrementing - see pollForCommand() below for why a
// plain tabId comparison in the timeout/rejection handlers isn't
// enough on its own. Confirmed as a real race by tracing through the
// code, not from a device report: two overlapping goBack() calls to
// the SAME tab share the same tabId, so a stale callback from an
// OLDER request could still match "pendingGoBackForTab === tabId"
// even after a NEWER request has taken over. A unique token per
// dispatch lets those callbacks tell "my own request" apart from "a
// different, newer request to the same tab."
let pendingGoBackToken = 0;

function clearPendingGoBack() {
  pendingGoBackForTab = null;
  if (pendingGoBackTimeoutId !== null) {
    clearTimeout(pendingGoBackTimeoutId);
    pendingGoBackTimeoutId = null;
  }
}

function reportDepth(tabId, depth, transitionType, qualifiers) {
  const params = new URLSearchParams({
    tabId: String(tabId),
    depth: String(depth),
    transitionType: transitionType || '',
    qualifiers: JSON.stringify(qualifiers || []),
  });
  fetch(`${REPORT_URL}?${params.toString()}`, { method: 'GET' })
    .catch((err) => {
      // The local helper server may not be running (e.g. the
      // addon setting that enables it is off, or it failed to
      // start) - fail silently. The addon's Python side has its
      // own click-counting fallback for exactly this case.
      console.debug('[quickbrowser-navtracker] report failed:', err);
    });
}

function handleTopFrameEvent(details) {
  if (details.frameId !== 0) {
    return;
  }

  activeTabId = details.tabId;

  const existing = tabState.get(details.tabId);
  if (existing === undefined) {
    // First event seen for this tab - this is the baseline starting
    // page, not a step forward.
    tabState.set(details.tabId, { depth: 0 });
    reportDepth(details.tabId, 0, details.transitionType, details.transitionQualifiers);
    return;
  }

  const qualifiers = details.transitionQualifiers || [];
  const previousDepth = existing.depth;

  // See the module-level comment above for why this is based on our
  // own pending-request tracking rather than transitionQualifiers.
  if (pendingGoBackForTab === details.tabId) {
    existing.depth = Math.max(0, existing.depth - 1);
    clearPendingGoBack();
  } else {
    existing.depth += 1;
  }

  console.debug(
    '[quickbrowser-navtracker] nav event: transitionType=' + details.transitionType +
    ' qualifiers=' + JSON.stringify(qualifiers) +
    ' depth ' + previousDepth + ' -> ' + existing.depth
  );

  reportDepth(details.tabId, existing.depth, details.transitionType, qualifiers);
}

chrome.webNavigation.onCommitted.addListener(handleTopFrameEvent);
chrome.webNavigation.onHistoryStateUpdated.addListener(handleTopFrameEvent);

chrome.tabs.onRemoved.addListener((tabId) => {
  tabState.delete(tabId);
  if (activeTabId === tabId) {
    activeTabId = null;
  }
  if (pendingGoBackForTab === tabId) {
    clearPendingGoBack();
  }
});

const GOBACK_RESULT_URL = `http://localhost:${HELPER_PORT}/goback_result`;

function reportGoBackResult(ok, error) {
  const params = new URLSearchParams({ ok: ok ? '1' : '0' });
  if (error) {
    params.set('error', String(error));
  }
  fetch(`${GOBACK_RESULT_URL}?${params.toString()}`, { method: 'GET' }).catch((err) => {
    console.debug('[quickbrowser-navtracker] reportGoBackResult failed:', err);
  });
}

function pollForCommand() {
  fetch(POLL_URL, { method: 'GET' })
    .then((response) => response.json())
    .then((data) => {
      if (!(data && data.goBack)) {
        return;
      }

      // Report this straight to Kodi's own log via the addon's local
      // server, rather than only console.debug() here - the outcome
      // of chrome.tabs.goBack() (success, rejection, or simply not
      // knowing which tab to target) has been the actual open
      // question across several rounds of real-device testing, and
      // this Chrome-side console isn't visible from Kodi's log at
      // all without a separate manual check each time.
      if (activeTabId === null) {
        reportGoBackResult(false, 'no_active_tab_known');
        return;
      }

      const targetTabId = activeTabId;
      // Cancel any previous pending correlation/timeout before
      // starting a new one, and mint a fresh token for this specific
      // dispatch. Confirmed as a real race by tracing through the
      // code, not from a device report: rapid repeated Back presses
      // could dispatch a second goBack() call to the same tab before
      // the first one's promise has resolved. Two overlapping calls
      // share the same tabId, so a plain "pendingGoBackForTab ===
      // targetTabId" check in the timeout/rejection callbacks below
      // can't tell "my own request" apart from "a different, newer
      // request to the same tab" - only the token can.
      clearPendingGoBack();
      pendingGoBackForTab = targetTabId;
      const myToken = ++pendingGoBackToken;
      pendingGoBackTimeoutId = setTimeout(() => {
        // Safety net: if goBack() resolved without producing a
        // top-frame navigation event (e.g. genuinely nothing to go
        // back to), this flag would otherwise stay stuck forever,
        // wrongly attributing the NEXT unrelated forward navigation
        // to this request instead. Token check (not just tabId)
        // confirms this timeout still belongs to the current
        // request before clearing it.
        if (pendingGoBackToken === myToken) {
          clearPendingGoBack();
        }
      }, PENDING_GOBACK_TIMEOUT_MS);

      chrome.tabs.goBack(targetTabId).then(
        () => {
          reportGoBackResult(true, null);
        },
        (err) => {
          // The call itself failed outright - no navigation event to
          // wait for. Token check (not just tabId) confirms this
          // rejection still belongs to the current request before
          // clearing pending state or resetting depth - otherwise a
          // late rejection from an OLDER, since-superseded request
          // could incorrectly clear or reset state that now belongs
          // to a newer, still-in-flight request to the same tab.
          if (pendingGoBackToken === myToken) {
            clearPendingGoBack();

            // Confirmed as the actual root cause of Back never
            // reaching 0, from a real device log: Chrome's rejection
            // here (e.g. "Cannot find a next page in history") is
            // itself the authoritative signal that we're at the true
            // start of history - but since a FAILED goBack() produces
            // no navigation event at all, and depth tracking is
            // entirely event-driven, the depth counter was staying
            // stuck at whatever it was before the failure, forever,
            // even though this rejection is exactly the information
            // needed to know we've reached 0. Correct it directly
            // here instead of waiting for an event that will never
            // come.
            const existing = tabState.get(targetTabId);
            if (existing) {
              existing.depth = 0;
              reportDepth(targetTabId, 0, 'goback_failed', []);
            }
          }

          reportGoBackResult(false, err && err.message ? err.message : String(err));
        }
      );
    })
    .catch((err) => {
      // Same reasoning as reportDepth's fetch failure - the local
      // helper server not being reachable is an expected, silent
      // fallback case, not an error worth surfacing.
      console.debug('[quickbrowser-navtracker] poll failed:', err);
    });
}

setInterval(pollForCommand, POLL_INTERVAL_MS);

