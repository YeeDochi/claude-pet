import os, types

HOOK = os.path.join(os.path.dirname(__file__), "..", "bin", "claude-pet-hook")
mod = types.ModuleType("claude_pet_hook")
mod.__file__ = HOOK
with open(HOOK) as f:
    exec(compile(f.read(), HOOK, "exec"), mod.__dict__)


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
