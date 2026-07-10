# Platform support

[← README](../README.md) · **English** | [한국어](platform.ko.md)

The reactive core (states, animation, roaming, drag-and-throw, tray) is portable.
Window integration (perch/occlusion, click-to-focus) also works on Windows via
polled Win32 APIs, not just KDE; taskbar-hide is still KDE-only. Everything
else just switches off where it isn't implemented — the pet still runs.

| Platform | Runs | Window integration |
|----------|------|--------------------|
| **KDE Plasma** (Wayland/X11) | ✅ | ✅ full — perch, occlusion clip/hide, click-to-focus, taskbar-hide |
| Other Linux (GNOME, …) | ✅ (XWayland) | ✖ KDE-only bits no-op (roam/drag/states/tray work) |
| **Windows** | ✅ | ✅ perch, occlusion clip/hide, click-to-focus (`SetForegroundWindow`, polled `ctypes`/Win32); ✖ taskbar-hide not implemented |
| **macOS** | 🅱️ should launch (native Qt) | ⚠️ best-effort click-to-focus via `osascript`; perch/occlusion not implemented |

All CLI tools (`bin/*`) are Python — no bash — so they run wherever Python does.
KDE and Windows are actively tested; GNOME is out of scope for window integration
and macOS is best-effort/unverified on real hardware. Where window integration
isn't implemented, the pet falls back to the desktop floor with those features
disabled.

## Requirements

- Python 3 + PyQt6 — `pip install PyQt6`
- **KDE Plasma** for the full experience: `qdbus6` (window integration / click-to-focus),
  `wmctrl` (optional, hides the pet from the taskbar). XWayland if on Wayland.
- **Windows**: nothing extra — window integration uses only the stdlib `ctypes`
  bindings to `user32`/`dwmapi`/`kernel32` in `src/windows_win32.py`.

## Help test on your OS

macOS is best-effort and **unverified on real hardware** — reports welcome. If
you run it, please check and open an issue:

- **Launches?** `bin/claude-pet` shows the creature; it roams, and drag-and-throw works.
- **Reacts?** After `claude-pet-install`, using Claude Code changes its state
  (working / thinking / celebrate).
- **Tray** icon appears and its menu works.
- **macOS only:** left-click brings your terminal/IDE (Terminal / iTerm / VS Code) to
  the front (`osascript`); frontmost-app detection gates the "celebrate" pose.
- Note what's broken vs. the table above (taskbar-hide is KDE-only by design).
