# claude-pet — system tray + hide from taskbar

_2026-07-09_

## Goal

The roaming creature currently shows an entry in the desktop taskbar. Move
claude-pet's presence to the **system tray** (network/wifi area) instead: keep
the creature roaming as-is, drop the taskbar entry, and add a tray icon that
reflects the creature's current state and hosts the existing controls.

## Scope

Single file: `src/pet.py` (plus a tiny offscreen test for the icon renderer).
The creature renderer (`creature.py`) is reused unchanged.

## Behavior

- **Creature:** unchanged — keeps roaming, dragging, click-to-focus, physics.
- **Taskbar:** the pet window no longer appears in the taskbar/pager. On
  XWayland (xcb) the `Qt.Tool` flag is kept and, if the entry still shows on
  KDE, the X11 `_NET_WM_STATE_SKIP_TASKBAR` / `_NET_WM_STATE_SKIP_PAGER` hints
  are set. Verified on the user's actual screen.
- **Tray icon (`QSystemTrayIcon`):** always present while the pet runs. Its
  image is the creature drawn small via `creature.draw_creature` into an
  offscreen `QPixmap` → `QIcon`, showing the creature's **current state's
  representative frame** (a single still, not animated).
  - Updates **only when the displayed state changes** (not every frame), driven
    from the existing 20fps `_tick`.
  - Tooltip: short state label (e.g. "claude-pet — 작업 중").
- **Tray interaction:**
  - **Right-click / context menu** → the existing menu (이리와 / 조용히 / 종료).
  - **Left-click (Trigger)** → bring the Claude terminal forward (same as
    left-clicking the creature: `_activate_claude`).

## Design notes

- Add a helper `_state_icon(state) -> QIcon` that renders one representative
  frame of `state` into a transparent `QPixmap` at tray size (e.g. 22–32 px),
  reusing `draw_creature`. Pure w.r.t. window state; unit-testable offscreen
  (asserts it returns a non-null, non-empty icon for every state in
  `creature.STATES`).
- Track `self._tray_state` so `_tick` calls `setIcon` only on change.
- Keep `QApplication.setQuitOnLastWindowClosed(True)` behavior sane: quitting is
  via the tray/creature menu "종료" as today; the tray icon does not by itself
  keep or close the app beyond current behavior.

## Out of scope

- Show/hide (toggle) of the creature from the tray — explicitly not wanted.
- Animated tray icon (frame-by-frame) — a single still per state is enough.

## Verification

Offscreen unit test for `_state_icon`. Then launch on the user's KDE screen and
confirm: (1) no taskbar entry, (2) tray icon appears and changes with state,
(3) right-click menu works, (4) left-click raises the terminal.
