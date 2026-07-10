# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

claude-pet is a pixel-art desktop creature (PyQt6) that roams the screen and changes expression in real time based on Claude Code's activity, delivered via hooks over a unix socket.

## Commands

```bash
# Run the pet
bin/claude-pet                          # launcher → python3 src/pet.py

# Register / remove Claude Code hooks in ~/.claude/settings.json (backs up first, idempotent)
bin/claude-pet-install-hooks
bin/claude-pet-install-hooks --remove
# Restart any running Claude Code session afterward so it picks up the hooks.

# Preview all creature states as a sprite sheet (renders offscreen, saves a PNG)
python3 src/creature.py [out.png]       # sprite sheet -> given path, else a temp file

# Dependency
pip install PyQt6                        # requires KDE Plasma/Wayland with XWayland; qdbus6 for click-to-focus
```

Tests live in `tests/` (pytest); run them with `python3 -m pytest -q`. Pure logic (state engine, hook payloads, physics, config, hostinfo, sprites) is unit-tested; the GUI/roaming behavior has no automated coverage, so also verify visually by running the pet or the `creature.py` sprite sheet. There is no linter or build step.

## Architecture

```
Claude Code ──hook──▶ bin/claude-pet-hook ──unix socket──▶ src/pet.py (PyQt6 window)
                                                             ├─ src/creature.py  (render)
                                                             ├─ roam / physics / drag
                                                             └─ KWin script (focus Konsole)
```

Three moving parts communicate over a unix socket at `$XDG_RUNTIME_DIR/claude-pet.sock`:

- **`bin/claude-pet-hook`** is invoked by Claude Code for each hook event (event name in `argv[1]`, JSON payload on stdin). It sends `{"event", "session"}` to the socket and exits. **Invariant: it must never block or fail Claude** — every error is swallowed and it always exits 0. If the pet isn't running, the connect fails silently.
- **`src/pet.py`** owns the window, the socket server (via `QSocketNotifier`, no threads), movement, and interaction. It maps hook events → creature states and tracks per-session state.
- **`src/creature.py`** is a pure-`QPainter`, stateless renderer: `draw_creature(painter, ox, oy, u, state, frame, facing)`. No image assets — all art is code (CC0, so the repo carries no licensing risk).

### State model (`pet.py`)

- `EVENT_STATE` maps a hook event name to a creature state; `_handle_event` records it per `session_id` in `self.sessions`.
- `_recompute_state` picks the displayed state as the highest-`PRIORITY` state across all active sessions (attention > error > working > thinking > celebrate > waiting/idle). This is how multiple concurrent Claude sessions collapse to one creature.
- `celebrate` is transient: `_tick` expires it (`state_expiry`) and downgrades lingering `celebrate` sessions to `waiting`.
- `_render_state` (what's actually painted) can differ from `claude_state` — e.g. while roaming the body paints `"walk"`, and physics/held modes paint the underlying Claude state. `mode` is one of `roam | held | thrown`; roaming only happens in idle/waiting when not dragged and not `dnd` (do-not-disturb).

> Note: `TODO.md` flags the hook→state mapping as due for a redesign — treat `EVENT_STATE` as provisional, not settled.

### Renderer conventions (`creature.py`)

- Coordinates are in **art pixels**, scaled by `u` (device px per art pixel). The bounding box is `GRID_W × GRID_H`; `pet.py` sizes its window from these plus `PAD_X/PAD_Y`.
- Each state sets rig parameters (bob, squash/stretch `sx/sy`, tilt, leg phase, eye style, prop) at the top of `draw_creature`, then shared geometry draws body/legs/arms/eyes. Add a new state by extending `STATES`, adding its rig branch, and adding any `prop`.
- `px()` applies squash/stretch about the body center and is used for the tiltable body; `rect()` draws props in untilted screen-ish space. Left/right facing is a `QPainter` mirror transform in `pet.py`'s `paintEvent`, not baked into the art.

### Platform specifics

- **XWayland is required.** `pet.py` forces `QT_QPA_PLATFORM=xcb` because native Wayland forbids a client from positioning its own window, which a roaming pet needs.
- **Click-to-focus** (`_activate_claude`) works by writing a temporary KWin script and loading it via `qdbus6 org.kde.KWin /Scripting`; the script activates the first window whose `resourceClass` contains `konsole`. This is KDE-specific and best-effort (wrapped in try/except).

## Conventions

- `assets/` (custom `*.gif`/`*.png`) and `transcript/` are `.gitignore`d — the former to avoid committing unlicensed art, the latter because raw session logs may contain secrets. Keep it that way; don't commit files there.
- User-facing menu strings are in Korean.
- Design rationale and decisions live in `docs/superpowers/specs/2026-07-09-claude-pet-design.md`.
