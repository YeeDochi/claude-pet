"""Read other windows' geometry (KDE, via a KWin script pushing over D-Bus) so
the pet can perch on and be contained by them.

Best-effort and GATED: if the KWin/D-Bus feed never arrives (non-KDE, no
session bus), the listing stays empty and the pet just uses the screen floor
as before. Coordinates are X screen pixels, matching Qt's move() under
XWayland — no remapping needed.
"""
from collections import namedtuple

Win = namedtuple("Win", "wid x y w h title")

# KWin classes that are shell chrome / helpers, never perch targets
EXCLUDE_CLASSES = {"plasmashell", "xwaylandvideobridge", "claude-pet", ""}


def parse_kwin_dump(text, min_size=40):
    """Parse the geometry feed pushed by our KWin script.

    Format: `id;class;x,y,w,h|id;class;x,y,w,h|...`  (coords may be floats).
    Filters shell chrome and sub-min_size junk. Pure."""
    wins = []
    for tok in text.split("|"):
        tok = tok.strip()
        if not tok:
            continue
        parts = tok.split(";", 2)
        if len(parts) != 3:
            continue
        wid, cls, geo = parts
        cls = cls.strip().lower()
        if cls in EXCLUDE_CLASSES:
            continue
        nums = geo.split(",")
        if len(nums) != 4:
            continue
        try:
            x, y, w, h = (int(float(n)) for n in nums)
        except ValueError:
            continue
        if w < min_size or h < min_size:
            continue
        wins.append(Win(wid, x, y, w, h, cls))
    return wins


def window_at(px, py, wins):
    """Topmost window whose rect contains (px, py), or None. wmctrl lists
    bottom-to-top, so the LAST containing window is the topmost."""
    hit = None
    for win in wins:
        if win.x <= px <= win.x + win.w and win.y <= py <= win.y + win.h:
            hit = win
    return hit


def top_surface_under(cx, wins, screen_bottom):
    """Y of the highest window top-edge whose horizontal span covers column cx
    (and is on-screen above the floor); else screen_bottom."""
    best = screen_bottom
    for win in wins:
        if win.x <= cx <= win.x + win.w and 0 <= win.y < best:
            best = win.y
    return best


def support_surface_under(cx, wins, screen_bottom, feet_y, tol=6):
    """The surface a creature at column cx with its feet at feet_y is resting on.

    Only window tops that are AT or BELOW the feet (within tol) count — the
    creature can rest on / fall onto them, but never auto-climbs onto a window
    whose top is above its feet. Among the eligible surfaces the highest
    (smallest y) wins; the screen floor is the fallback.

    This is the key difference from top_surface_under: standing on the desktop
    floor, windows above the feet are ignored (no teleport-up), yet a creature
    dropped/thrown above a window still lands on it."""
    best = screen_bottom
    for win in wins:
        if win.x <= cx <= win.x + win.w and (feet_y - tol) <= win.y < best:
            best = win.y
    return best
