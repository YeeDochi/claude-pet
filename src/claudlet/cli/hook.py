#!/usr/bin/env python3
"""claudlet-hook — per-session bridge between Claude Code and its pet.

Claude Code invokes this for each hook event (event name in argv[1], JSON
payload on stdin). It:
  * on SessionStart, launches a pet for this session if one isn't already
    running (launched from inside the session, so it inherits host app + env);
  * forwards every event to that session's pet over a loopback TCP socket,
    whose port is published in $XDG_RUNTIME_DIR/claudlet-<session_id>.port.

Must never block or fail Claude: every error is swallowed and exit is always 0.
"""
import sys
import os
import json
import socket
import subprocess

# Claude Code always sends the hook payload as UTF-8 JSON on stdin, but on
# non-UTF-8-locale Windows (e.g. Korean cp949), Python's default stdin codec
# follows the console codepage and mangles any multi-byte payload content.
# Wrapped because this is module-top-level code (outside main()'s try): a
# closed/detached stream makes reconfigure raise, and this hook must never
# fail Claude — swallow it and carry on.
try:
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from claudlet.core import hostinfo
except Exception:
    hostinfo = None


def build_message(argv, data):
    """Build the JSON line to send to the pet. Pure; unit-tested."""
    event = (argv[1] if len(argv) > 1 else "") or data.get("hook_event_name", "")
    msg = {"event": event, "session": data.get("session_id") or "default"}
    for key in ("tool_name", "notification_type", "error_type",
                "permission_mode"):
        val = data.get(key)
        if val:
            msg[key] = val
    # Companion lifetime (issue #2): Stop/SubagentStop payloads carry a
    # background_tasks snapshot -- Claude Code's own view of what is still
    # running, i.e. exactly what its UI shows. Forward counts of the RUNNING
    # tasks so the companion is present precisely while the UI shows background
    # work. The stopping agent's OWN entry is excluded: it lists itself as
    # running even at its final SubagentStop, and when that stop is the last
    # hook event of an idle session (a background agent finishing while the
    # user is away) no later snapshot ever arrives to clear it -- counting self
    # left the companion up forever. Excluding self makes the final stop read
    # as an empty snapshot; the engine's depart GRACE (not instant departure)
    # is what keeps the companion trailing the UI instead of leading it.
    bt = data.get("background_tasks")
    if isinstance(bt, list):
        self_id = data.get("agent_id")
        # Only shell/subagent entries are real per-run work; an unknown
        # always-running entry type would otherwise pin bg_tasks above zero and
        # hold the companion up forever.
        running = [b for b in bt if isinstance(b, dict)
                   and b.get("status") == "running" and b.get("id") != self_id
                   and b.get("type") in ("shell", "subagent")]
        msg["bg_tasks"] = len(running)                                  # any bg work
        msg["bg_agents"] = sum(1 for b in running
                               if b.get("type") == "subagent")          # other agents
    return json.dumps(msg) + "\n"


def sock_for(data):
    return hostinfo.read_session_port(data.get("session_id") or "default")


def resolve_claude_pid(start_pid, proc_info, max_hops=32):
    """Walk up the parent chain from start_pid to the Claude Code process.

    Claude runs hooks under a transient shell, so os.getppid() is that
    shell (which exits within ~1s) rather than the long-lived `claude`
    process. If the pet's orphan reaper polled the shell pid it would quit
    ~3s after launch. So climb parents until one whose command name
    contains 'claude', and give the reaper *that* pid.

    proc_info(pid) -> (comm, ppid) or None if the pid is gone. Returns 0
    if no claude ancestor is found (caller then skips the reaper — the pet
    simply won't self-reap, same as a manually launched one).
    """
    pid = start_pid
    seen = set()
    for _ in range(max_hops):
        if pid <= 1 or pid in seen:
            return 0
        seen.add(pid)
        info = proc_info(pid)
        if info is None:
            return 0
        comm, ppid = info
        if "claude" in comm:
            return pid
        pid = ppid
    return 0


_win32_proc_table = None   # lazy, cached per hook invocation (see below)


def _proc_info(pid):
    """(comm, ppid) for a pid, or None if it's gone/undetectable.
    Linux: /proc/<pid>/stat. Windows: one cached Toolhelp snapshot (process
    names/parents don't change mid-lookup, so we only take it once even
    though resolve_claude_pid calls this per hop). macOS: undetectable, so
    the reaper is simply skipped there."""
    if os.name == "nt":
        global _win32_proc_table
        if _win32_proc_table is None:
            try:
                from claudlet.platform.geom import win32
                _win32_proc_table = win32.proc_table()
            except Exception:
                _win32_proc_table = {}
        return _win32_proc_table.get(pid)
    try:
        with open("/proc/%d/stat" % pid) as f:
            data = f.read()
        # format: `pid (comm) state ppid ...`; comm may contain spaces/parens
        rparen = data.rindex(")")
        comm = data[data.index("(") + 1:rparen]
        fields = data[rparen + 2:].split()
        return comm, int(fields[1])   # fields[0]=state, fields[1]=ppid
    except (OSError, ValueError, IndexError):
        return None


def _launch_pet(session_id, host):
    # Give the reaper the real Claude Code pid, not our transient shell parent.
    claude_pid = resolve_claude_pid(os.getppid(), _proc_info)
    # Launch the pet as `python -m claudlet` with THIS interpreter so it works
    # cross-OS; detach so it outlives the hook. start_new_session is POSIX-only.
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
          "stderr": subprocess.DEVNULL}
    if os.name == "posix":
        kw["start_new_session"] = True
    # Make sure the child can import claudlet from a source checkout (pipx
    # installs already have it importable; the extra PYTHONPATH is harmless).
    env = dict(os.environ)
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(hostinfo.__file__)))
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.Popen(
        [sys.executable, "-m", "claudlet", "--session", session_id,
         "--host", host, "--claude-pid", str(claude_pid)], env=env, **kw)


def _send(port, payload):
    if port is None:
        raise OSError("no pet port for this session")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    s.connect((hostinfo.LOOPBACK, port))
    s.sendall(payload)
    s.close()


def main():
    if hostinfo is None:
        return
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

    event = (sys.argv[1] if len(sys.argv) > 1 else "") or data.get("hook_event_name", "")
    session_id = data.get("session_id") or "default"

    # Opt-in companion-lifetime diagnostic (CLAUDLET_DEBUG_BG=1), same spirit as
    # CLAUDLET_DEBUG_GEOM: append each Stop/SubagentStop's raw background_tasks
    # to <tmp>/claudlet-bgdebug.jsonl so "the companion won't leave" can be
    # diagnosed from what Claude Code actually reported on that machine,
    # instead of guessed at. Never raises (hooks must not fail Claude).
    if os.environ.get("CLAUDLET_DEBUG_BG") and event in ("Stop", "SubagentStop",
                                                         "StopFailure"):
        try:
            import time as _time
            import tempfile as _tempfile
            with open(os.path.join(_tempfile.gettempdir(),
                                   "claudlet-bgdebug.jsonl"), "a") as f:
                f.write(json.dumps({
                    "t": _time.time(), "event": event,
                    "agent_id": data.get("agent_id"),
                    "background_tasks": data.get("background_tasks"),
                }) + "\n")
        except Exception:
            pass

    # on session start, bring up this session's pet if one isn't already there
    # (verified by handshake, so a stale port file can't suppress the launch)
    launched_fresh = False
    if event == "SessionStart":
        try:
            # capture BEFORE pet_alive(), which unlinks the file on a refused
            # connect. Only a brand-new session (never had a port file) is safe
            # to skip sending to: there's provably nothing to send to yet. If a
            # port file DID exist, pet_alive()'s False can also mean "our own
            # pet, alive, just slow to answer the ping" (busy Qt event loop) —
            # not necessarily dead — so still attempt the send below rather than
            # dropping this event on a timing coincidence.
            had_port = hostinfo.read_session_port(session_id) is not None
            if not hostinfo.pet_alive(session_id):
                _launch_pet(session_id, hostinfo.detect_host())
                launched_fresh = not had_port
        except Exception:
            pass

    if not launched_fresh:
        try:
            _send(hostinfo.read_session_port(session_id),
                  build_message(sys.argv, data).encode())
        except Exception:
            pass  # pet not running / not ready — ignore silently


def _cli():
    """console-script entry point — hooks must always succeed (exit 0)."""
    try:
        main()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    _cli()
