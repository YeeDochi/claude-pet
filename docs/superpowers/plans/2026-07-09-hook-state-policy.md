# Hook→State Policy & Animation Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Claude Code's instantaneous hook events into a continuous, tool-aware creature state, and add the animations for it.

**Architecture:** Extract the policy into a pure, Qt-free `src/state_engine.py` (time and terminal-focus injected, so it unit-tests deterministically). `pet.py` feeds it hook events and asks it for the display state each frame. `claude-pet-hook` is widened to forward `tool_name`/`notification_type`/`error_type`. `creature.py` gains the new render states.

**Tech Stack:** Python 3, PyQt6, pytest (dev only), KDE Plasma/Wayland (XWayland), `qdbus6`.

## Global Constraints

- `bin/claude-pet-hook` must NEVER block or fail Claude Code — swallow every error, always exit 0.
- No new runtime dependencies beyond PyQt6 (pytest is dev-only; focus detection may use `kdotool`/`qdbus6` if present but must degrade gracefully when absent).
- Renderer art is code-only (no image assets); keep the `QPainter` style in `creature.py`.
- Timing constants (verbatim): debounce/min-hold `0.8s`; `idle`→`sleeping` after `60s` quiet; celebrate `1.6s`; error `2.0s`.
- State names (verbatim): `thinking`, `work_computer`, `work_search`, `work_web`, `work_agent`, `work_skill`, `attention`, `idle` (calm/awake), `celebrate`, `sleeping` (zZ), `error`, `walk` (render-only). The old renderer state `waiting` (the zZ one) is renamed `sleeping`; the old `idle` (calm bob) keeps its name.
- Spec: `docs/superpowers/specs/2026-07-09-hook-state-policy-design.md`.

---

## File Structure

- **Create** `src/state_engine.py` — pure policy engine (no Qt, no wall-clock).
- **Create** `tests/test_state_engine.py` — pytest for the engine.
- **Modify** `bin/claude-pet-hook` — forward `tool_name`, `notification_type`, `error_type`.
- **Modify** `bin/claude-pet-install-hooks` — register `StopFailure`.
- **Modify** `src/creature.py` — rename `waiting`→`sleeping`; add `thinking` (ponder), `work_computer` (alias of laptop), `work_search`, `work_web`, `work_agent`, `work_skill`.
- **Modify** `src/pet.py` — replace `EVENT_STATE`/`_recompute_state` with `StateEngine`; add focus detection; age timers in `_tick`.
- **Create** `src/focus.py` — terminal-focus probe (the spike), Qt-free, returns `bool`.

---

## Task 1: State engine — tool mapping, per-session base states, priority

**Files:**
- Create: `src/state_engine.py`
- Test: `tests/test_state_engine.py`

**Interfaces:**
- Produces:
  - `tool_to_state(tool_name: str) -> str`
  - `StateEngine(is_focused: Callable[[], bool] = None)` with `handle(ev: dict, now: float) -> None` and `display_state(now: float) -> str`
  - module constants `TOOL_STATES`, `WORK_STATES`, `PRIORITY`, `DEBOUNCE`, `SLEEP_TIMEOUT`, `CELEBRATE_DUR`, `ERROR_DUR`

- [ ] **Step 1: Ensure pytest is available**

Run: `python3 -c "import pytest" 2>/dev/null || pip install pytest`
Expected: exits cleanly (pytest importable).

- [ ] **Step 2: Write the failing test**

Create `tests/test_state_engine.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from state_engine import tool_to_state, StateEngine


def test_tool_to_state_known_and_fallback():
    assert tool_to_state("Edit") == "work_computer"
    assert tool_to_state("Bash") == "work_computer"
    assert tool_to_state("Read") == "work_search"
    assert tool_to_state("Grep") == "work_search"
    assert tool_to_state("WebFetch") == "work_web"
    assert tool_to_state("Task") == "work_agent"
    assert tool_to_state("Skill") == "work_skill"
    assert tool_to_state("mcp__gitlab__get_project") == "work_web"
    assert tool_to_state("SomethingNew") == "work_computer"   # fallback


def test_pretooluse_sets_work_state():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Edit"}, now=0.0)
    assert e.display_state(now=0.0) == "work_computer"


def test_no_sessions_is_sleeping():
    e = StateEngine()
    assert e.display_state(now=0.0) == "sleeping"


def test_priority_picks_attention_over_work():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Edit"}, now=0.0)
    e.handle({"event": "Notification", "session": "b",
              "notification_type": "permission_prompt"}, now=0.0)
    assert e.display_state(now=0.0) == "attention"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_state_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'state_engine'`.

- [ ] **Step 4: Write minimal implementation**

Create `src/state_engine.py`:

```python
"""Pure policy engine: Claude Code hook events -> creature display state.

No Qt and no wall-clock: callers pass `now` (a monotonic float) into every
method, so behaviour is deterministic under test. Terminal focus is injected
as a zero-arg callable returning bool.
"""

TOOL_STATES = {
    "Edit": "work_computer", "Write": "work_computer",
    "NotebookEdit": "work_computer", "Bash": "work_computer",
    "Read": "work_search", "Grep": "work_search", "Glob": "work_search",
    "WebFetch": "work_web", "WebSearch": "work_web",
    "Task": "work_agent",
    "Skill": "work_skill",
}
WORK_STATES = {"work_computer", "work_search", "work_web",
               "work_agent", "work_skill"}

PRIORITY = {
    "attention": 6, "error": 5,
    "work_computer": 4, "work_search": 4, "work_web": 4,
    "work_agent": 4, "work_skill": 4,
    "thinking": 3, "celebrate": 2, "idle": 1, "sleeping": 0,
}

DEBOUNCE = 0.8
SLEEP_TIMEOUT = 60.0
CELEBRATE_DUR = 1.6
ERROR_DUR = 2.0


def tool_to_state(tool_name):
    if tool_name in TOOL_STATES:
        return TOOL_STATES[tool_name]
    if tool_name and tool_name.startswith("mcp__"):
        return "work_web"
    return "work_computer"


class _Session:
    __slots__ = ("state", "since", "expiry", "last_event", "pending")

    def __init__(self, now):
        self.state = "idle"
        self.since = now
        self.expiry = None     # end ts for transient states (celebrate/error)
        self.last_event = now
        self.pending = None    # deferred work state (debounce)

    def set_state(self, state, now):
        self.state = state
        self.since = now
        self.expiry = None
        self.pending = None


class StateEngine:
    def __init__(self, is_focused=None):
        self.sessions = {}
        self.is_focused = is_focused or (lambda: True)

    def handle(self, ev, now):
        name = ev.get("event") or ev.get("hook_event_name") or ""
        sid = str(ev.get("session") or ev.get("session_id") or "default")
        if name == "SessionEnd":
            self.sessions.pop(sid, None)
            return
        s = self.sessions.get(sid)
        if s is None:
            s = self.sessions[sid] = _Session(now)
        s.last_event = now

        if name == "SessionStart":
            s.set_state("idle", now)
        elif name == "UserPromptSubmit":
            s.set_state("thinking", now)
        elif name == "PreToolUse":
            self._set_work(s, tool_to_state(ev.get("tool_name", "")), now)
        elif name == "Notification":
            nt = ev.get("notification_type", "")
            if nt == "permission_prompt":
                s.set_state("attention", now)
            elif nt == "idle_prompt":
                s.set_state("sleeping", now)
        elif name == "Stop":
            if self.is_focused():
                s.set_state("idle", now)
            else:
                s.set_state("celebrate", now)
                s.expiry = now + CELEBRATE_DUR
        elif name == "StopFailure":
            s.set_state("error", now)
            s.expiry = now + ERROR_DUR
        # PostToolUse / SubagentStop / unknown: liveness refresh only

    def _set_work(self, s, work_state, now):
        s.set_state(work_state, now)

    def display_state(self, now):
        if not self.sessions:
            return "sleeping"
        return max((s.state for s in self.sessions.values()),
                   key=lambda st: PRIORITY.get(st, 0))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_state_engine.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add src/state_engine.py tests/test_state_engine.py
git commit -m "feat: state engine core — tool mapping, sessions, priority"
```

---

## Task 2: State engine — debounce (minimum hold on work states)

**Files:**
- Modify: `src/state_engine.py` (`_set_work`, add `_age`, call `_age` from `display_state`)
- Test: `tests/test_state_engine.py`

**Interfaces:**
- Produces: `StateEngine._age(session, now)` internal; `display_state` now ages sessions before picking.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_state_engine.py`:

```python
def test_debounce_holds_fast_tool_switch():
    e = StateEngine()
    # a fast Read then an immediate Edit within the debounce window
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Read"}, now=0.0)
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Edit"}, now=0.2)
    # still inside 0.8s hold -> the search motion is still what shows
    assert e.display_state(now=0.3) == "work_search"
    # after the hold expires, the pending Edit is promoted
    assert e.display_state(now=0.9) == "work_computer"


def test_same_tool_repeats_do_not_reset_forever():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Read"}, now=0.0)
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Grep"}, now=0.1)
    # Grep is also work_search — no visible change, no pending needed
    assert e.display_state(now=0.2) == "work_search"
    assert e.display_state(now=1.0) == "work_search"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_state_engine.py::test_debounce_holds_fast_tool_switch -v`
Expected: FAIL — returns `work_computer` at 0.3 (no debounce yet).

- [ ] **Step 3: Implement debounce**

In `src/state_engine.py`, replace `_set_work` with:

```python
    def _set_work(self, s, work_state, now):
        # Guarantee the current work motion shows >= DEBOUNCE before switching
        # to a *different* work motion; remember the latest as pending.
        if s.state in WORK_STATES and (now - s.since) < DEBOUNCE:
            if work_state != s.state:
                s.pending = work_state
            return
        s.set_state(work_state, now)
```

Add a new method `_age` (place it directly above `display_state`):

```python
    def _age(self, s, now):
        # promote a deferred work state once the current one has held long enough
        if s.pending and s.state in WORK_STATES and (now - s.since) >= DEBOUNCE:
            s.set_state(s.pending, now)
```

Replace `display_state` with:

```python
    def display_state(self, now):
        for s in self.sessions.values():
            self._age(s, now)
        if not self.sessions:
            return "sleeping"
        return max((s.state for s in self.sessions.values()),
                   key=lambda st: PRIORITY.get(st, 0))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_state_engine.py -v`
Expected: PASS (all, including the two new).

- [ ] **Step 5: Commit**

```bash
git add src/state_engine.py tests/test_state_engine.py
git commit -m "feat: state engine debounce (0.8s min hold on work motions)"
```

---

## Task 3: State engine — transient decay, sleep timeout, focus-gated celebrate, thinking

**Files:**
- Modify: `src/state_engine.py` (`_age`)
- Test: `tests/test_state_engine.py`

**Interfaces:**
- Produces: `_age` now also decays `celebrate`/`error` → `idle`, and ages `idle` → `sleeping` after `SLEEP_TIMEOUT`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state_engine.py`:

```python
def test_stop_focused_goes_idle_not_celebrate():
    e = StateEngine(is_focused=lambda: True)
    e.handle({"event": "Stop", "session": "a"}, now=0.0)
    assert e.display_state(now=0.0) == "idle"


def test_stop_unfocused_celebrates_then_decays_to_idle():
    e = StateEngine(is_focused=lambda: False)
    e.handle({"event": "Stop", "session": "a"}, now=0.0)
    assert e.display_state(now=0.5) == "celebrate"
    assert e.display_state(now=1.7) == "idle"      # after CELEBRATE_DUR (1.6s)


def test_idle_sleeps_after_timeout():
    e = StateEngine(is_focused=lambda: True)
    e.handle({"event": "Stop", "session": "a"}, now=0.0)      # -> idle
    assert e.display_state(now=10.0) == "idle"
    assert e.display_state(now=61.0) == "sleeping"            # 60s quiet


def test_idle_prompt_sleeps_immediately():
    e = StateEngine()
    e.handle({"event": "Notification", "session": "a",
              "notification_type": "idle_prompt"}, now=0.0)
    assert e.display_state(now=0.1) == "sleeping"


def test_stopfailure_errors_then_decays():
    e = StateEngine()
    e.handle({"event": "StopFailure", "session": "a"}, now=0.0)
    assert e.display_state(now=1.0) == "error"
    assert e.display_state(now=2.1) == "idle"                 # after ERROR_DUR (2.0s)


def test_userpromptsubmit_thinks_then_works():
    e = StateEngine()
    e.handle({"event": "UserPromptSubmit", "session": "a"}, now=0.0)
    assert e.display_state(now=0.0) == "thinking"
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Read"}, now=0.5)
    assert e.display_state(now=0.5) == "work_search"


def test_sessionend_drops_session():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Edit"}, now=0.0)
    e.handle({"event": "SessionEnd", "session": "a"}, now=0.1)
    assert e.display_state(now=0.1) == "sleeping"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_state_engine.py -v`
Expected: FAIL on the decay/sleep tests (`celebrate` never decays, `idle` never sleeps).

- [ ] **Step 3: Extend `_age`**

In `src/state_engine.py`, replace `_age` with:

```python
    def _age(self, s, now):
        # promote a deferred work state once the current one has held long enough
        if s.pending and s.state in WORK_STATES and (now - s.since) >= DEBOUNCE:
            s.set_state(s.pending, now)
        # transient states (celebrate/error) decay back to calm idle
        if s.expiry is not None and now >= s.expiry:
            s.set_state("idle", now)
        # calm idle falls asleep after a long quiet spell
        if s.state == "idle" and (now - s.last_event) >= SLEEP_TIMEOUT:
            s.state = "sleeping"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_state_engine.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/state_engine.py tests/test_state_engine.py
git commit -m "feat: state engine transients, sleep timeout, focus-gated celebrate"
```

---

## Task 4: Widen `claude-pet-hook` to forward tool/notification/error fields

**Files:**
- Modify: `bin/claude-pet-hook`
- Test: `tests/test_hook_payload.py` (create)

**Interfaces:**
- Produces: the socket message JSON now includes `tool_name`, `notification_type`, `error_type` when present in the incoming payload.

- [ ] **Step 1: Write the failing test**

The message-building logic is currently inline in `main()`. Extract it to a
testable `build_message(argv, stdin_json)` function. Create
`tests/test_hook_payload.py`:

```python
import sys, os, json, importlib.util

HOOK = os.path.join(os.path.dirname(__file__), "..", "bin", "claude-pet-hook")
spec = importlib.util.spec_from_file_location("claude_pet_hook", HOOK)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_pretooluse_forwards_tool_name():
    msg = json.loads(mod.build_message(
        ["claude-pet-hook", "PreToolUse"],
        {"session_id": "s1", "tool_name": "Edit", "tool_input": {}}))
    assert msg["event"] == "PreToolUse"
    assert msg["session"] == "s1"
    assert msg["tool_name"] == "Edit"


def test_notification_forwards_type():
    msg = json.loads(mod.build_message(
        ["claude-pet-hook", "Notification"],
        {"session_id": "s1", "notification_type": "permission_prompt"}))
    assert msg["notification_type"] == "permission_prompt"


def test_missing_fields_omitted():
    msg = json.loads(mod.build_message(["claude-pet-hook", "Stop"],
                                       {"session_id": "s1"}))
    assert msg["event"] == "Stop"
    assert "tool_name" not in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hook_payload.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'build_message'`.

- [ ] **Step 3: Refactor `bin/claude-pet-hook`**

Replace the body of `main()` and add `build_message`. The file becomes:

```python
#!/usr/bin/env python3
"""claude-pet-hook — forwards a Claude Code hook event to the running pet.

Registered in ~/.claude/settings.json for each hook event. Claude Code invokes
it with the event name as argv[1] and the hook payload as JSON on stdin. It
sends a small JSON line to the pet's unix socket and exits 0 immediately.

Must never block or fail Claude: any error is swallowed and exit is always 0.
"""
import sys
import os
import json
import socket

SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "claude-pet.sock")


def build_message(argv, data):
    """Build the JSON line to send to the pet. Pure; unit-tested."""
    event = (argv[1] if len(argv) > 1 else "") or data.get("hook_event_name", "")
    msg = {"event": event, "session": data.get("session_id") or "default"}
    for key in ("tool_name", "notification_type", "error_type"):
        val = data.get(key)
        if val:
            msg[key] = val
    return json.dumps(msg) + "\n"


def main():
    raw = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
    except Exception:
        pass
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    try:
        payload = build_message(sys.argv, data).encode()
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect(SOCK)
        s.sendall(payload)
        s.close()
    except Exception:
        pass  # pet not running or any error — ignore silently


if __name__ == "__main__":
    main()
    sys.exit(0)   # hooks must always succeed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hook_payload.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add bin/claude-pet-hook tests/test_hook_payload.py
git commit -m "feat: hook forwards tool_name/notification_type/error_type"
```

---

## Task 5: Register `StopFailure` hook

**Files:**
- Modify: `bin/claude-pet-install-hooks`

**Interfaces:**
- Produces: `StopFailure` added to `PLAIN_EVENTS` so installing registers it.

- [ ] **Step 1: Add the event**

In `bin/claude-pet-install-hooks`, change:

```python
PLAIN_EVENTS = ["UserPromptSubmit", "Notification", "Stop",
                "SubagentStop", "SessionStart", "SessionEnd"]
```

to:

```python
PLAIN_EVENTS = ["UserPromptSubmit", "Notification", "Stop", "StopFailure",
                "SubagentStop", "SessionStart", "SessionEnd"]
```

- [ ] **Step 2: Verify install/remove round-trips without clobbering**

Run:
```bash
cp -n ~/.claude/settings.json /tmp/settings.pretest.json 2>/dev/null || true
bin/claude-pet-install-hooks
python3 -c "import json;h=json.load(open('$HOME/.claude/settings.json'))['hooks'];assert 'StopFailure' in h, list(h);print('StopFailure registered OK')"
bin/claude-pet-install-hooks --remove
python3 -c "import json;print('removed OK')"
```
Expected: prints `StopFailure registered OK` then `removed OK`. (The script backs up settings.json each write; that is expected.)

- [ ] **Step 3: Commit**

```bash
git add bin/claude-pet-install-hooks
git commit -m "feat: register StopFailure hook"
```

---

## Task 6: Renderer — rename `waiting`→`sleeping`, add new states

**Files:**
- Modify: `src/creature.py`
- Test: `tests/test_creature_render.py` (create)

**Interfaces:**
- Consumes: existing `draw_creature(p, ox, oy, u, state, frame, facing)` and `STATES`.
- Produces: `STATES` contains all 12 names from Global Constraints; `draw_creature` runs without error for every state.

- [ ] **Step 1: Write the failing test**

Create `tests/test_creature_render.py`:

```python
import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication
import creature as C

_app = QApplication.instance() or QApplication(sys.argv)

EXPECTED = {"thinking", "work_computer", "work_search", "work_web",
            "work_agent", "work_skill", "attention", "idle",
            "celebrate", "sleeping", "error", "walk"}


def test_states_present():
    assert EXPECTED.issubset(set(C.STATES)), EXPECTED - set(C.STATES)
    assert "waiting" not in C.STATES   # renamed to sleeping


def test_every_state_renders_without_error():
    img = QImage(C.GRID_W * 6, C.GRID_H * 6, QImage.Format.Format_ARGB32)
    for st in EXPECTED:
        for frame in (0, 7, 50, 100):
            p = QPainter(img)
            C.draw_creature(p, 0, 0, 6, st, frame)
            p.end()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_creature_render.py -v`
Expected: FAIL on `test_states_present` (new states missing, `waiting` still present).

- [ ] **Step 3: Update `STATES` and rig branches**

In `src/creature.py`:

3a. Replace the `STATES` tuple:

```python
STATES = ("idle", "walk", "work_computer", "work_search", "work_web",
          "work_agent", "work_skill", "thinking", "attention",
          "error", "celebrate", "sleeping")
```

3b. Rename the `waiting` branch to `sleeping` (same body):

```python
    elif state == "sleeping":
        bob = _sin(frame, 50, 0.4)
        eyes = "sleep"
        prop = "zzz"
```

3c. Replace the old `working` branch with `work_computer` (identical laptop rig):

```python
    elif state == "work_computer":
        bob = _sin(frame, 30, 0.3)                # gentle head bob while typing
        eyes = "focus"
        prop = "laptop"
```

3d. Replace the old `thinking` (bulb) branch with a pondering pose:

```python
    elif state == "thinking":
        bob = _sin(frame, 46, 0.35)
        tilt = _sin(frame, 92, 3.0)               # slow head cant, "hmm"
        eyes = "up"
        prop = "ponder"
```

3e. Add the three new work states after `work_computer`:

```python
    elif state == "work_search":
        bob = abs(_sin(frame, 6, 0.7))            # busy little bounce
        legphase = (frame / 6.0) % 1.0            # fast legs
        tilt = _sin(frame, 6, 3.5)                # quick side-to-side lean
        eyes = "focus"
        prop = "magnify"
    elif state == "work_web":
        bob = _sin(frame, 40, 0.3)
        eyes = "up"
        prop = "phone"
    elif state == "work_agent":
        bob = _sin(frame, 34, 0.4)
        eyes = "open"
        prop = "clones"
    elif state == "work_skill":
        bob = _sin(frame, 28, 0.5)
        eyes = "happy"
        prop = "hat"
```

3f. Update the arm-pose map so laptop/agent hide/keep arms sensibly:

```python
    arm = {"work_computer": "none", "attention": "up",
           "celebrate": "up"}.get(state, "side")
```

- [ ] **Step 4: Add the new props**

In the props section of `draw_creature` (after the existing `zzz` branch), add:

```python
    elif prop == "ponder":
        # slow "?" that fades in over the head
        if (frame % 90) > 20:
            p.setPen(QPen(ZTXT)); f = QFont("Sans"); f.setPointSizeF(1.8 * u)
            f.setBold(True); p.setFont(f)
            p.drawText(int(ox + 18 * u), int(oy + (3.2 + bob) * u), "?")
            p.setPen(Qt.PenStyle.NoPen)
    elif prop == "magnify":
        # a little magnifying glass held out front
        rect(17.6, 6.2, 2.6, 2.6, QColor("#BFC7D0"))     # lens ring
        rect(18.1, 6.7, 1.6, 1.6, QColor("#9FD3E8"))     # glass
        rect(19.4, 8.4, 1.4, 1.2, ORANGE_D)              # handle
    elif prop == "phone":
        # a chunky handset held to the head; slow "ring" dots
        rect(2.0, 6.0, 1.6, 3.0, QColor("#2A2A30"))      # handset body
        rect(1.7, 5.7, 2.2, 0.9, QColor("#2A2A30"))      # ear piece
        if (frame % 40) < 20:
            rect(0.4, 4.4, 0.8, 0.8, BULB_L)             # ~ ring spark
    elif prop == "clones":
        # two mini creatures filing out to the right, bobbing in sequence
        for k in range(2):
            mb = _sin(frame, 18, 0.6, phase=k * 0.5)
            bx = 18.5 + k * 2.2
            rect(bx, 9.5 + mb, 1.8, 1.8, ORANGE)         # tiny body
            rect(bx, 9.5 + mb, 1.8, 0.5, ORANGE_L)       # highlight
            rect(bx + 0.3, 10.1 + mb, 0.4, 0.5, EYE)     # eye
    elif prop == "hat":
        # party/wizard cone hat + a sparkle
        rect(9.0, 2.0, 3.0, 0.7, QColor("#6C5CE7"))      # brim
        rect(9.7, 0.6, 1.6, 1.6, QColor("#8E7CFF"))      # cone
        rect(10.1, 0.1, 0.8, 0.8, BULB_L)                # pom
        if (frame % 30) < 15:
            rect(13.0, 1.4, 0.9, 0.9, BULB_L)            # sparkle
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_creature_render.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Eyeball the sprite sheet**

Update the sprite-sheet `__main__` block: set
`order = ["idle", "walk", "work_computer", "work_search", "work_web", "work_agent", "work_skill", "thinking", "attention", "celebrate", "error", "sleeping"]`
and give `labels` a Korean entry for each (e.g. `"work_web": "웹/전화"`). Fix the
hardcoded `out` path to the scratchpad dir for this session, then run:

Run: `python3 src/creature.py`
Expected: prints `saved <path>`; open the PNG and confirm each new state reads
clearly. Tune rig numbers by eye if needed (art is expected to be adjusted here).

- [ ] **Step 7: Commit**

```bash
git add src/creature.py tests/test_creature_render.py
git commit -m "feat: renderer — sleeping rename + thinking/search/web/agent/skill states"
```

---

## Task 7: Focus probe (`src/focus.py`) — the spike

**Files:**
- Create: `src/focus.py`
- Test: `tests/test_focus.py` (create)

**Interfaces:**
- Produces: `terminal_focused() -> bool` — True if the Claude terminal (Konsole) is the active window; conservatively returns `True` when detection is unavailable (so celebrate is suppressed rather than firing while the user is watching). Also `_active_window_class() -> str | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_focus.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import focus


def test_focused_true_when_class_is_konsole(monkeypatch):
    monkeypatch.setattr(focus, "_active_window_class", lambda: "konsole")
    assert focus.terminal_focused() is True


def test_focused_false_when_other_window(monkeypatch):
    monkeypatch.setattr(focus, "_active_window_class", lambda: "firefox")
    assert focus.terminal_focused() is False


def test_focused_true_when_unknown(monkeypatch):
    # detection unavailable -> conservative: assume focused (suppress celebrate)
    monkeypatch.setattr(focus, "_active_window_class", lambda: None)
    assert focus.terminal_focused() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_focus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'focus'`.

- [ ] **Step 3: Implement the probe**

Create `src/focus.py`:

```python
"""Best-effort probe: is the Claude terminal (Konsole) the active window?

KDE Wayland does not expose the active window's class over plain DBus, and X
tools cannot see native Wayland clients. We try `kdotool` (a KWin-scripting
CLI) first; if it is absent or fails, we report "unknown" and the caller treats
that conservatively (assume focused -> no celebrate). Enabling reliable
detection is the spike: if kdotool is not acceptable, replace
`_active_window_class` with a persistent KWin script that emits the active
window's resourceClass over DBus.
"""
import shutil
import subprocess

TERMINAL_CLASSES = ("konsole",)   # extend if other terminals are used


def _active_window_class():
    """Return the active window's class lowercased, or None if undetectable."""
    kdotool = shutil.which("kdotool")
    if not kdotool:
        return None
    try:
        wid = subprocess.check_output([kdotool, "getactivewindow"],
                                      text=True, timeout=2).strip()
        if not wid:
            return None
        cls = subprocess.check_output(
            [kdotool, "getwindowclassname", wid],
            text=True, timeout=2).strip().lower()
        return cls or None
    except Exception:
        return None


def terminal_focused():
    cls = _active_window_class()
    if cls is None:
        return True   # conservative: unknown -> assume focused, suppress celebrate
    return any(t in cls for t in TERMINAL_CLASSES)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_focus.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Manual spike check (record the result)**

Run: `python3 -c "import sys; sys.path.insert(0,'src'); import focus; print('class=', focus._active_window_class(), 'focused=', focus.terminal_focused())"`
Expected: If `kdotool` is installed, prints the real active window class. If it
prints `class= None`, note in the commit body that live focus detection is not
yet available on this machine and celebrate will stay suppressed until the KWin
fallback is built (tracked as follow-up in TODO.md).

- [ ] **Step 6: Commit**

```bash
git add src/focus.py tests/test_focus.py
git commit -m "feat: terminal focus probe (kdotool, conservative fallback)"
```

---

## Task 8: Wire the engine + focus into `pet.py`

**Files:**
- Modify: `src/pet.py`
- Test: `tests/test_pet_smoke.py` (create)

**Interfaces:**
- Consumes: `state_engine.StateEngine`, `focus.terminal_focused`.
- Produces: `Pet` drives rendering from `engine.display_state(now)`; hook socket lines feed `engine.handle(ev, now)`.

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_pet_smoke.py`:

```python
import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from PyQt6.QtWidgets import QApplication
import pet as P

_app = QApplication.instance() or QApplication(sys.argv)


def test_pet_constructs_and_uses_engine():
    p = P.Pet()
    assert hasattr(p, "engine")
    # feed a PreToolUse and confirm the engine drives the claude state
    p._handle_event({"event": "PreToolUse", "session": "a", "tool_name": "Bash"})
    p._tick()
    assert p.claude_state == "work_computer"
    p._cleanup()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_pet_smoke.py -v`
Expected: FAIL — `Pet` has no `engine` attribute.

- [ ] **Step 3: Replace the mapping/recompute with the engine**

In `src/pet.py`:

3a. Add imports near the top (after `import creature as C`):

```python
from state_engine import StateEngine
import focus
```

3b. Delete the module-level `EVENT_STATE` and `PRIORITY` dicts (the engine owns them now).

3c. In `Pet.__init__`, replace the `self.claude_state`/`self.sessions`/`self.state_expiry` lines with:

```python
        self.engine = StateEngine(is_focused=focus.terminal_focused)
        self.claude_state = "sleeping"       # last state the engine reported
```

3d. Replace `_handle_event` and delete `_recompute_state`:

```python
    def _handle_event(self, ev):
        self.engine.handle(ev, time.monotonic())
```

3e. In `_tick`, replace the celebrate-decay block and the `eff = self.claude_state`
lines with a single pull from the engine. The top of `_tick` becomes:

```python
    def _tick(self):
        self.frame += 1
        now = time.monotonic()
        self.claude_state = self.engine.display_state(now)
        eff = self.claude_state

        roaming = eff in ("idle", "sleeping") and self.mode == "roam" and not self.dnd
```

(Leave the rest of `_tick` — thrown/roam/stationary branches — unchanged, but see 3f.)

3f. In `_roam` and `_physics`, any reference to `self.claude_state` for the
render state stays valid. Confirm the stationary branch still does
`self._render_state = eff`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_pet_smoke.py -v`
Expected: PASS. (`focus.terminal_focused()` returns True in the test env, which
is fine — we only assert the work state.)

- [ ] **Step 5: Add the search "dart" movement (small flourish)**

`work_search` should also make the pet physically dart left/right. In `_tick`,
inside the stationary branch (the `else`), before `self._render_state = eff`, add:

```python
            if eff == "work_search":
                # quick random horizontal darts while rummaging
                if self.target_x is None or abs(self.target_x - self.x) < 4:
                    span = self.w * 3
                    self.target_x = min(max(self.x + random.uniform(-span, span),
                                            self.screen_rect.left()),
                                        self.screen_rect.right() - self.w)
                dx = self.target_x - self.x
                self.facing = 1 if dx > 0 else -1
                self.x += max(-6, min(6, dx))     # fast step
```

- [ ] **Step 6: Run the full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: PASS (all tests across every task).

- [ ] **Step 7: Commit**

```bash
git add src/pet.py tests/test_pet_smoke.py
git commit -m "feat: drive pet from state engine + focus-gated celebrate"
```

---

## Task 9: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Install hooks and launch the pet**

Run:
```bash
bin/claude-pet-install-hooks
bin/claude-pet &
```
Expected: pet window appears; no traceback in the terminal.

- [ ] **Step 2: Drive real hook events through the socket**

Simulate the events a real session emits and confirm the creature reacts. Run
each and watch the pet:
```bash
H=bin/claude-pet-hook
echo '{"session_id":"t","tool_name":"Edit"}'   | $H PreToolUse    # laptop typing
echo '{"session_id":"t","tool_name":"Read"}'   | $H PreToolUse    # darts + magnifier
echo '{"session_id":"t","tool_name":"WebFetch"}'| $H PreToolUse   # phone
echo '{"session_id":"t","tool_name":"Task"}'   | $H PreToolUse    # clones
echo '{"session_id":"t","tool_name":"Skill"}'  | $H PreToolUse    # party hat
echo '{"session_id":"t","notification_type":"permission_prompt"}' | $H Notification  # ! jump
echo '{"session_id":"t"}'                        | $H StopFailure  # X_X tip over
echo '{"session_id":"t"}'                        | $H Stop         # idle or celebrate
```
Expected: each command visibly changes the creature to the mapped state; the
`Stop` result is `celebrate` only when the Claude terminal is not the active
window (otherwise calm `idle`).

- [ ] **Step 3: Confirm sleep + real-session reaction**

Leave it idle >60s → confirm it dozes (`zZ`). Then start a real Claude Code
session in Konsole and confirm the creature reacts live (this is the previously
unverified path per TODO.md).

- [ ] **Step 4: Update TODO.md**

Tick off the resolved items in `TODO.md` (hook→state redesign, thinking≠bulb,
celebrate stabilization, error trigger). If live focus detection was NOT
available in Task 7, add a follow-up bullet: "focus detection fallback (KWin
script) — celebrate suppressed until then."

- [ ] **Step 5: Commit**

```bash
git add TODO.md
git commit -m "docs: update TODO after hook->state redesign"
```

---

## Self-Review Notes

- **Spec coverage:** state inventory → Tasks 6/8; hook firing/fields → Task 4; tool→state map + debounce + transients + sleep + priority + lifecycle → Tasks 1–3; StopFailure registration → Task 5; focus-gated celebrate (+ risk/spike + fallback) → Tasks 7/8; renderer rename + new motions → Task 6; deferred items (typed bubbles, auto-run state, GIF, multi-monitor) intentionally omitted.
- **Debounce nuance:** `SubagentStop`/`PostToolUse` are liveness-only (no state change) by design — the work state persists until the next `PreToolUse`/`Stop`, which is what keeps `work_agent` visible for the duration of a subagent.
- **Focus risk is isolated:** the engine defaults `is_focused` such that "unknown" suppresses celebrate; every other behavior is independent of the spike outcome.
