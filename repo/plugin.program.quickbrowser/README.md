# Quick Browser (plugin.program.quickbrowser)

Lets you pick from a list of configured websites, launches your
choice fullscreen in Chrome (`--kiosk`), and lets you move the real
Windows mouse cursor and click using Kodi's remote directional
buttons.

**Windows only.** This will not work on Android, iOS, or Linux builds
of Kodi - it relies on the Windows `user32.dll` API directly via
`ctypes`.

## How it works

1. `default.py` reads your configured sites and shows a native Kodi
   selection menu (`xbmcgui.Dialog().select()`) listing each one by
   name.
2. Once you pick one, it launches Chrome in kiosk mode pointed at
   that site's URL.
3. It then opens an invisible `xbmcgui.WindowDialog` and blocks
   (`doModal()`).
4. Kodi keeps delivering remote button presses (Left/Right/Up/Down/
   Select/Back/Stop/Info/top-right button) to this window's
   `onAction()` even while Chrome has OS focus and is drawn on top -
   this is because official Kodi remote apps send
   input via JSON-RPC/EventServer directly into Kodi's own process,
   independent of window focus.
5. Each directional press nudges the real OS cursor by a configurable
   step, accelerating if the same direction repeats quickly. Select
   performs a left click at the cursor's current position. Reaching
   the top/bottom of the screen while still moving in that direction
   scrolls instead. Back sends the browser's own back shortcut
   (Alt+Left) while there's somewhere to go back to; once already at
   the starting page, Back arms an exit rather than closing
   immediately, and the press after that exits - a safety buffer
   against an accidental close. Stop, Info, and the top-right
   gesture-area button on the official remote all exit immediately
   from anywhere.

## Settings

- **Websites** category - up to 5 site slots, each with a **Name**
  and **URL**. Slot 1 is enabled by default (`https://example.com`);
  slots 2-5 start as `(unused)` - fill in a real name and URL to
  enable a slot, or leave it as `(unused)` to keep it out of the
  launch menu.
- **Chrome executable path** - default assumes an `(x86)` install at
  `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`;
  change if yours is installed elsewhere. If the configured path
  doesn't exist, common alternate locations are tried automatically
  before giving up.
- **Cursor step size** - pixels moved per directional press
- **Max speed multiplier** - how far cursor acceleration can ramp up
  when repeating the same direction quickly
- **Scroll notches per press** - how much the wheel scrolls when the
  cursor hits the top/bottom of the screen
- **Silence Kodi UI navigation sounds** - mutes Kodi's own move/select
  sound effects while the addon is running, restoring whatever was
  set before on exit
- **Wait after launching Chrome** - delay before input capture starts,
  to give Chrome time to open fullscreen
