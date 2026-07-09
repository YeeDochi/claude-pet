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
        # Guarantee the current work motion shows >= DEBOUNCE before switching
        # to a *different* work motion; remember the latest as pending.
        if s.state in WORK_STATES and (now - s.since) < DEBOUNCE:
            if work_state != s.state:
                s.pending = work_state
            return
        s.set_state(work_state, now)

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

    def display_state(self, now):
        for s in self.sessions.values():
            self._age(s, now)
        if not self.sessions:
            return "sleeping"
        return max((s.state for s in self.sessions.values()),
                   key=lambda st: PRIORITY.get(st, 0))
