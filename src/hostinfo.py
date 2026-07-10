"""Shared helpers: detect the Claude Code host app, and per-session socket paths.

Pure and dependency-free so both `bin/claude-pet-hook` (runs inside the Claude
Code session, sees its env) and `src/pet.py` can import it and agree.
"""
import os
import socket
import tempfile

LOOPBACK = "127.0.0.1"

# Liveness handshake: a client sends PING and a real pet answers with a line
# containing BANNER_MARK. A bare TCP connect can't tell our pet apart from an
# unrelated process that the OS happened to hand the same (stale) port number,
# so every liveness check goes through this round-trip instead. Same on every
# OS — the whole project speaks one loopback-TCP protocol.
PING = b'{"cmd": "ping"}\n'
BANNER_MARK = "claude-pet"

# host -> window-class / app-name substrings used to match/focus that host's
# window. On Linux these match KWin resourceClass; on macOS the frontmost app
# name (from AppleScript) is matched against the same substrings.
HOST_CLASSES = {
    "vscode": ["code"],
    "jetbrains": ["jetbrains"],
    "konsole": ["konsole"],
    "apple_terminal": ["terminal"],
    "iterm": ["iterm"],
    "unknown": [],
}

# host -> macOS application name, for `osascript ... to activate` (click-to-focus).
# None where we can't name it reliably (varies per JetBrains IDE).
MAC_APP = {
    "vscode": "Visual Studio Code",
    "apple_terminal": "Terminal",
    "iterm": "iTerm",
}


def detect_host(env=None):
    """Best-effort identify the terminal/IDE hosting Claude Code, from env vars."""
    env = os.environ if env is None else env
    if env.get("TERM_PROGRAM") == "vscode" or env.get("VSCODE_PID"):
        return "vscode"
    if "jetbrains" in (env.get("TERMINAL_EMULATOR", "").lower()):
        return "jetbrains"
    if env.get("KONSOLE_VERSION"):
        return "konsole"
    tp = env.get("TERM_PROGRAM", "")
    if tp == "Apple_Terminal":
        return "apple_terminal"
    if tp == "iTerm.app":
        return "iterm"
    return "unknown"


def host_classes(host):
    """Window-class / app-name substrings for a host (empty list if unknown)."""
    return HOST_CLASSES.get(host, [])


def mac_app(host):
    """macOS application name to activate for a host, or None if unknown."""
    return MAC_APP.get(host)


def runtime_dir():
    """Base dir for per-session port files: $XDG_RUNTIME_DIR, else the OS temp dir.

    AF_UNIX sockets aren't available on stock Windows Python builds, so pets
    listen on a loopback TCP port instead and drop the assigned port in a
    small file here for hook/motion scripts to read.
    """
    return os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()


def session_port_file(session_id):
    """Path to the file holding the loopback TCP port for a session's pet."""
    sid = session_id or "default"
    return os.path.join(runtime_dir(), "claude-pet-{}.port".format(sid))


def read_port_file(path):
    """Port int from a .port file, or None if it's missing/empty/malformed."""
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def read_session_port(session_id):
    """Port of the pet attached to this session, or None if unknown/stale."""
    return read_port_file(session_port_file(session_id))


def write_session_port(session_id, port):
    """Publish the pet's port atomically. A plain open("w") truncates first and
    the bytes only land at close, so a hook/motion reader firing in that window
    sees an empty file (int("") -> dropped event). Write a sibling temp file and
    os.replace it in — atomic on both POSIX and Windows — so readers only ever
    see the old file or the whole new one, never a half-written one."""
    path = session_port_file(session_id)
    tmp = "{}.{}.tmp".format(path, os.getpid())
    with open(tmp, "w") as f:
        f.write(str(port))
    os.replace(tmp, path)


def pet_alive(session_id, timeout=0.3):
    """True only if THIS session's pet is really listening — proven by the
    liveness handshake, not a bare connect. Guards two failure modes a plain
    connect can't:
      * a stale .port file whose port the OS reassigned to an unrelated local
        process (that process accepts the connect but never answers PING), and
      * accumulating dead .port files (a refused connect means nothing is
        there, so the file is stale and gets removed here).
    Any non-refused error (busy pet, foreign listener that stays silent) counts
    as 'not our pet' but leaves the file alone."""
    path = session_port_file(session_id)
    port = read_port_file(path)
    if port is None:
        return False
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((LOOPBACK, port))
        s.sendall(PING)
        try:
            s.shutdown(socket.SHUT_WR)   # signal EOF so the pet answers now
        except OSError:
            pass
        reply = s.recv(256).decode("utf-8", "replace")
        return BANNER_MARK in reply
    except ConnectionRefusedError:
        try:
            os.unlink(path)              # nothing listening -> stale file
        except OSError:
            pass
        return False
    except OSError:
        return False
    finally:
        s.close()
