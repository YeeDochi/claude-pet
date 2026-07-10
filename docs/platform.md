# Platform support

[← README](../README.md) · **English** | [한국어](platform.ko.md)

The reactive core (states, animation, roaming, drag-and-throw, tray) is portable.
Window integration (perch/occlusion, click-to-focus) also works on Windows via
polled Win32 APIs, not just KDE; a macOS equivalent (polled Quartz) exists but
is **untested speculation** — see below. Taskbar-hide is still KDE-only.
Everything else just switches off where it isn't implemented — the pet still runs.

| Platform | Runs | Window integration |
|----------|------|--------------------|
| **KDE Plasma** (Wayland/X11) | ✅ | ✅ full — perch, occlusion clip/hide, click-to-focus, taskbar-hide |
| Other Linux (GNOME, …) | ✅ (XWayland) | ✖ KDE-only bits no-op (roam/drag/states/tray work) |
| **Windows** | ✅ | ✅ perch, occlusion clip/hide, click-to-focus (`SetForegroundWindow`, polled `ctypes`/Win32); ✖ taskbar-hide not implemented |
| **macOS** | 🅱️ should launch (native Qt) | 🧪 perch/occlusion implemented (polled Quartz via `pyobjc`) but **UNVERIFIED — written without Mac hardware, needs testing**; ⚠️ best-effort click-to-focus via `osascript` |

All CLI tools (`bin/*`) are Python — no bash — so they run wherever Python does.
KDE and Windows are actively tested; GNOME is out of scope for window integration.
The macOS window-integration code was **written blind, without any Mac to run it
on** — treat it as a starting point for testing, not a working feature. Where
window integration isn't implemented (or pyobjc is missing on macOS), the pet
falls back to the desktop floor with those features disabled.

## Requirements

- Python 3 + PyQt6 — `pip install PyQt6`
- **KDE Plasma** for the full experience: `qdbus6` (window integration / click-to-focus),
  `wmctrl` (optional, hides the pet from the taskbar). XWayland if on Wayland.
- **Windows**: nothing extra — window integration uses only the stdlib `ctypes`
  bindings to `user32`/`dwmapi`/`kernel32` in `src/windows_win32.py`.
- **macOS only**: `pip install pyobjc-framework-Quartz` for perch/occlusion
  (`src/macos_geom.py`). Optional — without it the pet still runs, with window
  integration off. Never needed (or imported) on Windows/Linux.

## Help test on your OS

The entire macOS window-integration path (`src/macos_geom.py` and its wiring in
`pet.py`) is **speculative code written without access to macOS hardware** — it
has never once executed on a Mac. It was written from Apple's documentation to
be handed to someone who can actually test it. Reports very welcome. If you run
it, please check in roughly this order and open an issue:

1. **macOS first step — Screen Recording permission.** Go to System Settings →
   Privacy & Security → Screen Recording and grant it to the terminal (or
   Python) that launches the pet. Without it, macOS hides window *titles* from
   the enumeration API. The code falls back to app names (which need no
   permission), so perch/occlusion *should* still work unpermissioned — please
   test both with and without the permission and report the difference.
2. **Launches?** `bin/claude-pet` shows the creature; it roams, and drag-and-throw works.
   (`pip install pyobjc-framework-Quartz` first for the window-integration bits.)
3. **Perches?** Drag the pet on top of another window — its feet should land on
   the window's top edge, and it should ride along when you move that window.
   If it perches at a mirrored/offset height, the coordinate-space assumption
   in `src/macos_geom.py` is wrong (documented there). Check a second monitor too.
4. **Occlusion?** Raise another window over the one the pet is perched on — the
   pet should clip/hide. If this behaves *inverted*, the z-order assumption in
   `src/macos_geom.py` is wrong.
5. **Reacts?** After `claude-pet-install`, using Claude Code changes its state
   (working / thinking / celebrate).
6. **Tray** icon appears and its menu works.
7. **Click-to-focus:** left-click brings your terminal/IDE (Terminal / iTerm /
   VS Code) to the front (`osascript`); frontmost-app detection gates the
   "celebrate" pose.
- Note what's broken vs. the table above (taskbar-hide is KDE-only by design;
  per-session host-window tracking — hide-when-host-minimized — is not
  implemented on macOS).
