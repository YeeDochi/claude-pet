"""User config for claude-pet: remap which creature motion shows for which
Claude Code activity.

File (JSON, all keys optional), at ``$XDG_CONFIG_HOME/claude-pet/config.json``
(default ``~/.config/claude-pet/config.json``)::

    {
      "tools":      { "Bash": "work_search", "Grep": "sing", "*": "work_computer" },
      "events":     { "prompt": "thinking", "celebrate": "juggle" },
      "raw_events": { "PostToolUse": "celebrate", "SubagentStop": "wave" }
    }

- ``tools``  — tool name -> state. ``"*"`` is the fallback for unmapped tools;
  ``mcp__*`` tools default to ``work_web`` unless named explicitly.
- ``events`` — event slot -> state. Slots: start, prompt, done, celebrate,
  error, permission, idle_prompt (see state_engine.DEFAULT_EVENT_STATES).
- ``raw_events`` — raw hook event name -> state, for any event the engine does
  not already handle via a slot (PostToolUse, SubagentStop, PreCompact, and any
  future event). Knowing the event name the hook pushes is enough to map it.

Values must be one of state_engine.MAPPABLE_STATES; anything else (or a bad
file) is ignored, so a typo degrades to the built-in defaults rather than
breaking the pet. Pure except for the single file read in load_config.
"""
import os
import json

from state_engine import MAPPABLE_STATES, DEFAULT_EVENT_STATES


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "claude-pet", "config.json")


def _clean(raw):
    """Validate a parsed config dict -> {tool_states, event_states}. Pure."""
    tools = {}
    for key, val in (raw.get("tools") or {}).items():
        if isinstance(key, str) and val in MAPPABLE_STATES:
            tools[key] = val
    events = {}
    for key, val in (raw.get("events") or {}).items():
        if key in DEFAULT_EVENT_STATES and val in MAPPABLE_STATES:
            events[key] = val
    raw_events = {}
    for key, val in (raw.get("raw_events") or {}).items():
        if isinstance(key, str) and val in MAPPABLE_STATES:
            raw_events[key] = val
    return {"tool_states": tools, "event_states": events, "raw_events": raw_events}


def load_config(path=None):
    """Read + validate the config file. Never raises: a missing/broken file
    yields empty overrides (built-in defaults apply)."""
    path = path or config_path()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {"tool_states": {}, "event_states": {}, "raw_events": {}}
    if not isinstance(raw, dict):
        return {"tool_states": {}, "event_states": {}, "raw_events": {}}
    return _clean(raw)
