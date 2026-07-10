"""Read other windows' geometry on macOS (Quartz window services) so the pet
can perch on and be contained by them — the macOS equivalent of the KWin/D-Bus
feed and of `windows_win32.py`.

*** SPECULATIVE / UNVERIFIED ***********************************************
This module was written WITHOUT access to macOS hardware, from Apple's
documentation alone, to be tested and fixed on a real Mac. Nothing here has
ever executed on macOS. Comments below flag every assumption that needs
verifying; do not trust this file until someone with a Mac has run it.
****************************************************************************

Like Win32 (and unlike KWin scripting), Quartz has no practical
push-on-change API for "some window moved" that we could use from an
unprivileged Python process, so `pet.py` polls `dump()` on a QTimer.

Produces the same wire format the KWin feed uses (`windows.parse_kwin_dump`),
so it plugs into the existing, already-tested perch/contain pipeline
unchanged: `id;class;x,y,w,h;pid|id;class;x,y,w,h;pid|...`, bottom-to-top.

Screen Recording permission gotcha (IMPORTANT for whoever tests this):
    Since macOS 10.15 Catalina, `kCGWindowName` (the per-window TITLE) is
    omitted from CGWindowListCopyWindowInfo results for other apps' windows
    unless the calling app has been granted **Screen Recording** permission
    (System Settings -> Privacy & Security -> Screen Recording; grant it to
    the terminal/Python that launches the pet). WITHOUT the permission the
    call still succeeds — it just silently returns dictionaries with no
    window titles. To degrade gracefully instead of breaking, the `title`
    field of our wire format (which on KDE holds the window CLASS, not the
    title) is filled from `kCGWindowOwnerName` — the owning APP's name, which
    is documented to be available without any permission. That is also
    semantically the closer match for a window class. So geometry/perch/
    occlusion should work without Screen Recording; only if owner names turn
    out to be missing too would the permission matter. VERIFY on hardware.

Coordinate space assumption (VERIFY): `kCGWindowBounds` is a CGRect in
CoreGraphics *global display* coordinates — origin at the top-left of the
main display, y growing DOWNWARD (CGWindow/CGDisplay space is top-left
based, unlike AppKit's bottom-left NSScreen space). Qt on macOS also exposes
QScreen/global positions in a top-left-origin space, so the values should be
directly comparable to the pet's Qt coordinates with no y-flip. This is the
single riskiest assumption in the file — if the pet perches at mirrored
heights, a y-flip (or per-display remap) is what's missing. Multi-monitor
offsets (secondary displays at negative coords) are a second thing to check.

Why exclude-by-PID and not by window id: on Windows we exclude the pet's own
window by HWND (`QWidget.winId()` IS the HWND). On macOS `winId()` returns an
NSView pointer, which is NOT a `kCGWindowNumber` (CGWindowID), so there is no
cheap, reliable id to compare. The pet's process id, however, is trivially
correct and also covers any helper windows (tray popups, menus) the pet
process creates — so the caller passes `exclude_pid=os.getpid()` instead.
"""
import sys

# Guarded import: this module must be importable everywhere. On non-macOS
# (and on macOS without pyobjc-framework-Quartz installed) `Quartz` stays
# None and every entry point no-ops — same defensive shape as
# `windows_win32.user32 is None`. pyobjc is deliberately used instead of raw
# ctypes CoreFoundation marshalling: CF ref-counting mistakes in unverified
# ctypes code would crash, while a wrong pyobjc call just returns odd data.
Quartz = None
if sys.platform == "darwin":
    try:
        import Quartz              # pip install pyobjc-framework-Quartz
    except Exception:
        Quartz = None

# CGWindow info-dictionary keys, as plain strings. The Quartz constants
# (Quartz.kCGWindowNumber etc.) are CFStrings documented to bridge to exactly
# these values, and using literals keeps the row-parsing logic below pure and
# unit-testable on any OS without pyobjc. (VERIFY on hardware that e.g.
# Quartz.kCGWindowNumber == "kCGWindowNumber" — believed true for all of
# these, they are defined as their own symbol names.)
K_NUMBER = "kCGWindowNumber"          # CGWindowID; stable for the window's lifetime
K_LAYER = "kCGWindowLayer"            # window level; 0 == normal app windows
K_BOUNDS = "kCGWindowBounds"          # {"X":, "Y":, "Width":, "Height":} floats
K_OWNER_PID = "kCGWindowOwnerPID"
K_OWNER_NAME = "kCGWindowOwnerName"   # owning APP name; no permission needed
K_NAME = "kCGWindowName"              # window TITLE; needs Screen Recording perm
K_ALPHA = "kCGWindowAlpha"


def available():
    """True when the Quartz backend can actually be used (macOS + pyobjc)."""
    return Quartz is not None


def _clean_class(name):
    """App/class name -> safe lowercase wire-format token. `;` and `|` are the
    wire format's field/record separators, so they must never appear in it."""
    return str(name).replace(";", " ").replace("|", " ").strip().lower()


def _row_from_info(info, exclude_pid=None):
    """One CGWindow info dict -> (wid, cls, x, y, w, h, pid), or None to skip.

    Pure (works on plain dicts), so it's unit-tested off-Mac. Filters:
    - layer != 0: GUESS that layer 0 (kCGNormalWindowLevel) is exactly the
      set of ordinary app windows, excluding the menu bar, Dock, status
      items, popups and other system chrome (those sit on higher levels).
      VERIFY: if the pet perches on invisible chrome or misses real windows,
      this filter is the first suspect.
    - fully transparent windows (alpha == 0): visible-looking rects that
      aren't actually drawn.
    - the pet's own process (`exclude_pid`).
    - degenerate rects. (The shared parser applies the real min-size filter.)
    """
    try:
        if int(info.get(K_LAYER, -1)) != 0:
            return None
        alpha = info.get(K_ALPHA)
        if alpha is not None and float(alpha) <= 0.0:
            return None
        pid = info.get(K_OWNER_PID)
        pid = int(pid) if pid is not None else 0
        if exclude_pid is not None and pid == int(exclude_pid):
            return None
        bounds = info.get(K_BOUNDS)
        if not bounds:
            return None
        x = int(round(float(bounds.get("X", 0))))
        y = int(round(float(bounds.get("Y", 0))))
        w = int(round(float(bounds.get("Width", 0))))
        h = int(round(float(bounds.get("Height", 0))))
        if w <= 0 or h <= 0:
            return None
        wid = info.get(K_NUMBER)
        wid = int(wid) if wid is not None else 0
        # Class field: owner APP name first (permission-free; class-like, cf.
        # module docstring), window title only as a fallback. Both missing ->
        # "" and parse_kwin_dump's EXCLUDE_CLASSES drops the row.
        cls = _clean_class(info.get(K_OWNER_NAME) or info.get(K_NAME) or "")
        return (wid, cls, x, y, w, h, pid)
    except Exception:
        return None      # any odd/half-populated dict: skip it, don't die


def _format_dump(rows):
    """Rows (topmost-first, as _enum_windows yields) -> wire-format string
    (bottom-to-top, as `windows.parse_kwin_dump` expects). Pure."""
    return "|".join(
        "{};{};{},{},{},{};{}".format(wid, cls, x, y, w, h, pid)
        for wid, cls, x, y, w, h, pid in reversed(rows)
    )


def _enum_windows(exclude_pid=None):
    """On-screen normal windows as row tuples, topmost-first.

    CGWindowListCopyWindowInfo with kCGWindowListOptionOnScreenOnly is
    documented to return windows ordered front-to-back (topmost FIRST) —
    same as Win32 EnumWindows, opposite of the wire format. VERIFY the order
    on hardware: if occlusion decisions look inverted (pet hides behind a
    window that is actually below it), this ordering assumption is wrong.
    """
    if Quartz is None:
        return []
    opts = (Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements)
    infos = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
    rows = []
    for info in (infos or []):
        row = _row_from_info(info, exclude_pid)
        if row is not None:
            rows.append(row)
    return rows


def dump(exclude_pid=None):
    """Current windows as a KWin-feed-format string (bottom-to-top stacking).
    "" when the backend is unavailable or anything goes wrong — callers treat
    an empty feed as "feature off", never as an error."""
    if Quartz is None:
        return ""
    try:
        return _format_dump(_enum_windows(exclude_pid))
    except Exception:
        return ""
