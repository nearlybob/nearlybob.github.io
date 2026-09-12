# Quick Browser (plugin.program.quickbrowser)

Lets you pick from a list of configured websites, launches your
choice fullscreen in Chrome (`--kiosk`), and lets you move the real
Windows mouse cursor and click using Kodi's remote directional
buttons.

**Windows only.** This will not work on Android, iOS, or Linux builds
of Kodi - it relies on the Windows `user32.dll` API directly via
`ctypes`.

---

## Setup

### 1. Requirements

- Kodi running on Windows
- Google Chrome installed somewhere on the system
- Normal mouse/keyboard access to the Windows desktop this Kodi is
  running on, in addition to whatever remote you control Kodi with -
  step 5 onward in "One-time Chrome extension setup" below happens on
  the Windows desktop directly, not through Kodi's own
  remote-controlled interface

### 2. Install the addon

1. In Kodi, go to the home screen and select **Settings** (the gear
   icon)
2. Select **Add-ons**
3. Select **Install from zip file**
4. Browse to wherever the addon's `.zip` file was saved (e.g. a USB
   drive, or a Downloads folder) and select it
5. Kodi shows a notification when installation finishes. No restart
   is needed.

### 3. Configure your sites

1. In Kodi, go to **Settings -> Add-ons -> My add-ons**
2. Select **Program add-ons**
3. Select **Quick Browser**
4. Select **Configure** (or the settings/gear icon for this addon,
   depending on your Kodi skin)
5. Select the **Websites** category (tab along the top or side,
   depending on skin)
6. Select **Site 1 - Name**, type a name for the site (e.g.
   `YouTube`), and confirm
7. Select **Site 1 - URL**, type the full address including
   `https://` (e.g. `https://youtube.com`), and confirm
8. Repeat for Site 2 through Site 5 if you want more than one site
   available - leave any slot's Name and URL both as `(unused)` to
   keep that slot out of the launch menu entirely
9. Select the **General** category
10. If Chrome isn't installed at the default location
    (`C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`),
    select **Chrome executable path** and type the correct path. If
    the configured path doesn't exist, a couple of other common
    install locations are tried automatically before giving up, so
    this can often be left as-is.
11. Close the settings screen (Back button, or however your remote
    exits a menu)

At this point the addon already works - selecting it from Program
add-ons shows your site list, launches Chrome fullscreen, and the
remote controls the mouse. The next step is optional but strongly
recommended.

### 4. One-time Chrome extension setup (recommended)

This step makes Back navigation accurate and reliable. Without it,
Back falls back to a plain Alt+Left keystroke, which some sites
(confirmed on PPV.st) can silently block - see "Real navigation
tracking" below for why.

This step involves both Kodi's remote-controlled interface (to
generate the shortcut files) and the Windows desktop directly with a
normal mouse and keyboard (to use those files). If Kodi is running on
a dedicated HTPC/TV setup, this means physically going to that
computer with a mouse and keyboard attached, or remoting into it some
other way (e.g. Remote Desktop) - there's no way to do steps 5
onward through Kodi's own remote-controlled interface.

**Step-by-step:**

1. In Kodi, go to **Settings -> Add-ons -> My add-ons -> Program
   add-ons -> Quick Browser -> Configure**
2. Select the **Setup** category
3. Select **Create desktop shortcuts**
4. A confirmation dialog appears listing what was created. Select
   **OK** to dismiss it.
5. Now switch to the Windows desktop directly, using a physical mouse
   and keyboard (not the Kodi remote) - minimize or exit Kodi if it's
   covering the desktop, or physically switch to that machine if
   you're not already there
6. On the Desktop, find and **double-click** the file named
   **"Quick Browser - Open Chrome Profile.bat"**. A new Chrome window
   opens - this is a separate, isolated profile dedicated to this
   addon, **not** your regular Chrome profile (see "Why an isolated
   Chrome profile" below for why this matters)
7. In that new Chrome window, click into the address bar at the top,
   type `chrome://extensions`, and press **Enter**
8. On the Extensions page, find the **"Developer mode"** toggle in
   the top-right corner and click it to turn it on
9. Click the **"Load unpacked"** button (top-left area of the page)
10. A Windows folder-picker dialog opens. **Do not navigate its
    folder tree by hand** - the steps below avoid that entirely,
    since manually clicking through folders in this specific dialog
    produced a real "folder name is not valid" error during testing.
    Leave this dialog open and move to the next step.
11. Back on the Desktop, find and **double-click** the file named
    **"Quick Browser - Open Extension Folder Path.bat"**. This opens
    a Notepad window containing a single line of text - the exact
    folder path needed.
12. In that Notepad window, press **Ctrl+A** (selects all the text),
    then **Ctrl+C** (copies it)
13. Switch back to the folder-picker dialog from step 10 (it should
    still be open - if using a taskbar, look for it there)
14. Click directly into the **"Folder:"** text field near the bottom
    of that dialog
15. Press **Ctrl+V** to paste the path you copied in step 12
16. Click the **"Select Folder"** button
17. Chrome should now show **"Quick Browser Navigation Tracker"** as
    an installed extension on the Extensions page

**To confirm it worked:** on that same Extensions page, check the
version number shown next to "Quick Browser Navigation Tracker" -
compare it against the version in this addon's own
`resources/chrome_extension/manifest.json` file. If they match, the
setup succeeded.

This only needs doing once. If Chrome or this addon is ever
reinstalled, or the addon's data folder is deleted, it needs redoing
(repeat from step 1 - the shortcuts can just be recreated the same
way).

**Fallback, if the shortcuts don't work for some reason:** Settings
-> Add-ons -> Quick Browser -> Configure -> Setup -> "Show full setup
instructions" shows the same paths as plain text in a dialog, to
type/copy manually instead of using the shortcut files.

**When updating the addon to a new version, the extension may also
need reloading.** Kodi updating the addon files on disk does not
automatically make Chrome notice a change to an extension it already
has loaded - confirmed as a real, repeated point of confusion across
testing, where a fix was shipped and tested but the old extension
code was silently still running. After installing an addon update, go
to `chrome://extensions` and check the version number shown on
"Quick Browser Navigation Tracker" - it's bumped every time
`background.js` changes, specifically so this is checkable rather
than just assumed. If it doesn't match what the current addon version
ships (check `resources/chrome_extension/manifest.json`), click the
refresh/reload icon on the extension's card (or fully close Chrome
first), then check the version again before testing.

If you skip this step, or it's ever not working, the addon still
works exactly the same otherwise - Back just uses the older, less
reliable keystroke method for the whole session.

---

## Settings reference

- **Setup** category:
  - **Create desktop shortcuts** - writes two `.bat` shortcuts to your
    Desktop for the one-time Chrome extension setup above, with exact
    paths for your install already filled in - see step 4 above.
  - **Show full setup instructions** - fallback: displays the same
    paths and command as plain text in a dialog, to type/copy
    manually instead.
- **Websites** category - up to 5 site slots, each with a **Name**
  and **URL**. Slot 1 is enabled by default (`https://example.com`);
  slots 2-5 start as `(unused)`.
- **General** category:
  - **Chrome executable path** - see step 3 above.
  - **Cursor step size** - pixels moved per directional press.
  - **Max speed multiplier** - how far cursor acceleration can ramp
    up when repeating the same direction quickly.
  - **Scroll notches per press** - how much the wheel scrolls when
    the cursor hits the top/bottom of the screen.
  - **Silence Kodi UI navigation sounds** - mutes Kodi's own move/
    select sound effects while the addon is running, restoring
    whatever was set before on exit.
  - **Switch to fullscreen-window mode while running** - temporarily
    switches Kodi from true exclusive fullscreen to windowed/
    borderless mode before Chrome launches, switching back on exit.
    See "Fullscreen-window toggling" below for why this exists and
    how it's implemented safely.
  - **Use real Chrome navigation tracking for Back** - see "Real
    navigation tracking" below. Falls back to click-counting + a
    keystroke automatically if unavailable - never the only way Back
    can work.
  - **Wait after launching Chrome** - delay before input capture
    starts, to give Chrome time to open fullscreen.

---

