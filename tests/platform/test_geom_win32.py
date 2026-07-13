import os

from claudlet.platform.geom import win32


def test_proc_ancestors_empty_without_kernel32(monkeypatch):
    monkeypatch.setattr(win32, "kernel32", None)
    assert win32.proc_ancestors(1234) == set()


def test_proc_ancestors_empty_for_bad_pid(monkeypatch):
    assert win32.proc_ancestors(None) == set()
    assert win32.proc_ancestors("not-a-pid") == set()


def test_proc_ancestors_walks_real_process_tree():
    if os.name != "nt":
        return
    acc = win32.proc_ancestors(os.getpid())
    assert os.getpid() in acc
    assert len(acc) >= 1


def test_proc_table_empty_without_kernel32(monkeypatch):
    monkeypatch.setattr(win32, "kernel32", None)
    assert win32.proc_table() == {}


def test_proc_table_reflects_real_process_tree():
    if os.name != "nt":
        return
    table = win32.proc_table()
    name, ppid = table[os.getpid()]
    assert "python" in name
    assert ppid > 0


def test_to_logical_identity_at_100_percent():
    # scale 1.0 -> unchanged, ints out
    assert win32._to_logical(100, 200, 800, 600, 1.0) == (100, 200, 800, 600)


def test_to_logical_divides_by_scale():
    # 150% display: a physical rect scales down into Qt logical space
    assert win32._to_logical(150, 150, 1200, 900, 1.5) == (100, 100, 800, 600)
    # 125%
    assert win32._to_logical(125, 0, 500, 250, 1.25) == (100, 0, 400, 200)


def test_dpi_scale_defaults_to_1_without_symbol(monkeypatch):
    # pre-1607 Windows / non-Windows: no GetDpiForWindow -> 1.0 (no regression)
    monkeypatch.setattr(win32, "_HAS_GETDPI", False)
    assert win32._dpi_scale(1234) == 1.0


def test_find_window_by_class_matches_substring(monkeypatch):
    rows = [(11, "chrome_widgetwin_1", 0, 0, 800, 600, 5),
            (22, "cascadia_hosting_window_class", 0, 0, 400, 300, 6)]
    monkeypatch.setattr(win32, "user32", object())   # non-None gate
    monkeypatch.setattr(win32, "_enum_windows", lambda exclude_hwnd=None: rows)
    assert win32.find_window_by_class(["cascadia"]) == 22
    assert win32.find_window_by_class(["nope"]) is None


def test_find_window_by_class_noop_without_user32(monkeypatch):
    monkeypatch.setattr(win32, "user32", None)
    assert win32.find_window_by_class(["x"]) is None


def test_user_locale_empty_without_kernel32(monkeypatch):
    monkeypatch.setattr(win32, "kernel32", None)
    assert win32.user_locale() == ""


def test_activate_hwnd_noop_without_user32(monkeypatch):
    monkeypatch.setattr(win32, "user32", None)
    win32.activate_hwnd(12345)   # must not raise


def test_activate_hwnd_noop_for_falsy_hwnd():
    win32.activate_hwnd(None)    # must not raise
    win32.activate_hwnd(0)


class _FakeUser32:
    def __init__(self):
        self.calls = []
        self.foreground_set_to = None

    def IsIconic(self, hwnd):
        return False

    def GetForegroundWindow(self):
        return 111

    def GetWindowThreadProcessId(self, hwnd, out):
        return {111: 22, 999: 33}.get(hwnd, 0)

    def AttachThreadInput(self, a, b, attach):
        self.calls.append(("attach", a, b, attach))
        return 1

    def SetForegroundWindow(self, hwnd):
        self.foreground_set_to = hwnd
        return 1

    def BringWindowToTop(self, hwnd):
        self.calls.append(("top", hwnd))


class _FakeKernel32:
    def GetCurrentThreadId(self):
        return 44


def test_activate_hwnd_attaches_both_threads_and_sets_foreground(monkeypatch):
    fake_user32 = _FakeUser32()
    monkeypatch.setattr(win32, "user32", fake_user32)
    monkeypatch.setattr(win32, "kernel32", _FakeKernel32())

    win32.activate_hwnd(999)

    assert fake_user32.foreground_set_to == 999
    assert ("attach", 44, 22, True) in fake_user32.calls   # attach to fg thread
    assert ("attach", 44, 33, True) in fake_user32.calls   # attach to target thread
    assert ("attach", 44, 22, False) in fake_user32.calls  # detach afterwards
    assert ("attach", 44, 33, False) in fake_user32.calls
    assert ("top", 999) in fake_user32.calls
