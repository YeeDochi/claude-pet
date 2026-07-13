"""Read other windows' geometry on macOS (Quartz window services) so the pet
can perch on and be contained by them — the macOS equivalent of the KWin/D-Bus
feed and of `win32.py`.

*** VERIFIED ON HARDWARE (since v1.0.0) ***********************************
This module runs on real macOS: perch, occlusion, and click-to-focus were
confirmed on a Mac, and the bugs that surfaced there (right-click jitter,
vanishing on the Show Desktop gesture) were fixed in 0.3.6. It began as
documentation-only speculation, hence the assumption notes below — kept
because the maintainer has no Mac, so macOS regressions still tend to appear
post-release, and these notes are the map of where to look (coordinate space,
Screen Recording) if perch/occlusion drift on a newer macOS.
****************************************************************************

(proc_ancestors below uses `ps`, not Quartz, so it works even without pyobjc.)

Like Win32 (and unlike KWin scripting), Quartz has no practical
push-on-change API for "some window moved" that we could use from an
unprivileged Python process, so `pet.py` polls `dump()` on a QTimer.

Produces the same wire format the KWin feed uses (`geom.parse_dump`),
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
    occlusion work without Screen Recording (confirmed in practice); only if
    owner names turn out to be missing too would the permission matter.

Coordinate space (validated on hardware): `kCGWindowBounds` is a CGRect in
CoreGraphics *global display* coordinates — origin at the top-left of the
main display, y growing DOWNWARD (CGWindow/CGDisplay space is top-left
based, unlike AppKit's bottom-left NSScreen space). Qt on macOS also exposes
QScreen/global positions in a top-left-origin space, so the values should be
directly comparable to the pet's Qt coordinates with no y-flip. This is the
single riskiest assumption in the file — if the pet perches at mirrored
heights, a y-flip (or per-display remap) is what's missing. Multi-monitor
offsets (secondary displays at negative coords) are a second thing to check.

Coordinate diagnosis note: perch matches a window's TOP EDGE by coordinate
(6px tolerance) while containment/occlusion match by window ID, so if the pet
can be dropped INTO a window (works) but won't perch ON TOP of it (fails), the
coordinates are off — run the pet with CLAUDLET_DEBUG_GEOM=1 (see pet.py's
_debug_geom_log) to print the rects, screen box and devicePixelRatio.

Why exclude-by-PID and not by window id: on Windows we exclude the pet's own
window by HWND (`QWidget.winId()` IS the HWND). On macOS `winId()` returns an
NSView pointer, which is NOT a `kCGWindowNumber` (CGWindowID), so there is no
cheap, reliable id to compare. The pet's process id, however, is trivially
correct and also covers any helper windows (tray popups, menus) the pet
process creates — so the caller passes `exclude_pid=os.getpid()` instead.
"""
import subprocess
import sys

# Guarded import: this module must be importable everywhere. On non-macOS
# (and on macOS without pyobjc-framework-Quartz installed) `Quartz` stays
# None and every entry point no-ops — same defensive shape as
# `win32.user32 is None`. pyobjc is deliberately used instead of raw
# ctypes CoreFoundation marshalling: CF ref-counting mistakes in unverified
# ctypes code would crash, while a wrong pyobjc call just returns odd data.
Quartz = None
if sys.platform == "darwin":
    try:
        import Quartz              # pip install pyobjc-framework-Quartz
    except Exception:
        Quartz = None

# AppKit (Cocoa) is used only for the two window-behaviour fixes below
# (Dock-icon suppression + stop-hiding-on-deactivate). It ships with
# pyobjc-framework-Cocoa, which pyobjc-framework-Quartz already depends on, so
# it's available wherever Quartz is. Guarded exactly like Quartz: absent -> the
# fixes no-op and the pet just behaves as before (Dock icon shown, hides on
# click-away). Kept SEPARATE from Quartz so a partial pyobjc install can still
# use whichever half imported.
AppKit = None
objc = None
if sys.platform == "darwin":
    try:
        import AppKit             # pip install pyobjc-framework-Cocoa (via Quartz)
        import objc
    except Exception:
        AppKit = None
        objc = None

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


def set_accessory_policy():
    """Make the pet an 'accessory' (agent) app so it shows NO Dock icon and NO
    Cmd-Tab app-switcher entry — the macOS equivalent of Qt.Tool's skip-taskbar
    on Windows/Linux.

    Why this is needed at all: on macOS the Dock icon is governed by the app's
    *activation policy* (the Info.plist LSUIElement key, or this runtime call),
    NOT by any window flag. So Qt.WindowType.Tool — which DOES remove the
    taskbar button on Windows and the task entry on Linux — leaves the default
    NSApplicationActivationPolicyRegular in place on macOS, and the launching
    Python shows its rocket/interpreter icon in the Dock. Switching to
    ...PolicyAccessory removes it.

    Best-effort: returns True if applied, False if AppKit is missing or the call
    raised (same degrade-don't-crash contract as the rest of this module). Call
    once, after QApplication (hence NSApplication.sharedApplication) exists and
    BEFORE the first window is shown, so no icon ever flashes in the Dock.
    """
    if AppKit is None:
        return False
    try:
        app = AppKit.NSApplication.sharedApplication()
        # NSApplicationActivationPolicyAccessory == 1; use the named constant
        # when present, fall back to the documented literal.
        policy = getattr(AppKit, "NSApplicationActivationPolicyAccessory", 1)
        app.setActivationPolicy_(policy)
        return True
    except Exception:
        return False


def keep_visible_on_deactivate(win_id):
    """Stop a Qt.Tool window from vanishing when the user clicks another app.

    Qt.WindowType.Tool maps to an NSPanel utility window on macOS, and such a
    panel's `hidesOnDeactivate` defaults to YES — so the moment our app is
    deactivated (the user clicks any other window) AppKit auto-hides the panel
    and the creature blinks out of existence. Linux/Windows have no
    "hide on app deactivate" concept, so the bug is macOS-only. Turning
    hidesOnDeactivate off keeps the pet on screen across the whole desktop
    regardless of which app is frontmost.

    `win_id` is QWidget.winId() — on macOS an NSView* address. The native window
    must already exist, so call this from the widget's showEvent (or any time
    after show()). Best-effort; no-op / False without pyobjc or on any error.
    """
    if AppKit is None or objc is None:
        return False
    try:
        view = objc.objc_object(c_void_p=int(win_id))   # NSView*
        nswindow = view.window()
        if nswindow is None:
            return False
        nswindow.setHidesOnDeactivate_(False)
        return True
    except Exception:
        return False


def keep_stationary_on_desktop(win_id):
    """Stop the pet vanishing with the 'Show Desktop' / Mission Control gesture.

    The macOS Show-Desktop trackpad gesture (spread thumb + three fingers) and
    Exposé slide every ordinary app window off-screen. A roaming desktop creature
    should stay put like a desktop widget instead. AppKit governs this with the
    NSWindow's `collectionBehavior`: adding NSWindowCollectionBehaviorStationary
    marks the window 'unaffected by Exposé' so it stays visible and in place
    through Show Desktop, Exposé and Mission Control. Linux/Windows have no
    equivalent 'sweep the desktop' concept, so the bug is macOS-only.

    We OR the flag onto the window's existing behaviour rather than replacing it,
    so whatever Qt already set (its NSPanel defaults) is preserved.

    `win_id` is QWidget.winId() — on macOS an NSView* address; the native window
    must already exist, so call this after show() (e.g. from showEvent), same as
    keep_visible_on_deactivate. Best-effort; no-op / False without pyobjc or on
    any error."""
    if AppKit is None or objc is None:
        return False
    try:
        view = objc.objc_object(c_void_p=int(win_id))   # NSView*
        nswindow = view.window()
        if nswindow is None:
            return False
        # NSWindowCollectionBehaviorStationary == 1 << 4; use the named constant
        # when present, else the documented literal.
        stationary = getattr(AppKit, "NSWindowCollectionBehaviorStationary", 1 << 4)
        nswindow.setCollectionBehavior_(nswindow.collectionBehavior() | stationary)
        return True
    except Exception:
        return False


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
        # "" and parse_dump's EXCLUDE_CLASSES drops the row.
        cls = _clean_class(info.get(K_OWNER_NAME) or info.get(K_NAME) or "")
        return (wid, cls, x, y, w, h, pid)
    except Exception:
        return None      # any odd/half-populated dict: skip it, don't die


def _format_dump(rows):
    """Rows (topmost-first, as _enum_windows yields) -> wire-format string
    (bottom-to-top, as `geom.parse_dump` expects). Pure."""
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


# Last calibration applied by dump(): (scale, off_x, off_y). Exposed only so the
# pet's opt-in debug logger can report it; scale 1.0 == "no scaling / uncalibrated".
LAST_CAL = (1.0, 0.0, 0.0)


def _own_bounds(infos, pid, ref=None):
    """Raw CG bounds (x, y, w, h) of the pet's OWN body window owned by `pid`, on
    ANY layer — used to self-calibrate the CG->Qt coordinate scale from a window
    whose Qt logical rect we already know. The pet window is an always-on-top
    Tool window, so it is NOT on layer 0 and _row_from_info (which filters to
    layer 0) would drop it; hence this separate, filter-free scan. None if the
    pet window isn't in the list yet.

    Picking the RIGHT own-window matters: the pet process also owns transient
    windows — most importantly the right-click QMenu, which lives on a higher
    layer and can be LARGER than the tiny body. The old "largest owned window"
    rule then made the menu the calibration ruler, producing a bogus scale/offset
    that remapped every other window and flung the pet across the screen while the
    menu was open (jitter + fly-to-the-left). So when the Qt `ref` size is known,
    prefer the candidate whose CG dimensions scale UNIFORMLY from the ref (the
    body scales by the same DPR in x and y; a menu has a different aspect ratio),
    breaking ties toward the largest. Without a ref, fall back to largest-area."""
    cands = []
    for info in (infos or []):
        try:
            if int(info.get(K_OWNER_PID, -1)) != int(pid):
                continue
            b = info.get(K_BOUNDS)
            if not b:
                continue
            w = float(b.get("Width", 0))
            h = float(b.get("Height", 0))
            if w <= 0 or h <= 0:
                continue
            cands.append((float(b.get("X", 0)), float(b.get("Y", 0)), w, h))
        except Exception:
            continue
    if not cands:
        return None
    qw = float(ref[0]) if ref else 0.0
    qh = float(ref[1]) if ref else 0.0
    if qw <= 0 or qh <= 0:
        return max(cands, key=lambda b: b[2] * b[3])   # no ref: old largest-wins
    # aspect-distortion first (0 == perfectly uniform scale, i.e. the body),
    # then largest area as a tiebreak. Menus, with a mismatched aspect, sort last.
    return min(cands, key=lambda b: (abs(b[2] / qw - b[3] / qh), -b[2] * b[3]))


def _calibration(own, ref):
    """(scale, off_x, off_y) mapping raw CG coords -> Qt logical coords, derived
    from the pet's own window: `own`=(x,y,w,h) as CG reports it, `ref`=(qw,qh,
    qx,qy) as Qt knows it. If CG already reports Qt points, scale≈1 and this is a
    no-op; if it reports backing-store PIXELS on a Retina display, scale≈dpr and
    every window shrinks into Qt's space (the macOS analogue of the Win32
    _to_logical /scale fix). Returns (1,0,0) — no scaling — when the pet window
    wasn't found or the numbers are implausible, so perch can't get worse than
    the current unscaled behaviour."""
    if not own or not ref:
        return (1.0, 0.0, 0.0)
    bx, by, bw, bh = own
    qw, qh, qx, qy = ref
    if bw <= 0 or bh <= 0 or qw <= 0 or qh <= 0:
        return (1.0, 0.0, 0.0)
    scale = ((bw / qw) + (bh / qh)) / 2.0
    if not (0.4 < scale < 4.0):          # implausible -> refuse to scale
        return (1.0, 0.0, 0.0)
    return (scale, bx / scale - qx, by / scale - qy)


def _scaled(row, scale, off_x, off_y):
    """Apply the CG->Qt (scale, offset) to one raw row tuple."""
    if scale == 1.0 and off_x == 0.0 and off_y == 0.0:
        return row
    wid, cls, x, y, w, h, pid = row
    return (wid, cls,
            int(round(x / scale - off_x)), int(round(y / scale - off_y)),
            int(round(w / scale)), int(round(h / scale)), pid)


def dump(exclude_pid=None, ref=None):
    """Current windows as a KWin-feed-format string (bottom-to-top stacking).
    "" when the backend is unavailable or anything goes wrong — callers treat
    an empty feed as "feature off", never as an error.

    `ref`=(qt_w, qt_h, qt_x, qt_y): the pet's OWN window as Qt knows it. When
    given, the window owned by `exclude_pid` is measured in the same CG snapshot
    and used to self-calibrate the CG->Qt coordinate scale (see _calibration),
    which is then applied to every other window. `ref=None` -> raw CG coords
    (old behaviour). One CGWindowListCopyWindowInfo call serves both."""
    global LAST_CAL
    if Quartz is None:
        return ""
    try:
        opts = (Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements)
        infos = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
        rows = []
        for info in (infos or []):
            row = _row_from_info(info, exclude_pid)
            if row is not None:
                rows.append(row)
        cal = _calibration(_own_bounds(infos, exclude_pid, ref), ref) \
            if (ref and exclude_pid is not None) else (1.0, 0.0, 0.0)
        LAST_CAL = cal
        rows = [_scaled(r, *cal) for r in rows]
        return _format_dump(rows)
    except Exception:
        return ""


def _proc_parents():
    """{pid: ppid} for every process, from one `ps` snapshot — the macOS
    equivalent of the Win32 Toolhelp snapshot / reading all of /proc."""
    out = {}
    try:
        res = subprocess.run(["ps", "-Ao", "pid=,ppid="],
                             capture_output=True, text=True, timeout=3)
    except Exception:
        return out
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                out[int(parts[0])] = int(parts[1])
            except ValueError:
                continue
    return out


def proc_ancestors(pid, max_hops=40):
    """Set of pids from `pid` up to the top, via one `ps` snapshot — the macOS
    counterpart of walking /proc/<pid>/stat's ppid chain (Linux) or a Toolhelp
    snapshot (Windows). The terminal/IDE window's owning pid is one of these, so
    matching it to a window's owner pid finds this session's host window. Uses
    `ps` (not the Quartz backend, so it works without pyobjc and needs no
    permission) and is called once at startup, sidestepping the fragile
    kinfo_proc struct ABI a sysctl walk would depend on."""
    acc = set()
    try:
        cur = int(pid)
    except (TypeError, ValueError):
        return acc
    parent = _proc_parents()
    if not parent:
        return acc
    while cur > 1 and cur not in acc and len(acc) < max_hops:
        acc.add(cur)
        nxt = parent.get(cur)
        if not nxt:
            break
        cur = nxt
    return acc
