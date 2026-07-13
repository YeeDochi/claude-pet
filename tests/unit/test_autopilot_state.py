from claudlet.core.state_engine import StateEngine


def _pre(tool, pm=None):
    ev = {"event": "PreToolUse", "session": "a", "tool_name": tool}
    if pm is not None:
        ev["permission_mode"] = pm
    return ev


# --- auto mode: each work type gets its own visor-clad variant ---

def test_auto_computer_variant():
    e = StateEngine()
    e.handle(_pre("Edit", pm="auto"), 0.0)
    assert e.display_state(0.0) == "auto_computer"


def test_auto_search_variant():
    e = StateEngine()
    e.handle(_pre("Read", pm="auto"), 0.0)
    assert e.display_state(0.0) == "auto_search"


def test_auto_web_variant():
    e = StateEngine()
    e.handle(_pre("WebFetch", pm="bypassPermissions"), 0.0)
    assert e.display_state(0.0) == "auto_web"


def test_agent_dispatch_is_companion_only_even_in_auto():
    # subagent dispatch is represented by the follower companion, not a main
    # state — so even in auto mode it does NOT become auto_agent; the main
    # creature is left as-is (idle here) and only the agent counter opens.
    e = StateEngine()
    e.handle(_pre("Task", pm="auto"), 0.0)
    assert e.display_state(0.0) == "idle"
    assert e.agents_active() == 1


def test_auto_skill_variant():
    e = StateEngine()
    e.handle(_pre("Skill", pm="auto"), 0.0)
    assert e.display_state(0.0) == "auto_skill"


def test_mcp_tool_in_auto_is_web_variant():
    e = StateEngine()
    e.handle(_pre("mcp__gitlab__get_project", pm="auto"), 0.0)
    assert e.display_state(0.0) == "auto_web"


# --- non-auto modes behave exactly as before (no regression) ---

def test_default_mode_shows_normal_work():
    e = StateEngine()
    e.handle(_pre("Edit", pm="default"), 0.0)
    assert e.display_state(0.0) == "work_computer"


def test_missing_permission_mode_is_normal_work():
    e = StateEngine()
    e.handle(_pre("Read"), 0.0)
    assert e.display_state(0.0) == "work_search"


def test_plan_mode_is_not_auto_variant():
    e = StateEngine()
    e.handle(_pre("Read", pm="plan"), 0.0)
    assert e.display_state(0.0) == "work_search"


# --- fallbacks & lifecycle ---

def test_custom_mapped_tool_in_auto_falls_back_to_autopilot():
    # a tool the user remapped to a non-work state has no variant -> generic cruise
    e = StateEngine(tool_states={"Grep": "sing"})
    e.handle(_pre("Grep", pm="auto"), 0.0)
    assert e.display_state(0.0) == "autopilot"


def test_auto_variant_decays_when_quiet():
    e = StateEngine()
    e.handle(_pre("Edit", pm="auto"), 0.0)
    assert e.display_state(1.0) == "auto_computer"
    assert e.display_state(1000.0) in ("idle", "sleeping")


# --- auto_active(): visor persists across states while in an auto mode ---

def test_auto_active_true_in_auto_mode():
    e = StateEngine()
    e.handle(_pre("Edit", pm="auto"), 0.0)
    assert e.auto_active() is True


def test_auto_active_false_in_default_mode():
    e = StateEngine()
    e.handle(_pre("Edit", pm="default"), 0.0)
    assert e.auto_active() is False


def test_auto_active_persists_through_events_without_pm():
    # an idle/Stop tick may omit pm; the remembered mode carries the visor over
    e = StateEngine()
    e.handle(_pre("Edit", pm="auto"), 0.0)
    e.handle({"event": "Stop", "session": "a"}, 1.0)   # no permission_mode
    assert e.auto_active() is True


def test_auto_active_cleared_on_session_end():
    e = StateEngine()
    e.handle(_pre("Edit", pm="auto"), 0.0)
    e.handle({"event": "SessionEnd", "session": "a"}, 1.0)
    assert e.auto_active() is False
