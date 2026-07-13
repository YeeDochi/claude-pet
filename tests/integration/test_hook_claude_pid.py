import os, types
import claudlet.platform.geom as geom_pkg
from claudlet.cli import hook as mod


def tree(d):
    """Build a proc_info callback from {pid: (comm, ppid)}."""
    return lambda pid: d.get(pid)


def test_walks_up_through_shell_to_claude():
    # hook(101) -> zsh(90) -> claude(80) -> zsh(1)
    info = tree({101: ("python3", 90), 90: ("zsh", 80),
                 80: ("claude", 1)})
    assert mod.resolve_claude_pid(90, info) == 80


def test_direct_child_of_claude():
    info = tree({90: ("claude", 1)})
    assert mod.resolve_claude_pid(90, info) == 90


def test_no_claude_in_chain_returns_zero():
    info = tree({90: ("zsh", 80), 80: ("systemd", 1)})
    assert mod.resolve_claude_pid(90, info) == 0


def test_dead_pid_returns_zero():
    info = tree({})  # pid already gone
    assert mod.resolve_claude_pid(90, info) == 0


def test_cycle_does_not_hang():
    # self-referential ppid must not loop forever
    info = tree({90: ("zsh", 90)})
    assert mod.resolve_claude_pid(90, info) == 0


def test_matches_claude_with_suffix():
    # comm may be truncated/decorated but still contain 'claude'
    info = tree({90: ("zsh", 80), 80: ("claude-code", 1)})
    assert mod.resolve_claude_pid(90, info) == 80


def test_proc_info_windows_branch_walks_via_win32_table(monkeypatch):
    # _proc_info has no /proc on Windows; it must fall back to a Toolhelp
    # snapshot (win32.proc_table) instead of always returning None.
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod, "_win32_proc_table", None)
    fake = types.ModuleType("win32")
    fake.proc_table = lambda: {90: ("cmd.exe", 80), 80: ("claude.exe", 1)}
    monkeypatch.setattr(geom_pkg, "win32", fake, raising=False)
    assert mod.resolve_claude_pid(90, mod._proc_info) == 80


def test_proc_info_windows_branch_caches_table_once(monkeypatch):
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod, "_win32_proc_table", None)
    calls = []
    fake = types.ModuleType("win32")
    def _table():
        calls.append(1)
        return {90: ("cmd.exe", 80), 80: ("claude.exe", 1)}
    fake.proc_table = _table
    monkeypatch.setattr(geom_pkg, "win32", fake, raising=False)
    mod._proc_info(90)
    mod._proc_info(80)
    assert len(calls) == 1


def test_proc_info_windows_branch_missing_module_returns_none(monkeypatch):
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod, "_win32_proc_table", None)
    monkeypatch.setattr(geom_pkg, "win32", None, raising=False)
    assert mod._proc_info(90) is None
