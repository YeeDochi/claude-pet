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
# permission_mode values (present on every hook payload) that mean Claude is
# grinding on its own without stopping to ask. "plan" is excluded: it's read-only
# planning, not autonomous execution.
AUTO_MODES = {"auto", "bypassPermissions"}

# Under an auto mode the pet puts its visor on and wanders while it works: each
# work type keeps its own flavour (prop/animation) but visor-clad. Maps the plain
# work state -> its autonomous "auto_*" variant. Anything without a variant falls
# back to the generic `autopilot` cruise.
AUTO_VARIANT = {
    "work_computer": "auto_computer",
    "work_search": "auto_search",
    "work_web": "auto_web",
    "work_agent": "auto_agent",
    "work_skill": "auto_skill",
}
AUTO_STATES = {"autopilot", *AUTO_VARIANT.values()}

WORK_STATES = {"work_computer", "work_search", "work_web",
               "work_agent", "work_skill"} | AUTO_STATES

# the direct single-state events, keyed by short name -> default state. Users can
# override any of these via config (see petconfig.py).
DEFAULT_EVENT_STATES = {
    "start": "idle",            # SessionStart
    "prompt": "thinking",       # UserPromptSubmit
    "done": "idle",             # Stop, terminal focused
    "celebrate": "celebrate",   # Stop, terminal NOT focused (away)
    "error": "error",           # StopFailure
    "permission": "attention",  # Notification / permission_prompt
    "idle_prompt": "sleeping",  # Notification / idle_prompt
    "autopilot": "autopilot",   # PreToolUse while permission_mode is autonomous
}

# states a user is allowed to map a tool/event to (expressive display states;
# excludes internal/mode-only ones like walk/held/falling/float). Kept as a plain
# set so this module stays Qt-free — mirror of the renderable creature states.
MAPPABLE_STATES = {
    "idle", "sleeping", "thinking", "attention", "error", "celebrate",
    "work_computer", "work_search", "work_web", "work_agent", "work_skill",
    "autopilot", "jump", "wave", "sing", "juggle",
}

PRIORITY = {
    "attention": 6, "error": 5,
    "work_computer": 4, "work_search": 4, "work_web": 4,
    "work_agent": 4, "work_skill": 4,
    "thinking": 3, "celebrate": 2, "idle": 1, "sleeping": 0,
}
for _st in AUTO_STATES:                 # auto variants show at work-level priority
    PRIORITY[_st] = 4

DEBOUNCE = 0.8
SLEEP_TIMEOUT = 60.0
CELEBRATE_DUR = 1.6
ERROR_DUR = 2.0
WORK_TIMEOUT = 120.0   # work_*/thinking with no events this long -> assume the
                       # turn ended without a Stop (e.g. user interrupt) -> idle


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
    def __init__(self, is_focused=None, tool_states=None, event_states=None,
                 raw_events=None):
        self.sessions = {}
        self.is_focused = is_focused or (lambda: True)
        # merge user overrides over the defaults (see petconfig.load_config)
        self._tools = dict(TOOL_STATES)
        self._tools.update(tool_states or {})
        self._events = dict(DEFAULT_EVENT_STATES)
        self._events.update(event_states or {})
        # raw hook-event-name -> state, for events without a dedicated slot
        # (PostToolUse, SubagentStop, PreCompact, future events...)
        self._raw = dict(raw_events or {})
        # custom targets behave like work states (debounce + liveness decay)
        self._work_like = (set(WORK_STATES) | set(self._tools.values())
                           | set(self._raw.values()))
        # custom target states show at work-level priority unless already ranked
        self._priority = dict(PRIORITY)
        for st in (set(self._tools.values()) | set(self._events.values())
                   | set(self._raw.values())):
            self._priority.setdefault(st, 4)

    def _tool_state(self, tool_name):
        if tool_name in self._tools:
            return self._tools[tool_name]
        if tool_name and tool_name.startswith("mcp__"):
            return "work_web"
        return self._tools.get("*", "work_computer")   # "*" = generic fallback

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
            s.set_state(self._events["start"], now)
        elif name == "UserPromptSubmit":
            s.set_state(self._events["prompt"], now)
        elif name == "PreToolUse":
            st = self._tool_state(ev.get("tool_name", ""))
            if ev.get("permission_mode") in AUTO_MODES:
                # visor on, wandering while it works: each work type keeps its own
                # flavour as an auto_* variant; anything else -> generic autopilot.
                st = AUTO_VARIANT.get(st, self._events["autopilot"])
            self._set_work(s, st, now)
        elif name == "Notification":
            nt = ev.get("notification_type", "")
            if nt == "permission_prompt":
                s.set_state(self._events["permission"], now)
            elif nt == "idle_prompt":
                s.set_state(self._events["idle_prompt"], now)
        elif name == "Stop":
            if self.is_focused():
                s.set_state(self._events["done"], now)
            else:
                s.set_state(self._events["celebrate"], now)
                s.expiry = now + CELEBRATE_DUR
        elif name == "StopFailure":
            s.set_state(self._events["error"], now)
            s.expiry = now + ERROR_DUR
        elif name in self._raw:
            # any other event the user mapped by raw name (PostToolUse, etc.)
            s.set_state(self._raw[name], now)
        # otherwise (PostToolUse/SubagentStop/… unmapped): liveness refresh only

    def _set_work(self, s, work_state, now):
        # Guarantee the current work motion shows >= DEBOUNCE before switching
        # to a *different* work motion; remember the latest as pending.
        if s.state in self._work_like and (now - s.since) < DEBOUNCE:
            if work_state != s.state:
                s.pending = work_state
            return
        s.set_state(work_state, now)

    def _age(self, s, now):
        # promote a deferred work state once the current one has held long enough
        if s.pending and s.state in self._work_like and (now - s.since) >= DEBOUNCE:
            s.set_state(s.pending, now)
        # transient states (celebrate/error) decay back to calm idle
        if s.expiry is not None and now >= s.expiry:
            s.set_state("idle", now)
        # work/thinking gone quiet for a long time: no Stop ever came (e.g. the
        # user interrupted with ESC), so fall back to calm idle.
        if (s.state in self._work_like or s.state == "thinking") and \
           (now - s.last_event) >= WORK_TIMEOUT:
            s.set_state("idle", now)
        # calm idle falls asleep after a long quiet spell
        if s.state == "idle" and (now - s.last_event) >= SLEEP_TIMEOUT:
            s.state = "sleeping"

    def display_state(self, now):
        for s in self.sessions.values():
            self._age(s, now)
        if not self.sessions:
            return "sleeping"
        return max((s.state for s in self.sessions.values()),
                   key=lambda st: self._priority.get(st, 0))
