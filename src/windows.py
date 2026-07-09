"""Read other windows' geometry (KDE/X11 via wmctrl) so the pet can perch on
and be contained by them.

Best-effort and GATED: if wmctrl is unavailable (non-KDE, not installed), the
listing is empty and the pet just uses the screen floor as before. Coordinates
are X screen pixels, matching Qt's move() under XWayland — no remapping needed.
"""
import shutil
import subprocess
from collections import namedtuple

Win = namedtuple("Win", "wid x y w h title")


def parse_wmctrl_lg(text):
    """Parse `wmctrl -lG` output into Win rects. Malformed rows are skipped."""
    wins = []
    for line in text.splitlines():
        parts = line.split(None, 7)          # wid desk x y w h host title...
        if len(parts) < 7:
            continue
        wid, _desk, x, y, w, h = parts[:6]
        title = parts[7] if len(parts) >= 8 else ""
        try:
            wins.append(Win(wid, int(x), int(y), int(w), int(h), title))
        except ValueError:
            continue
    return wins


def list_windows(exclude_prefix="claude-pet-", min_size=40):
    """Current windows (best-effort). Returns [] if wmctrl is unavailable — this
    is the gating point that disables perching off KDE/X11."""
    if not shutil.which("wmctrl"):
        return []
    try:
        out = subprocess.check_output(["wmctrl", "-lGS"], text=True, timeout=2)
    except Exception:
        return []
    result = []
    for win in parse_wmctrl_lg(out):
        if exclude_prefix and win.title.startswith(exclude_prefix):
            continue
        if win.w < min_size or win.h < min_size:      # skip panels/docks/junk
            continue
        result.append(win)
    return result


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
    (and is on-screen above the floor); else screen_bottom. This is the surface
    a falling pet lands on."""
    best = screen_bottom
    for win in wins:
        if win.x <= cx <= win.x + win.w and 0 <= win.y < best:
            best = win.y
    return best
