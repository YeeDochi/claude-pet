#!/usr/bin/env python3
"""claudlet macOS coordinate diagnostic (standalone, read-only).

Run this ON THE MAC and paste the whole output back. It shows how the window
feed's coordinates line up with Qt's logical coordinate space, which is what we
need to fix the perch-on-top alignment: perch matches a window's TOP EDGE by
coordinate, so when drop-INTO-a-window works but perch-ON-TOP doesn't, the feed
coordinates are off (Retina point-vs-pixel, or a y-offset). Nothing here changes
any state; the pet does NOT need to be running.

    python3 bin/claudlet-macos-diag

Prints:
  1. every on-screen window Quartz reports (raw, unfiltered) — number, owner,
     pid, layer, alpha, RAW bounds;
  2. the FILTERED feed the pet actually uses (macos.dump -> parse);
  3. each Qt screen's geometry + devicePixelRatio;
  4. a verdict hint: does a full-screen-ish window's width match the screen in
     points, or is it ~dpr x bigger (-> the Windows-style /devicePixelRatio fix)?
"""
import os
import sys



def _quartz_windows():
    """Raw CGWindowListCopyWindowInfo result, or None if Quartz is missing."""
    try:
        import Quartz
    except Exception as e:
        print("!! Quartz (pyobjc-framework-Quartz) not importable: %s" % e)
        print("   install:  %s -m pip install pyobjc-framework-Quartz"
              % os.path.basename(sys.executable))
        return None
    opts = (Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements)
    return Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)


def _bounds(info):
    b = info.get("kCGWindowBounds", {}) or {}
    return (float(b.get("X", -1)), float(b.get("Y", -1)),
            float(b.get("Width", -1)), float(b.get("Height", -1)))


def main():
    print("== claudlet macOS geom diagnostic ==")
    print("python %s | platform %s" % (sys.version.split()[0], sys.platform))
    if sys.platform != "darwin":
        print("NOTE: not macOS — the Quartz section will be empty. Run on the Mac.")

    infos = _quartz_windows()

    # 1. raw, unfiltered Quartz window list ------------------------------
    print("\n--- 1. RAW Quartz on-screen windows (all layers) ---")
    if infos:
        for info in infos:
            x, y, w, h = _bounds(info)
            print("  #%-7s L%-4s a=%-4s pid=%-7s %-24s X=%.1f Y=%.1f W=%.1f H=%.1f"
                  % (info.get("kCGWindowNumber"), info.get("kCGWindowLayer"),
                     info.get("kCGWindowAlpha"), info.get("kCGWindowOwnerPID"),
                     str(info.get("kCGWindowOwnerName"))[:24], x, y, w, h))
    else:
        print("  (none / Quartz unavailable)")

    # 2. the filtered feed the pet actually consumes ---------------------
    print("\n--- 2. FILTERED feed (macos.dump -> geom.parse_dump) ---")
    try:
        from claudlet.platform.geom import macos
        from claudlet.platform import geom
        print("  macos.available():", macos.available())
        dump = macos.dump(exclude_pid=os.getpid())
        print("  raw dump string:", repr(dump))
        for wn in geom.parse_dump(dump):
            print("  win %-9s cls=%-22s %d,%d  %dx%d  top=%d pid=%s"
                  % (wn.wid, wn.title, wn.x, wn.y, wn.w, wn.h, wn.y, wn.pid))
    except Exception as e:
        print("  feed error:", repr(e))

    # 3. Qt screens (the coordinate space the pet positions itself in) ---
    print("\n--- 3. Qt screens (logical coords + devicePixelRatio) ---")
    dpr = None
    scr_w = None
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication(sys.argv[:1])                 # no window is shown
        for s in QApplication.screens():
            g, a = s.geometry(), s.availableGeometry()
            print("  '%s' geom=%d,%d %dx%d  avail=%d,%d %dx%d  dpr=%.2f  ldpi=%.0f"
                  % (s.name(), g.x(), g.y(), g.width(), g.height(),
                     a.x(), a.y(), a.width(), a.height(),
                     s.devicePixelRatio(), s.logicalDotsPerInch()))
        prim = QApplication.primaryScreen()
        dpr = prim.devicePixelRatio()
        scr_w = prim.geometry().width()
    except Exception as e:
        print("  Qt error:", repr(e))

    # 4. verdict hint ----------------------------------------------------
    print("\n--- 4. hint ---")
    widest = max((_bounds(i)[2] for i in infos), default=0.0) if infos else 0.0
    if dpr and scr_w and widest:
        ratio = widest / scr_w
        print("  primary screen width=%d pts, dpr=%.2f | widest Quartz window W=%.0f | "
              "ratio=%.2f" % (scr_w, dpr, widest, ratio))
        if dpr > 1.05 and abs(ratio - dpr) < 0.25:
            print("  => Quartz appears to report PIXELS while Qt uses POINTS:")
            print("     fix = Windows-style / devicePixelRatio in geom/macos.py (like _to_logical).")
        elif 0.75 <= ratio <= 1.25:
            print("  => Quartz widths already ~match Qt points (no /dpr needed).")
            print("     If perch still fails it's a y-offset (menu bar?) or the 6px tolerance.")
        else:
            print("  => inconclusive — just paste this whole output.")
    else:
        print("  (need both a Quartz window and a Qt screen to compare — paste output.)")


if __name__ == "__main__":
    main()
