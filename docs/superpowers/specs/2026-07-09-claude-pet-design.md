# claude-pet — design

_2026-07-09_

## Goal

A desktop mascot for KDE Plasma (Wayland) that (1) lives on the top layer and
roams the screen, and (2) reflects **Claude Code**'s state in real time —
crucially alerting the user when Claude is waiting for input.

## Key decisions

- **Roaming requires XWayland.** Native Wayland forbids a client from
  positioning its own window, which a roaming pet needs. The pet forces
  `QT_QPA_PLATFORM=xcb` so it runs under XWayland and can `move()` itself.
  A Plasma widget (plasmoid) was rejected: it can't roam (anchored).
- **Art is code, not assets.** The creature is drawn every frame with
  `QPainter` (`src/creature.py`). This makes the art unambiguously original
  (CC0), removes any licensing risk for a public repo, and animates smoothly
  via a small rig (squash/stretch, limb offsets, eye styles, props). Scraped
  reference GIFs are kept locally only and are `.gitignore`d.
- **Creature identity.** A square orange body with wide-set dash eyes, four
  stubby legs, and one body-shade block per side for arms — the "arms spread"
  standing pose. Working state hides the arms and shows typing hands behind a
  laptop.
- **Hook transport.** Claude Code hooks run `claude-pet-hook`, which forwards
  `{event, session}` to the pet over a unix socket
  (`$XDG_RUNTIME_DIR/claude-pet.sock`). The hook never blocks Claude and always
  exits 0. The pet uses a `QSocketNotifier` on the listening socket (no
  threads).

## Architecture

```
Claude Code ──hook──▶ claude-pet-hook ──unix socket──▶ pet (PyQt6)
                                                         ├─ creature.py (render)
                                                         ├─ roam / physics / drag
                                                         └─ KWin script (focus Konsole)
```

- `src/creature.py` — `draw_creature(painter, ox, oy, u, state, frame, facing)`.
  States: idle, walk, working, thinking, attention, error, celebrate, waiting.
- `src/pet.py` — window, animation timer (20 fps), roam + throw physics, drag,
  right-click menu, socket listener, multi-session priority aggregation.
- `bin/claude-pet-hook` — hook → socket bridge.
- `bin/claude-pet-install-hooks` — registers/removes hooks in settings.json.

## Hook → state mapping

| hook | state |
|------|-------|
| PreToolUse / PostToolUse / SubagentStop | working |
| UserPromptSubmit | thinking |
| Notification | attention |
| Stop | celebrate → waiting |
| SessionStart / SessionEnd | (session bookkeeping) |

Multiple sessions are aggregated by priority: attention > error > working >
thinking > celebrate > idle/waiting.

## Interaction

- Drag & throw (gravity + bounce), left-click → raise Konsole via a KWin
  scripting call (`org.kde.KWin /Scripting loadScript` + `start`), right-click
  menu (come here / quiet / quit).

## Out of scope (v1)

- Perching on window title bars (needs other windows' geometry; hard on
  Wayland).
- GIF-override rendering (assets/<state>.gif) — planned, not implemented.
- Per-session mini icons.
