#!/usr/bin/env python3
"""claudlet post-install setup: register the Claude Code hooks and link the
/claudlet skill into ~/.claude/skills/. Idempotent.

With a pipx/pip install the `claudlet*` commands and Python deps (PyQt6, plus
pyobjc-framework-Quartz on macOS) are already provided by the package, so this
only wires claudlet into Claude Code. Run after installing:

    claudlet-install            set up hooks + skill
    claudlet-install --remove   remove hooks + skill link (package stays)
"""
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.expanduser(os.path.join("~", ".claude", "skills"))
SKILL_LINK = os.path.join(SKILLS_DIR, "claudlet")
SKILL_SRC = os.path.join(HERE, "skill")          # packaged skill data

# README links shown when setup finishes. EN points at the repo root (GitHub
# renders README.md there); KO points at the Korean README explicitly.
README_EN = "https://github.com/YeeDochi/Claudlet"
README_KO = "https://github.com/YeeDochi/Claudlet/blob/master/README.ko.md"

_COLOR = (sys.stdout.isatty() and os.name != "nt"
          and os.environ.get("NO_COLOR") is None)


def _c(code, s):
    return "\033[%sm%s\033[0m" % (code, s) if _COLOR else s


def head(s):
    print("\n" + _c("1;36", s))


def ok(label, detail=""):
    print("  %s %s%s" % (_c("32", "+"), label,
                         ("  " + _c("2", detail)) if detail else ""))


def warn(s):
    print("  %s %s" % (_c("33", "!"), s), file=sys.stderr)


def _link_skill():
    """Symlink the packaged skill into ~/.claude/skills/. Returns (path, note)."""
    os.makedirs(SKILLS_DIR, exist_ok=True)
    if os.path.exists(SKILL_LINK) and not os.path.islink(SKILL_LINK):
        return None, "%s exists and isn't a symlink - left as-is" % SKILL_LINK
    try:
        if os.path.islink(SKILL_LINK):
            os.unlink(SKILL_LINK)
        os.symlink(SKILL_SRC, SKILL_LINK, target_is_directory=True)
        return SKILL_LINK, None
    except OSError as e:
        if os.name == "nt" and _link_skill_junction():
            return SKILL_LINK, None
        return None, "could not link skill (%s); link it manually: %s -> %s" % (
            e, SKILL_LINK, SKILL_SRC)


def _link_skill_junction():
    """Windows fallback: directory junctions don't need elevated privilege."""
    import subprocess
    try:
        subprocess.check_call(
            ["cmd", "/c", "mklink", "/J", SKILL_LINK, SKILL_SRC],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _unlink_skill():
    if os.path.islink(SKILL_LINK):
        os.unlink(SKILL_LINK)
    elif os.name == "nt" and os.path.isdir(SKILL_LINK):
        try:
            os.rmdir(SKILL_LINK)
        except OSError:
            pass


def _pip_install(pkgs):
    """Best-effort install for a bare source checkout that skipped `pip install`.
    Plain first (venv), then --user (system Python). A pipx/pip install already
    has the deps, so nothing runs then. Returns True on success."""
    import subprocess
    for extra in ([], ["--user"]):
        try:
            if subprocess.call(
                    [sys.executable, "-m", "pip", "install", *extra, *pkgs]) == 0:
                return True
        except Exception:
            pass
    return False


def _importable(name):
    import subprocess
    try:
        return subprocess.call([sys.executable, "-c", "import %s" % name],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) == 0
    except Exception:
        return False


def _check_deps():
    """Verify runtime deps (PyQt6; +Quartz on macOS). Normally already present
    via the package install; only a bare source checkout hits the pip fallback."""
    deps = [("PyQt6", "PyQt6")]
    if sys.platform == "darwin":
        deps.append(("Quartz", "pyobjc-framework-Quartz"))
    names = ", ".join(pip for _i, pip in deps)
    missing = [(i, pip) for i, pip in deps if not _importable(i)]
    if not missing:
        return "%s present" % names
    pkgs = [pip for _i, pip in missing]
    print("  installing %s ..." % ", ".join(pkgs))
    _pip_install(pkgs)
    still = [pip for i, pip in missing if not _importable(i)]
    if still:
        warn("could not install %s - install it with:\n      %s -m pip install %s"
             % (", ".join(still), os.path.basename(sys.executable), " ".join(still)))
        return "%s (%s missing)" % (names, ", ".join(still))
    return "%s installed" % ", ".join(pkgs)


def _already_installed(install_hooks):
    """True if claudlet hooks are ALREADY registered in Claude Code settings —
    i.e. this run is a reinstall/update, not a first install. Must be checked
    BEFORE install_hooks.main() runs (which registers them and would make every
    run look installed). `is_ours` also matches the pre-rename claude-pet
    markers, so upgrading from an old version still counts as an update. Any
    read error -> treat as a fresh install (show both links; harmless)."""
    try:
        s = install_hooks.load()
        for groups in s.get("hooks", {}).values():
            if any(install_hooks.is_ours(g) for g in groups):
                return True
    except Exception:
        pass
    return False


def _readme_line(url, label):
    return "  %s %s  %s" % (_c("1;36", "\U0001F4D6"), label, _c("4", url))


def _print_readme(was_installed):
    """Fresh install -> both README links (language unknown yet). Update -> the
    one matching the user's resolved language (Korean locale -> KO, else EN),
    since by now they have a config/locale we can read."""
    if not was_installed:
        print(_readme_line(README_EN, "Guide: "))
        print(_readme_line(README_KO, "가이드:"))
        return
    try:
        from claudlet import petconfig
        cfg = petconfig.load_config()
        lang = petconfig.resolve_lang(cfg.get("lang", "auto"))
    except Exception:
        lang = "en"                           # never fail setup over a link
    if lang == "ko":
        print(_readme_line(README_KO, "가이드:"))
    else:
        print(_readme_line(README_EN, "Guide:"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from claudlet import install_hooks

    if "--remove" in argv:
        # single teardown implementation lives in uninstall; delegate so
        # `claudlet-install --remove` and `claudlet-uninstall` never diverge.
        from claudlet import uninstall
        return uninstall.main(argv)

    # capture BEFORE install_hooks.main() registers our hooks, else every run
    # looks already-installed and the update branch would always win.
    was_installed = _already_installed(install_hooks)

    head("setting up claudlet")
    ok("dependencies", _check_deps())
    install_hooks.main([])
    ok("Claude Code hooks", "registered")
    skill, note = _link_skill()
    if skill:
        ok("/claudlet skill", skill)
    if note:
        warn(note)

    head("done")
    print("Restart Claude Code sessions to pick up the hooks (new sessions")
    print("auto-spawn a pet). Run one now with:  " + _c("1", "claudlet"))
    print("Update anytime from inside Claude Code with:  " + _c("1", "/claudlet update"))
    _print_readme(was_installed)


if __name__ == "__main__":
    main()
