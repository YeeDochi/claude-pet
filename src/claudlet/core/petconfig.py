"""User config for claudlet: remap which creature motion shows for which
Claude Code activity.

File (JSON, all keys optional), at ``$XDG_CONFIG_HOME/claudlet/config.json``
(default ``~/.config/claudlet/config.json``)::

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

from claudlet.core.state_engine import MAPPABLE_STATES, DEFAULT_EVENT_STATES


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "claudlet", "config.json")


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
    lang = raw.get("lang")
    if lang not in ("ko", "en", "auto"):
        lang = "auto"

    def _rect(v):
        if not isinstance(v, dict):
            return None
        try:
            x, y, w, h = float(v["x"]), float(v["y"]), float(v["w"]), float(v["h"])
        except (KeyError, TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        return {"x": x, "y": y, "w": w, "h": h}

    roam_area = _rect(raw.get("roam_area"))
    if not isinstance(raw.get("no_go"), list):
        no_go = []
    else:
        no_go = [r for r in (_rect(z) for z in raw.get("no_go")) if r]

    return {"tool_states": tools, "event_states": events,
            "raw_events": raw_events, "lang": lang,
            "roam_area": roam_area, "no_go": no_go}


def _windows_locale():
    """User's UI locale (e.g. "ko-KR") via Win32 — Windows doesn't set the
    POSIX LANG/LC_* vars resolve_lang() otherwise reads, so without this,
    "auto" would default to English on every Windows machine regardless of
    the system's actual language. Delegates to geom/win32.py (the one module
    that owns the guarded, typed ctypes handles) rather than re-opening windll."""
    try:
        from claudlet.platform.geom import win32
        return win32.user_locale()
    except Exception:
        return ""


def resolve_lang(value):
    """Map a config lang to a concrete "ko"/"en". "auto" (or anything odd) reads
    the locale: Korean locale -> ko, otherwise en."""
    if value in ("ko", "en"):
        return value
    loc = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
           or os.environ.get("LANG") or "")
    if not loc and os.name == "nt":
        loc = _windows_locale()
    return "ko" if loc.lower().startswith("ko") else "en"


def load_config(path=None):
    """Read + validate the config file. Never raises: a missing/broken file
    yields empty overrides (built-in defaults apply)."""
    path = path or config_path()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {"tool_states": {}, "event_states": {}, "raw_events": {},
                "lang": "auto", "roam_area": None, "no_go": []}
    if not isinstance(raw, dict):
        return {"tool_states": {}, "event_states": {}, "raw_events": {},
                "lang": "auto", "roam_area": None, "no_go": []}
    return _clean(raw)
