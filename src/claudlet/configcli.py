#!/usr/bin/env python3
"""claudlet-config — locate, inspect, scaffold, and open the user config.

Usage:
    claudlet-config            # show path, status, effective values, ignored entries
    claudlet-config --path     # print the absolute config path only
    claudlet-config init       # create a starter template if none exists
    claudlet-config open       # open the config in the OS default editor

Thin presentation/scaffold layer over petconfig — all path/schema/validation
logic lives there. The /claudlet skill documents the schema so Claude can edit
the JSON directly and re-run this command to validate.
"""
import json
import os
import sys

from claudlet.core import petconfig
from claudlet.core.state_engine import MAPPABLE_STATES, DEFAULT_EVENT_STATES


def diagnose(raw):
    """Split a parsed config dict into what load_config accepts vs silently
    drops. Pure. Returns {"accepted": <petconfig._clean result>, "ignored":
    [human-readable strings]} so a typo'd state or unknown slot is visible
    instead of degrading to defaults with no feedback."""
    accepted = petconfig._clean(raw)
    ignored = []

    for key, val in (raw.get("tools") or {}).items():
        if not (isinstance(key, str) and val in MAPPABLE_STATES):
            ignored.append("tools.%s=%r (not a valid state)" % (key, val))
    for key, val in (raw.get("events") or {}).items():
        if key not in DEFAULT_EVENT_STATES:
            ignored.append("events.%s=%r (unknown event slot)" % (key, val))
        elif val not in MAPPABLE_STATES:
            ignored.append("events.%s=%r (not a valid state)" % (key, val))
    for key, val in (raw.get("raw_events") or {}).items():
        if not (isinstance(key, str) and val in MAPPABLE_STATES):
            ignored.append("raw_events.%s=%r (not a valid state)" % (key, val))
    if "lang" in raw and raw.get("lang") not in ("ko", "en", "auto"):
        ignored.append("lang=%r (use ko | en | auto)" % (raw.get("lang"),))

    return {"accepted": accepted, "ignored": ignored}


_DEFAULTS = {"tool_states": {}, "event_states": {}, "raw_events": {},
             "lang": "auto"}


def build_report(path=None):
    """Inspect the config file at `path` (default: the resolved config_path).
    Returns {"path", "status": found|missing|invalid, "error"?, "accepted",
    "ignored"}. Never raises."""
    path = os.path.abspath(path or petconfig.config_path())
    if not os.path.exists(path):
        return {"path": path, "status": "missing",
                "accepted": dict(_DEFAULTS), "ignored": []}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        return {"path": path, "status": "invalid", "error": str(e),
                "accepted": dict(_DEFAULTS), "ignored": []}
    if not isinstance(raw, dict):
        return {"path": path, "status": "invalid",
                "error": "top-level JSON must be an object",
                "accepted": dict(_DEFAULTS), "ignored": []}
    d = diagnose(raw)
    return {"path": path, "status": "found",
            "accepted": d["accepted"], "ignored": d["ignored"]}


# A valid, minimal starting point (per-key guidance lives in `show`, the skill
# doc, and docs/configuration.md — JSON has no comments).
TEMPLATE = {
    "lang": "auto",
    "tools": {"Bash": "work_computer"},
    "events": {},
    "raw_events": {},
}


def init_config(path=None):
    """Create a starter template at `path` if it doesn't exist. Returns True if
    a file was created, False if one was already there (never clobbers)."""
    path = os.path.abspath(path or petconfig.config_path())
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(TEMPLATE, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return True


def _open_command(path, platform=None, name=None):
    """How to open `path`: an argv list for a subprocess, or the string
    "startfile" meaning use os.startfile (Windows). Pure."""
    platform = sys.platform if platform is None else platform
    name = os.name if name is None else name
    if name == "nt":
        return "startfile"
    if platform == "darwin":
        return ["open", path]
    return ["xdg-open", path]


def _launch(path):
    cmd = _open_command(path)
    if cmd == "startfile":
        os.startfile(path)                      # noqa: Windows only
    else:
        import subprocess
        subprocess.Popen(cmd)


def open_config(path=None):
    """Scaffold the config if missing, then open it in the OS default editor.
    Best-effort (never raises); returns the absolute path so the caller can
    print it as a fallback."""
    path = os.path.abspath(path or petconfig.config_path())
    init_config(path)
    try:
        _launch(path)
    except Exception:
        pass
    return path


def render(r):
    """Human-readable text for a build_report() result."""
    acc = r["accepted"]
    status = r["status"]
    if status == "invalid":
        status += " (%s)" % r.get("error", "")
    elif status == "missing":
        status += " (built-in defaults apply)"
    lines = [
        "config: " + r["path"],
        "status: " + status,
        "lang:   " + acc["lang"],
        "tools:      " + json.dumps(acc["tool_states"], ensure_ascii=False),
        "events:     " + json.dumps(acc["event_states"], ensure_ascii=False),
        "raw_events: " + json.dumps(acc["raw_events"], ensure_ascii=False),
    ]
    if r["ignored"]:
        lines.append("ignored (present in the file but dropped — fix these):")
        lines += ["  - " + s for s in r["ignored"]]
    lines += [
        "---",
        "valid states: " + ", ".join(sorted(MAPPABLE_STATES)),
        "event slots:  " + ", ".join(DEFAULT_EVENT_STATES),
        "edit the file (or ask Claude via /claudlet config), then restart the pet.",
    ]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    arg = argv[0] if argv else ""

    if arg == "--path":
        print(os.path.abspath(petconfig.config_path()))
        return 0
    if arg == "init":
        path = os.path.abspath(petconfig.config_path())
        created = init_config(path)
        print(("created " if created else "already exists: ") + path)
        return 0
    if arg == "open":
        print("opening " + open_config())
        return 0
    print(render(build_report()))
    return 0


def _cli():
    """console-script entry point (never raise from the CLI)."""
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    _cli()
