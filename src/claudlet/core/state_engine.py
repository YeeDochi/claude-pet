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
    # NOTE: subagent dispatch (tool_name "Agent"/"Task", see AGENT_TOOLS) is NOT
    # mapped to a main state — it's represented by the follower companion only,
    # so the main creature keeps showing the parent's own activity meanwhile.
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

# of those, the ones that WANDER the screen while working — "looking things up"
# reads as roaming; coding/agent/skill stay put and focus. (pet.py roam gating)
AUTO_ROAM = {"auto_web", "auto_search"}

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
    "asking": "asking",         # PreToolUse / AskUserQuestion or ExitPlanMode
    "autopilot": "autopilot",   # PreToolUse while permission_mode is autonomous
}

# tools that mean "Claude is waiting on the user to answer" rather than working:
# a question (AskUserQuestion) or a plan awaiting approval (ExitPlanMode). They
# arrive as PreToolUse and map to the calm, expectant `asking` state — finer than
# the `attention` alert used for permission prompts.
ASK_TOOLS = {"AskUserQuestion", "ExitPlanMode"}

# tools that DISPATCH a subagent. PreToolUse with one of these opens an
# "agent working" window that stays open until a matching SubagentStop, tracked
# as a per-session counter (see StateEngine.agents_active) so a companion can
# show beside the creature for the whole run — independent of the main display
# state, which follows the parent's own tool use meanwhile (background agents).
AGENT_TOOLS = {"Agent", "Task"}

# states a user is allowed to map a tool/event to (expressive display states;
# excludes internal/mode-only ones like walk/held/falling/float). Kept as a plain
# set so this module stays Qt-free — mirror of the renderable creature states.
MAPPABLE_STATES = {
    "idle", "sleeping", "thinking", "attention", "asking", "error", "celebrate",
    "work_computer", "work_search", "work_web", "work_agent", "work_skill",
    "autopilot", "jump", "wave", "sing", "juggle",
}

PRIORITY = {
    "asking": 7, "attention": 6, "error": 5,
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
COMPANION_DEPART_GRACE = 3.0   # linger this long after the background_tasks
                               # snapshot empties before departing -- so the
                               # companion trails Claude Code's UI instead of
                               # vanishing a beat before the bottom line clears
WORK_TIMEOUT = 120.0   # work_*/thinking with no events this long -> assume the
                       # turn ended without a Stop (e.g. user interrupt) -> idle


def tool_to_state(tool_name):
    if tool_name in TOOL_STATES:
        return TOOL_STATES[tool_name]
    if tool_name and tool_name.startswith("mcp__"):
        return "work_web"
    return "work_computer"


class _Session:
    __slots__ = ("state", "since", "expiry", "last_event", "pending", "agents",
                 "agent_state", "agent_gone_since")

    def __init__(self, now):
        self.state = "idle"
        self.since = now
        self.expiry = None     # end ts for transient states (celebrate/error)
        self.last_event = now
        self.pending = None    # deferred work state (debounce)
        self.agents = 0        # open subagent windows (PreToolUse Agent .. SubagentStop)
        self.agent_state = None  # subagent's current activity, for the companion
        self.agent_gone_since = None  # ts the snapshot emptied (depart-grace timer)

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
        self._last_pm = None        # last-seen permission_mode (drives auto_active)
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
        if "permission_mode" in ev:          # every hook carries it; remember it
            self._last_pm = ev.get("permission_mode")
        if name == "SessionEnd":
            self.sessions.pop(sid, None)
            if not self.sessions:
                self._last_pm = None          # nobody left -> drop auto mode
            return
        s = self.sessions.get(sid)
        if s is None:
            s = self.sessions[sid] = _Session(now)
        s.last_event = now

        if name == "SessionStart":
            s.agents = 0                       # fresh session -> no open agents
            s.agent_state = None
            s.agent_gone_since = None
            s.set_state(self._events["start"], now)
        elif name == "UserPromptSubmit":
            # NOTE: deliberately does NOT reset s.agents — BACKGROUND subagents
            # outlive turn boundaries (the user chats while they run), and their
            # SubagentStop arrives whenever they actually finish.
            s.set_state(self._events["prompt"], now)
        elif name == "PreToolUse":
            tool = ev.get("tool_name", "")
            if tool in AGENT_TOOLS:
                # opens an agent-working window (closed when the background_tasks
                # snapshot no longer lists running work). Shown by the follower
                # companion; the main creature is left as-is. NOTE: the
                # companion's state is deliberately NOT driven by this session's
                # other tool events — subagent tools are isolated from parent
                # hooks (verified live), so those events are the PARENT's own
                # work; mirroring them just made the companion copy the main
                # creature. It shows its own life instead: thinking while
                # active, idle while waiting on background work.
                s.agents += 1
                s.agent_gone_since = None        # a fresh dispatch is active work
                if not s.agent_state:
                    s.agent_state = "thinking"   # agent spinning up
            elif tool in ASK_TOOLS:
                s.set_state(self._events["asking"], now)   # waiting on the user
            else:
                st = self._tool_state(tool)
                if ev.get("permission_mode") in AUTO_MODES:
                    # visor on, wandering while it works: each work type keeps its
                    # own flavour as an auto_* variant; else -> generic autopilot.
                    st = AUTO_VARIANT.get(st, self._events["autopilot"])
                self._set_work(s, st, now)
        elif name == "Notification":
            nt = ev.get("notification_type", "")
            if nt == "permission_prompt":
                s.set_state(self._events["permission"], now)
            elif nt == "idle_prompt":
                s.set_state(self._events["idle_prompt"], now)
        elif name == "SubagentStop":
            if not self._reconcile_agents(s, ev, now):
                s.agents = max(0, s.agents - 1)    # legacy: one subagent finished
                if s.agents == 0:
                    s.agent_state = None
        elif name == "Stop":
            # The MAIN turn ended, but background subagents keep running past it.
            # When the payload carries a background_tasks snapshot, reconcile the
            # companion count to it (this also self-heals a stuck count from a
            # lost SubagentStop). Without it, leave s.agents alone — killing it
            # here would drop live companions.
            self._reconcile_agents(s, ev, now)
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

    def _reconcile_agents(self, s, ev, now):
        """Set the companion count from Claude Code's background_tasks snapshot,
        forwarded (see hook.build_message) as:
          bg_agents  count of RUNNING subagent-type tasks
          bg_tasks   count of ALL running background tasks

        Returns False when the event carried no snapshot (older Claude Code),
        so the caller falls back to legacy -1 arithmetic.

        The point (issue #2): a subagent that launches its own background work
        and yields fires a SubagentStop while its work runs on — blindly
        decrementing there drops the companion mid-work. Instead we mirror the
        snapshot (Claude Code's own bottom-UI indicator): keep one idle
        companion while any background task is still running — however long that
        takes (issue #3 measured the UI holding its line until the work actually
        finished, disproving an earlier 30s-idle-drop assumption) — and depart
        only when the snapshot empties. The `s.agents > 0` guard means a plain
        background shell (no subagent ever dispatched) never conjures a
        companion from nothing."""
        bg_agents = ev.get("bg_agents")
        if bg_agents is None:
            return False
        bg_tasks = ev.get("bg_tasks") or 0
        if bg_agents > 0:
            s.agents = bg_agents               # active subagents, counted exactly
            if not s.agent_state:
                s.agent_state = "thinking"
            s.agent_gone_since = None          # active -> cancel pending departure
        elif bg_tasks > 0 and s.agents > 0:
            s.agents = 1                        # yielded; background work runs on
            s.agent_state = "idle"             # companion waits idle beside the pet
            s.agent_gone_since = None          # work is still listed -> not gone
        elif s.agents > 0:
            # snapshot emptied: don't vanish on the spot -- the very next hook
            # event can land a beat BEFORE Claude Code's bottom line clears, and
            # leading the UI reads as "it died mid-work". Linger idle for
            # COMPANION_DEPART_GRACE (see _age), trailing the UI instead.
            s.agents = 1
            s.agent_state = "idle"
            if s.agent_gone_since is None:
                s.agent_gone_since = now
        else:
            s.agent_state = None
            s.agent_gone_since = None
        return True

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
        if (s.state in self._work_like or s.state in ("thinking", "asking")) and \
           (now - s.last_event) >= WORK_TIMEOUT:
            s.set_state("idle", now)
        # calm idle falls asleep after a long quiet spell
        if s.state == "idle" and (now - s.last_event) >= SLEEP_TIMEOUT:
            s.state = "sleeping"
        # snapshot emptied a moment ago: depart once the linger grace has passed
        # (trail Claude Code's UI rather than lead it). NOTE: there is no fixed
        # idle timeout here — issue #3 measured Claude Code's UI keeping its
        # agent line up until the background work actually finishes, so an idle
        # companion waits as long as the work does.
        if s.agent_gone_since is not None and s.agents > 0 and \
           (now - s.agent_gone_since) >= COMPANION_DEPART_GRACE:
            s.agents = 0
            s.agent_state = None
            s.agent_gone_since = None

    def display_state(self, now):
        for s in self.sessions.values():
            self._age(s, now)
        if not self.sessions:
            return "sleeping"
        return max((s.state for s in self.sessions.values()),
                   key=lambda st: self._priority.get(st, 0))

    def agents_active(self):
        """Total open subagent windows across all sessions (0 = none). Drives a
        persistent 'agent working' companion beside the creature — independent of
        display_state, so it stays up while the main creature shows other work."""
        return sum(s.agents for s in self.sessions.values())

    def agent_state(self):
        """The running subagent's current activity (a work_* state, or 'thinking'
        while it spins up), for the companion to mirror; None if no agent runs."""
        for s in self.sessions.values():
            if s.agents > 0 and s.agent_state:
                return s.agent_state
        return None

    def auto_active(self):
        """True while the session is in an autonomous permission mode — the pet
        keeps its visor on (worn while working, pushed up otherwise) throughout."""
        return self._last_pm in AUTO_MODES
