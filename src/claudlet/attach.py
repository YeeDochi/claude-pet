"""claudlet-attach — bring up a pet for a Claude Code session (or standalone).

A console entry point so the /claudlet skill can just run `claudlet-attach`
instead of shelling into `python3 -c "import hostinfo; ..."` — which breaks under
a pipx install, where the package lives in an isolated venv the system python
can't import. Detects the session id and host, skips if a pet is already
attached (via the same liveness handshake the hook uses), and launches a
detached pet bound to the session.

    claudlet-attach                 attach to this session (env/newest transcript)
    claudlet-attach --session <id>  attach to a specific session
    claudlet-attach --standalone    an unattached, decorative roaming pet
"""
import glob
import os
import subprocess
import sys

from claudlet.core import hostinfo


def _newest_session_id():
    """Fallback when $CLAUDE_CODE_SESSION_ID is unset: the session id of the
    most recently modified transcript under ~/.claude/projects/."""
    files = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    return os.path.splitext(os.path.basename(newest))[0]


def _launch(extra_args):
    """Launch a detached `python -m claudlet` that outlives this call."""
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
          "stderr": subprocess.DEVNULL}
    if os.name == "posix":
        kw["start_new_session"] = True            # own process group; survives us
    # ensure the child interpreter can import claudlet from a source checkout
    # (pipx/pip installs already have it importable; the extra PYTHONPATH is harmless)
    env = dict(os.environ)
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(hostinfo.__file__)))
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.Popen([sys.executable, "-m", "claudlet"] + extra_args, env=env, **kw)


def _arg_value(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--standalone" in argv:
        _launch([])
        print("standalone pet running")
        return 0

    session_id = (_arg_value(argv, "--session")
                  or os.environ.get("CLAUDE_CODE_SESSION_ID")
                  or _newest_session_id()
                  or "default")
    host = hostinfo.detect_host()

    if hostinfo.pet_alive(session_id):
        print("already attached to session %s (host=%s)" % (session_id, host))
        return 0

    _launch(["--session", session_id, "--host", host])
    print("attached to session %s (host=%s)" % (session_id, host))
    return 0


def _cli():
    """console-script entry point; never hard-fails the caller."""
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    _cli()
