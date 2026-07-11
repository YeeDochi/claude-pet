#!/usr/bin/env python3
"""claude-pet quick installer — Linux, macOS, Windows.

  Linux / macOS:
    curl -fsSL https://raw.githubusercontent.com/YeeDochi/claude-pet/master/install.py | python3 -
  Windows (PowerShell):
    irm https://raw.githubusercontent.com/YeeDochi/claude-pet/master/install.py | python -

Clones (or updates) the repo, ensures dependencies (PyQt6, plus
pyobjc-framework-Quartz on macOS — the latter via bin/claude-pet-install), and
registers the Claude Code hooks + skill. Re-run anytime to update.
Override the location with the CLAUDE_PET_DIR environment variable.
"""
import os
import shutil
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO = "https://github.com/YeeDochi/claude-pet.git"
DEST = os.environ.get("CLAUDE_PET_DIR") or os.path.join(os.path.expanduser("~"),
                                                        "claude-pet")


def main():
    if not shutil.which("git"):
        sys.exit("error: git is required.")

    # 1) get the source (clone, or update an existing checkout)
    if os.path.isdir(os.path.join(DEST, ".git")):
        print("==> updating", DEST)
        subprocess.call(["git", "-C", DEST, "pull", "--ff-only"])
    else:
        print("==> cloning into", DEST)
        subprocess.check_call(["git", "clone", "--depth", "1", REPO, DEST])

    # 2) ensure PyQt6 (best-effort; tell the user if we can't)
    try:
        __import__("PyQt6")
    except ImportError:
        print("==> installing PyQt6")
        if subprocess.call([sys.executable, "-m", "pip", "install",
                            "--user", "PyQt6"]) != 0:
            print("   couldn't auto-install PyQt6 — install it yourself: "
                  "pip install PyQt6", file=sys.stderr)

    # 3) hooks + /claude-pet skill (same interpreter -> cross-OS)
    subprocess.check_call([sys.executable,
                           os.path.join(DEST, "bin", "claude-pet-install")])

    print("\nclaude-pet installed at", DEST, "\N{PAW PRINTS}")
    print("Restart Claude Code sessions, or run now:")
    print("  %s %s" % (sys.executable, os.path.join(DEST, "src", "pet.py")))


if __name__ == "__main__":
    main()
