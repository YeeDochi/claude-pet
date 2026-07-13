#!/usr/bin/env python3
"""claudlet-uninstall — reverse what claudlet-install set up, in one shot.

Usage:
    claudlet-uninstall            # stop pets, remove hooks + skill link,
                                  # clean stray .port files, guide pkg removal
    claudlet-uninstall --purge    # all the above + delete ~/.config/claudlet

Deliberately does NOT remove the package itself (uninstalling the running
interpreter's own package mid-run is fragile) — it prints the exact command
instead. See docs/superpowers/specs/2026-07-11-claudlet-uninstall-design.md.
"""
import json
import os
import shutil
import sys

from claudlet import motion
from claudlet.core import petconfig
from claudlet import install
from claudlet import install_hooks


def stop_running_pets():
    """Broadcast a quit to every running pet; return how many accepted it.

    Reuses the motion transport (port-file discovery + refused-connect stale
    cleanup) so there is one code path for talking to live pets."""
    return motion.send(json.dumps({"cmd": "quit"}) + "\n")


def clean_port_files():
    """Remove any claudlet-*.port still lingering (dead pets that never cleaned
    up after themselves); return how many files were actually removed."""
    n = 0
    for path in motion.port_files():
        try:
            os.unlink(path)
            n += 1
        except OSError:
            pass                        # already gone / not ours to remove
    return n


def purge_config():
    """Delete the user config directory (~/.config/claudlet), resolved via the
    same logic petconfig uses. Returns True if a directory was removed, False
    if there was nothing to remove."""
    cfg_dir = os.path.dirname(petconfig.config_path())
    if os.path.isdir(cfg_dir):
        shutil.rmtree(cfg_dir, ignore_errors=True)
        return not os.path.isdir(cfg_dir)
    return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    purge = "--purge" in argv

    install.head("uninstalling claudlet")
    n = stop_running_pets()
    if n:
        install.ok("stopped %d running pet(s)" % n)
    install_hooks.main(["--remove"])
    install._unlink_skill()
    install.ok("hooks + skill link removed")
    cleaned = clean_port_files()
    if cleaned:
        install.ok("cleaned %d stray port file(s)" % cleaned)
    if purge:
        if purge_config():
            install.ok("removed ~/.config/claudlet")
        else:
            install.ok("no config to remove")

    print("\nclaudlet unhooked. Remove the package with your installer:")
    print("    pipx uninstall claudlet        # if installed with pipx")
    print("    pip uninstall claudlet         # if installed with pip")
    return 0


def _cli():
    """console-script entry point (never raise from the CLI)."""
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    _cli()
