# Pet Motion Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/claude-pet <motion>` so the user can trigger a motion on the pet on demand — five new motions (`jump/wave/sing/juggle/float`) plus existing states — that play briefly then return, with `float` holdable as a no-gravity toggle.

**Architecture:** A new pure helper `bin/claude-pet-motion` broadcasts a `{"cmd":"motion",...}` JSON line to every live pet socket. `pet.py` handles that command as a *timed render override* layered on top of the existing `StateEngine` (which stays Claude-event-only). `creature.py` gains five new rig branches + two new props. The `claude-pet` skill dispatches the new sub-commands.

**Tech Stack:** Python 3, PyQt6 (`QPainter`), unix domain sockets, pytest.

## Global Constraints

- `bin/claude-pet-motion` MUST never block or raise — swallow every error, always exit 0 (mirrors `bin/claude-pet-hook`).
- Motion override is NOT a Claude event: it must not touch `StateEngine` and must not cancel/arm the SessionEnd quit timer.
- Motion override applies only when `self.mode not in ("held", "thrown")` — drag/throw physics always win.
- No new runtime dependencies. No new hook wiring.
- Art is code only (no image assets). New props follow the existing `rect()` untilted-space pattern.
- User-facing menu/echo strings elsewhere are Korean; CLI helper output is fine in English (matches existing `bin/` scripts).
- Verify by `python3 -m pytest` and by running the pet; there is no linter/build.

---

### Task 1: `claude-pet-motion` helper (pure core + broadcast)

**Files:**
- Create: `bin/claude-pet-motion`
- Test: `tests/test_motion_helper.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MOTIONS: dict[str, float]` — motion name → default duration seconds (`0.0` = hold until cleared).
  - `resolve_dur(name: str, override: str|None) -> float`
  - `build_motion_message(name: str|None, dur: float) -> str` — one JSON line (`\n`-terminated); `name=None` = clear.
  - `sock_paths() -> list[str]`, `send(msg: str) -> int`, `main(argv: list[str]) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_motion_helper.py`:
```python
import sys, os, json, types

MOD_PATH = os.path.join(os.path.dirname(__file__), "..", "bin", "claude-pet-motion")
mod = types.ModuleType("claude_pet_motion")
mod.__file__ = MOD_PATH
with open(MOD_PATH) as f:
    exec(compile(f.read(), MOD_PATH, "exec"), mod.__dict__)


def test_new_motions_present():
    for m in ("jump", "wave", "sing", "juggle", "float"):
        assert m in mod.MOTIONS


def test_float_holds_by_default():
    assert mod.MOTIONS["float"] == 0.0
    assert mod.resolve_dur("float", None) == 0.0


def test_resolve_dur_override_wins():
    assert mod.resolve_dur("jump", "5") == 5.0
    assert mod.resolve_dur("jump", None) == mod.MOTIONS["jump"]


def test_build_message_is_json_line():
    line = mod.build_motion_message("jump", 2.5)
    assert line.endswith("\n")
    obj = json.loads(line)
    assert obj == {"cmd": "motion", "motion": "jump", "dur": 2.5}


def test_build_message_clear():
    obj = json.loads(mod.build_motion_message(None, 0))
    assert obj["cmd"] == "motion" and obj["motion"] is None


def test_main_list_and_unknown(capsys):
    assert mod.main(["claude-pet-motion", "list"]) == 0
    assert mod.main(["claude-pet-motion", "bogus"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/claude-pet && python3 -m pytest tests/test_motion_helper.py -v`
Expected: FAIL — `FileNotFoundError` / `No such file` opening `bin/claude-pet-motion`.

- [ ] **Step 3: Write minimal implementation**

Create `bin/claude-pet-motion`:
```python
#!/usr/bin/env python3
"""claude-pet-motion — trigger a motion on running claude-pet(s).

Usage:
  claude-pet-motion <name> [dur]   play a motion (dur seconds; 0 = hold)
  claude-pet-motion stop|clear     clear any held motion
  claude-pet-motion list           list motion names

Broadcasts one JSON line to every $XDG_RUNTIME_DIR/claude-pet-*.sock.
Invariant: never block or raise; always exit 0 from the CLI entrypoint.
"""
import sys
import os
import json
import glob
import socket

# name -> default duration in seconds. 0.0 means "hold until cleared".
MOTIONS = {
    "jump": 2.5, "wave": 2.5, "sing": 3.0, "juggle": 3.0, "float": 0.0,
    # existing states, exposed as triggerable (no new art):
    "celebrate": 2.5, "thinking": 3.0, "sleeping": 4.0,
    "error": 2.5, "attention": 3.0,
}


def resolve_dur(name, override=None):
    if override is not None:
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    return MOTIONS.get(name, 2.5)


def build_motion_message(name, dur):
    """One JSON line for the pet socket. name=None -> clear the override."""
    return json.dumps({"cmd": "motion", "motion": name, "dur": dur}) + "\n"


def sock_paths():
    base = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    return glob.glob(os.path.join(base, "claude-pet-*.sock"))


def send(msg):
    """Broadcast msg to every live pet socket; return how many accepted it."""
    n = 0
    for path in sock_paths():
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect(path)
            s.sendall(msg.encode("utf-8"))
            s.close()
            n += 1
        except OSError:
            pass
    return n


def main(argv):
    arg = (argv[1] if len(argv) > 1 else "").strip().lower()
    if arg in ("", "list"):
        print("motions: " + ", ".join(MOTIONS))
        return 0
    if arg in ("stop", "clear"):
        send(build_motion_message(None, 0))
        print("motion cleared")
        return 0
    if arg not in MOTIONS:
        print("unknown motion '%s'. try: %s" % (arg, ", ".join(MOTIONS)))
        return 1
    override = argv[2] if len(argv) > 2 else None
    n = send(build_motion_message(arg, resolve_dur(arg, override)))
    print("%s -> %d pet(s)" % (arg, n))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:
        sys.exit(0)
```

- [ ] **Step 4: Make it executable and run tests**

Run:
```bash
cd ~/claude-pet && chmod +x bin/claude-pet-motion && python3 -m pytest tests/test_motion_helper.py -v
```
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add bin/claude-pet-motion tests/test_motion_helper.py
git commit -m "feat: claude-pet-motion helper — broadcast motion command to pets"
```

---

### Task 2: New creature motions (`jump/wave/sing/juggle/float`)

**Files:**
- Modify: `src/creature.py` (`STATES` line 21-23; rig branch region ~66-141; `arm` map line 144-145; props region after line 329)
- Modify: `tests/test_creature_render.py` (extend `EXTRA` coverage)

**Interfaces:**
- Consumes: nothing.
- Produces: `C.STATES` additionally contains `"jump", "wave", "sing", "juggle", "float"`; `draw_creature(p, ox, oy, u, state, frame, facing)` renders each without error.

- [ ] **Step 1: Write the failing test**

Edit `tests/test_creature_render.py` — add after `test_every_state_renders_without_error`:
```python
NEW_MOTIONS = {"jump", "wave", "sing", "juggle", "float"}


def test_new_motions_present():
    assert NEW_MOTIONS.issubset(set(C.STATES)), NEW_MOTIONS - set(C.STATES)


def test_new_motions_render_without_error():
    img = QImage(C.GRID_W * 6, C.GRID_H * 6, QImage.Format.Format_ARGB32)
    for st in NEW_MOTIONS:
        for frame in (0, 7, 50, 100):
            for facing in (1, -1):
                p = QPainter(img)
                C.draw_creature(p, 0, 0, 6, st, frame, facing=facing)
                p.end()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/claude-pet && python3 -m pytest tests/test_creature_render.py::test_new_motions_present -v`
Expected: FAIL — the assert reports the 5 names missing from `STATES`.

- [ ] **Step 3: Add the motions to `STATES`**

Edit `src/creature.py` lines 21-23 to:
```python
STATES = ("idle", "walk", "work_computer", "work_search", "work_web",
          "work_agent", "work_skill", "thinking", "attention",
          "error", "celebrate", "sleeping", "held", "falling",
          "jump", "wave", "sing", "juggle", "float")
```

- [ ] **Step 4: Add the rig branches**

In `draw_creature`, immediately BEFORE the `# arm pose derived from state` comment (currently line 143), add these `elif` branches (they extend the existing `if state == ... elif ...` chain that ends at `falling`):
```python
    elif state == "jump":
        j = abs(_sin(frame, 16, 5.5))            # tall hop
        bob = -j
        sy = 1.0 + 0.14 * (j / 5.5)              # stretch at apex
        sx = 1.0 - 0.10 * (j / 5.5)
        legphase = 0.5
        eyes = "happy"
    elif state == "wave":
        bob = _sin(frame, 30, 0.4)
        tilt = _sin(frame, 20, 4.0)              # rock while waving
        eyes = "happy"
    elif state == "sing":
        bob = _sin(frame, 22, 0.6)
        tilt = _sin(frame, 22, 5.0)              # big sway to the beat
        eyes = "happy"
        prop = "note"
    elif state == "juggle":
        bob = _sin(frame, 18, 0.4)
        eyes = "wide"
        prop = "balls"
    elif state == "float":
        bob = _sin(frame, 60, 1.6)               # slow, wide hover
        tilt = _sin(frame, 120, 3.0)             # lazy drift
        sx, sy = 1.03, 1.03                      # faintly puffed
        legphase = 0.5
        eyes = "open"
```
Note: `_sin(frame, period, amp)` and `legphase`/`eyes`/`bob`/`sx`/`sy`/`tilt`/`prop` are the same rig variables the existing branches set (see lines 57-141). `"happy"`, `"wide"`, `"open"` are existing `eye()` kinds.

- [ ] **Step 5: Give `wave` and `juggle` a raised-arm pose**

Edit the `arm` map (line 144-145) to add `wave` and `juggle`:
```python
    arm = {"work_computer": "none", "attention": "up", "celebrate": "up",
           "held": "up", "falling": "up", "juggle": "up", "wave": "wave"}.get(state, "side")
```
Then add a `wave` case to the arm-drawing block. After the `elif arm == "up":` block (ends line 194), insert:
```python
    elif arm == "wave":
        # left arm down at side, right arm raised and swinging (the wave)
        wv = _sin(frame, 16, 1.4)
        px(1.0, 7.9, 2.2, 1.9, ORANGE_D)                 # left arm at side
        px(17.3, 3.4 + wv, 2.1, 1.9, ORANGE_D)           # right arm up, waving
```
(`px`, `_sin`, `ORANGE_D` are already in scope here.)

- [ ] **Step 6: Add the `note` and `balls` props**

In the props section, after the `elif prop == "hat":` block (ends line 329, before `elif prop == "speech":`), insert:
```python
    elif prop == "note":
        # music notes bobbing up beside the head, cycling
        for k in range(2):
            nb = _sin(frame, 24, 0.8, phase=k * 0.5)
            nx = 17.6 + k * 1.9
            rect(nx, 2.4 + nb, 1.1, 1.1, EYE)            # note head
            rect(nx + 0.9, 1.2 + nb, 0.4, 2.3, EYE)      # stem
    elif prop == "balls":
        # three balls arcing overhead on staggered phases
        cols = [BULB, ORANGE_L, BULB_L]
        for k in range(3):
            t = ((frame + k * 12) % 36) / 36.0           # 0..1 around the arc
            bx = 6.0 + 9.0 * t                           # left -> right
            by = 2.6 + 3.2 * (1.0 - math.sin(t * math.pi))  # arc: high in the middle
            rect(bx, by, 1.2, 1.2, cols[k])
```
`_sin` accepts a `phase` kwarg (see the `clones` prop, line 318). `math`, `BULB`, `ORANGE_L`, `BULB_L`, `EYE`, `rect` are already in scope.

- [ ] **Step 7: Run the render tests**

Run: `cd ~/claude-pet && python3 -m pytest tests/test_creature_render.py -v`
Expected: PASS (all, including the 2 new tests).

- [ ] **Step 8: Eyeball the sprite sheet**

Run: `cd ~/claude-pet && python3 src/creature.py`
Expected: writes the sprite-sheet PNG (path hardcoded near the bottom of the file) with no traceback; open it and confirm the five new motions look reasonable. Adjust rig magnitudes if a motion reads badly (art tuning only — no interface change).

- [ ] **Step 9: Commit**

```bash
git add src/creature.py tests/test_creature_render.py
git commit -m "feat: jump/wave/sing/juggle/float creature motions + note/balls props"
```

---

### Task 3: Timed motion override in `pet.py`

**Files:**
- Modify: `src/pet.py` (`__init__` fields ~112-116; `_handle_event` 182-188; `_tick` after line 210)
- Modify: `tests/test_pet_smoke.py`

**Interfaces:**
- Consumes: `build_motion_message`-shaped events, i.e. `{"cmd": "motion", "motion": <str|None>, "dur": <float>}`.
- Produces: `Pet._motion: str|None`, `Pet._motion_expiry: float|None`; a motion cmd sets `_render_state` on the next `_tick` when `mode` is roam-like.

- [ ] **Step 1: Write the failing test**

Edit `tests/test_pet_smoke.py` — add:
```python
def test_motion_command_overrides_render_state():
    p = P.Pet(session_id="m1")
    try:
        p._handle_event({"cmd": "motion", "motion": "jump", "dur": 2.0})
        assert p._motion == "jump"
        p.mode = "roam"
        p._tick()
        assert p._render_state == "jump"
    finally:
        p._cleanup()


def test_motion_command_does_not_cancel_quit_timer():
    p = P.Pet(session_id="m2")
    try:
        p._handle_event({"event": "SessionEnd", "session": "m2"})
        assert p._quit_timer is not None
        p._handle_event({"cmd": "motion", "motion": "wave", "dur": 1.0})
        assert p._quit_timer is not None      # a motion cmd is NOT a Claude event
    finally:
        p._cleanup()


def test_motion_clear_releases_override():
    p = P.Pet(session_id="m3")
    try:
        p._handle_event({"cmd": "motion", "motion": "float", "dur": 0})
        assert p._motion == "float"
        p._handle_event({"cmd": "motion", "motion": None, "dur": 0})
        assert p._motion is None
    finally:
        p._cleanup()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/claude-pet && python3 -m pytest tests/test_pet_smoke.py::test_motion_command_overrides_render_state -v`
Expected: FAIL — `AttributeError: 'Pet' object has no attribute '_motion'`.

- [ ] **Step 3: Add override fields in `__init__`**

In `src/pet.py`, in the `# movement` block (after `self.vx = self.vy = 0.0`, line 116), add:
```python
        # user-triggered motion override (timed; independent of StateEngine)
        self._motion = None
        self._motion_expiry = None       # monotonic deadline; None = hold
```

- [ ] **Step 4: Handle the motion command in `_handle_event`**

Replace the body of `_handle_event` (lines 182-188) with:
```python
    def _handle_event(self, ev):
        # A motion command is a user override, NOT a Claude event: it must not
        # touch the engine or the SessionEnd quit timer.
        if ev.get("cmd") == "motion":
            motion = ev.get("motion")
            if not motion:
                if self._motion == "float":
                    self.mode = "thrown"        # gravity brings the floater home
                self._motion = None
                self._motion_expiry = None
            else:
                dur = ev.get("dur", 0) or 0
                self._motion = motion
                self._motion_expiry = (time.monotonic() + dur) if dur > 0 else None
            return
        self.engine.handle(ev, time.monotonic())
        name = ev.get("event") or ev.get("hook_event_name") or ""
        if name == "SessionEnd":
            self._arm_quit()          # session ended -> wind down (cancellable)
        else:
            self._cancel_quit()       # any other event means the session lives on
```

- [ ] **Step 5: Apply the override in `_tick`**

In `_tick`, the current lines 210-214 are:
```python
        self.claude_state = self.engine.display_state(now)
        eff = self.claude_state
        self._update_tray_icon()

        roaming = eff in ("idle", "sleeping") and self.mode == "roam" and not self.dnd
```
Insert an override check between the `_update_tray_icon()` call and the `roaming =` line:
```python
        self._update_tray_icon()

        # user-triggered motion override wins over roam/idle, but never over
        # drag/throw physics (held/thrown paint their own thing).
        if self._motion and self.mode not in ("held", "thrown"):
            if self._motion_expiry is not None and now >= self._motion_expiry:
                self._motion = None
                self._motion_expiry = None
            else:
                if self._motion == "float":
                    self.y = float(self.screen_rect.top() + self.h)  # hover high
                self._render_state = self._motion
                return

        roaming = eff in ("idle", "sleeping") and self.mode == "roam" and not self.dnd
```
(`self.frame` was already advanced at the top of `_tick`, so the motion animates. The `return` skips roam/physics for this tick so the motion is what paints.)

- [ ] **Step 6: Run the tests**

Run: `cd ~/claude-pet && python3 -m pytest tests/test_pet_smoke.py -v`
Expected: PASS (all, including the 3 new tests).

- [ ] **Step 7: Full suite regression check**

Run: `cd ~/claude-pet && python3 -m pytest -q`
Expected: PASS — previously-passing tests (physics, bounds, roam-fall, etc.) unaffected.

- [ ] **Step 8: Commit**

```bash
git add src/pet.py tests/test_pet_smoke.py
git commit -m "feat: timed motion override in pet (cmd=motion), float holds until cleared"
```

---

### Task 4: Skill dispatch for `/claude-pet <motion>`

**Files:**
- Modify: `skills/claude-pet/SKILL.md`

**Interfaces:**
- Consumes: `bin/claude-pet-motion` (Task 1).
- Produces: documented routing so that when the user types `/claude-pet <motion>`, `/claude-pet list`, or `/claude-pet stop`, Claude runs the helper instead of the attach/standalone flow.

- [ ] **Step 1: Update the skill front-matter description**

In `skills/claude-pet/SKILL.md`, replace the `description:` line (line 3) with:
```
description: Launch/attach the claude-pet desktop buddy, or trigger a motion on it. "/claude-pet" attaches a pet to the CURRENT session; "/claude-pet standalone" launches an unattached roaming pet; "/claude-pet <motion>" plays a motion (jump/wave/sing/juggle/float/celebrate/thinking/sleeping/error/attention); "/claude-pet list" lists motions; "/claude-pet stop" clears a held motion. Use when the user types "/claude-pet", "펫 띄워", "펫 붙여", "펫 점프", "start the pet".
```

- [ ] **Step 2: Add a dispatch section**

In `skills/claude-pet/SKILL.md`, immediately after the H1 intro paragraph (after line 10, before `## Default: attach to THIS session`), insert:
```markdown
## Routing

Look at the argument the user passed after `/claude-pet`:

- a **motion name** (`jump`, `wave`, `sing`, `juggle`, `float`, `celebrate`,
  `thinking`, `sleeping`, `error`, `attention`), or `list`, or `stop`/`clear`
  → run the motion helper (below); do NOT launch a pet.
- `standalone` → the standalone section.
- nothing → the attach section.

### Trigger a motion

```bash
~/claude-pet/bin/claude-pet-motion <arg>
```
e.g. `~/claude-pet/bin/claude-pet-motion jump`, `~/claude-pet/bin/claude-pet-motion float`
(holds until `~/claude-pet/bin/claude-pet-motion stop`), `~/claude-pet/bin/claude-pet-motion list`.
The helper broadcasts to every running pet and prints how many reacted; if it
says `-> 0 pet(s)`, no pet is running — offer to attach one with `/claude-pet`.
```

- [ ] **Step 3: Verify the skill end-to-end (manual)**

With a pet running (from earlier in the session), run:
```bash
~/claude-pet/bin/claude-pet-motion jump
~/claude-pet/bin/claude-pet-motion float
~/claude-pet/bin/claude-pet-motion stop
~/claude-pet/bin/claude-pet-motion list
```
Expected: each prints its line; the on-screen pet hops for `jump`, rises and hovers for `float`, drops back under gravity on `stop`; `list` prints the motion names. `-> 0 pet(s)` only if no pet is running.

- [ ] **Step 4: Commit**

```bash
git add skills/claude-pet/SKILL.md
git commit -m "feat: /claude-pet <motion> skill routing to claude-pet-motion"
```

---

## Notes for the implementer

- Frame/animation is driven by `self.frame` (incremented at the top of `_tick`) and passed to `draw_creature`; you don't animate in `pet.py`, only pick the state.
- `float` hover line: `screen_rect.top() + self.h` keeps the whole window on-screen near the top of the desktop. If it reads too high/low, tune the offset — behavior, not interface.
- Do not route motion through `StateEngine`: it is intentionally Claude-event-only, and its `display_state` priority logic would fight the override.
- The multi-monitor roam fix (`_screen_bottom_at`, shipped `b08c46e`) is unrelated; leave it untouched.
