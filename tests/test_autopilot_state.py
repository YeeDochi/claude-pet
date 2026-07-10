import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from state_engine import StateEngine


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


def test_auto_agent_variant():
    e = StateEngine()
    e.handle(_pre("Task", pm="auto"), 0.0)
    assert e.display_state(0.0) == "auto_agent"


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
