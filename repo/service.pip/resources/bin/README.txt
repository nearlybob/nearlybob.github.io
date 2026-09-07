7zr.exe is included in this folder as of v1.22.0.

WHAT IT IS
-----------
The 32-bit (x86) console build of 7zr.exe, part of 7-Zip's official LZMA
SDK, obtained directly from https://www.7-zip.org/sdk.html (the bin/
folder specifically, not bin/x64 or bin/arm64 - the 32-bit build runs on
both 32-bit and 64-bit Windows, so it's the more broadly compatible
choice regardless of which mpv build you're using).

LICENSE
--------
Public domain. 7-zip.org's own license page states: "LZMA SDK is placed
in the public domain. Anyone is free to copy, modify, publish, use,
compile, sell, or distribute the original LZMA SDK code, either in
source code form or as a compiled binary, for any purpose, commercial or
non-commercial, and by any means." No attribution or license text is
required, though the source remains freely available at 7-zip.org for
anyone who wants to verify or rebuild it themselves.

VERIFICATION
-------------
Confirmed as a genuine PE32 console executable for Windows (Intel
80386/x86), consistent with the expected file type, architecture, and
size for 7zr.exe. There's no published per-file hash on 7-zip.org to
check this specific file against, so that verification wasn't possible -
but the file's characteristics all match what's expected of a real
extraction from the official SDK archive.

WHAT THIS ENABLES
-------------------
With this file present, "Install/update mpv" and the auto-install prompt
(shown if mpv.exe isn't found when starting a PiP) work fully
automatically: download the latest mpv build, extract it with this tool,
done. No system-wide 7-Zip install needed.

If this file is ever missing from a future copy of the addon, everything
still works via a fallback to an already-installed system 7-Zip if
present - see mpv_installer.py in resources/lib/ for that logic.
