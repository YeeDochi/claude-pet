"""User config for claude-pet: remap which creature motion shows for which
Claude Code activity.

File (JSON, all keys optional), at ``$XDG_CONFIG_HOME/claude-pet/config.json``
(default ``~/.config/claude-pet/config.json``)::

    {
      "tools":  { "Bash": "work_search", "Grep": "sing", "*": "work_computer" },
      "events": { "prompt": "jam", "celebrate": "juggle" }
    }

- ``tools``  — tool name -> state. ``"*"`` is the fallback for unmapped tools;
  ``mcp__*`` tools default to ``work_web`` unless named explicitly.
- ``events`` — event slot -> state. Slots: start, prompt, done, celebrate,
  error, permission, idle_prompt (see state_engine.DEFAULT_EVENT_STATES).

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
    return {"tool_states": tools, "event_states": events}


def load_config(path=None):
    """Read + validate the config file. Never raises: a missing/broken file
    yields empty overrides (built-in defaults apply)."""
    path = path or config_path()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {"tool_states": {}, "event_states": {}}
    if not isinstance(raw, dict):
        return {"tool_states": {}, "event_states": {}}
    return _clean(raw)
