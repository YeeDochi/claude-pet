import sys, os, socket, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import hostinfo


def test_detect_vscode_by_term_program():
    assert hostinfo.detect_host({"TERM_PROGRAM": "vscode"}) == "vscode"

def test_detect_vscode_by_pid():
    assert hostinfo.detect_host({"VSCODE_PID": "123"}) == "vscode"

def test_detect_jetbrains():
    assert hostinfo.detect_host({"TERMINAL_EMULATOR": "JetBrains-JediTerm"}) == "jetbrains"

def test_detect_konsole():
    assert hostinfo.detect_host({"KONSOLE_VERSION": "250801"}) == "konsole"

def test_detect_unknown():
    assert hostinfo.detect_host({}) == "unknown"

def test_detect_macos_terminals():
    assert hostinfo.detect_host({"TERM_PROGRAM": "Apple_Terminal"}) == "apple_terminal"
    assert hostinfo.detect_host({"TERM_PROGRAM": "iTerm.app"}) == "iterm"

def test_mac_app_names():
    assert hostinfo.mac_app("vscode") == "Visual Studio Code"
    assert hostinfo.mac_app("apple_terminal") == "Terminal"
    assert hostinfo.mac_app("konsole") is None      # no macOS app for konsole
    assert hostinfo.mac_app("unknown") is None

def test_macos_host_classes_match_app_names():
    # frontmost app name on macOS is matched against these substrings
    assert hostinfo.host_classes("apple_terminal") == ["terminal"]
    assert hostinfo.host_classes("iterm") == ["iterm"]

def test_host_classes():
    assert hostinfo.host_classes("vscode") == ["code"]
    assert hostinfo.host_classes("konsole") == ["konsole"]
    assert hostinfo.host_classes("unknown") == []
    assert hostinfo.host_classes("nonsense") == []

def test_win_classes_vscode_has_no_safe_win32_guess():
    # VS Code's real Win32 class ("chrome_widgetwin_1") is shared by every
    # other Electron/Chromium app (Discord, Slack, Teams, a browser, even a
    # second unrelated VS Code window) -- guessing it risks click-to-focus
    # raising the wrong window, so win_classes deliberately returns []
    # (find_window_by_class then safely no-ops) rather than a false match.
    assert hostinfo.win_classes("vscode") == []

def test_win_classes_unknown_falls_back_to_generic_terminal_classes():
    # cmd.exe/PowerShell/Windows Terminal all detect_host() as "unknown" (no
    # env-var signal), unlike Linux where "unknown" means "no guess at all".
    # These two classes are distinctive enough (native terminal hosts only)
    # to trust a blind substring match.
    assert hostinfo.win_classes("unknown") == [
        "cascadia_hosting_window_class", "consolewindowclass"]

def test_win_classes_unmapped_host_gets_no_fallback():
    # Any host without a Windows-safe class (e.g. "konsole", a Linux-only
    # host that can never legitimately appear on Windows) gets no guess --
    # only "unknown" gets the generic terminal fallback.
    assert hostinfo.win_classes("konsole") == []
    assert hostinfo.win_classes("nonsense") == []

def test_session_port_file_path(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert hostinfo.session_port_file("abc") == os.path.join("/run/user/1000", "claude-pet-abc.port")
    assert hostinfo.session_port_file(None) == os.path.join("/run/user/1000", "claude-pet-default.port")

def test_read_session_port_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    hostinfo.write_session_port("abc", 54321)
    assert hostinfo.read_session_port("abc") == 54321

def test_read_session_port_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert hostinfo.read_session_port("nope") is None


def test_write_session_port_is_atomic_no_temp_left(tmp_path, monkeypatch):
    # atomic write must leave the final file only (no *.tmp sibling) and never
    # a truncated/empty file a concurrent reader could see.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    hostinfo.write_session_port("atom", 4242)
    assert hostinfo.read_session_port("atom") == 4242
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_write_session_port_retries_through_transient_replace_failure(tmp_path, monkeypatch):
    # os.replace() onto a destination another process has open for a brief
    # read raises PermissionError on Windows even though nothing is actually
    # wrong; write_session_port must retry through a transient failure rather
    # than crash its caller (Pet.__init__).
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    real_replace = os.replace
    calls = []

    def _flaky_replace(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("simulated sharing violation")
        real_replace(src, dst)

    monkeypatch.setattr(hostinfo.os, "replace", _flaky_replace)
    monkeypatch.setattr(hostinfo.time, "sleep", lambda s: None)
    hostinfo.write_session_port("flaky", 9999)
    assert hostinfo.read_session_port("flaky") == 9999
    assert len(calls) == 3


def test_write_session_port_raises_after_exhausting_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    def _always_fails(src, dst):
        raise PermissionError("simulated persistent sharing violation")

    monkeypatch.setattr(hostinfo.os, "replace", _always_fails)
    monkeypatch.setattr(hostinfo.time, "sleep", lambda s: None)
    try:
        hostinfo.write_session_port("stuck", 1111)
        assert False, "expected PermissionError to propagate"
    except PermissionError:
        pass
    # even on persistent failure the temp file must not linger
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def _banner_pet(session="sid", reply=None):
    """A minimal fake pet on a loopback port: accepts one connection, and
    answers with `reply` (default: the real banner). Returns (srv, port)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    if reply is None:
        reply = ('{"pet": "%s", "session": "%s"}\n' % (hostinfo.BANNER_MARK, session)).encode()

    def _serve():
        try:
            conn, _ = srv.accept()
            conn.recv(256)
            if reply:
                conn.sendall(reply)
            conn.close()
        except OSError:
            pass
    threading.Thread(target=_serve, daemon=True).start()
    return srv, port


def test_pet_alive_true_when_banner_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    srv, port = _banner_pet("sid")
    try:
        hostinfo.write_session_port("sid", port)
        assert hostinfo.pet_alive("sid") is True
    finally:
        srv.close()


def test_pet_alive_false_for_foreign_listener(tmp_path, monkeypatch):
    # a listener that accepts but never sends our banner (a stale port reused by
    # an unrelated local process) must NOT be mistaken for a live pet.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    srv, port = _banner_pet(reply=b"HTTP/1.1 200 OK\r\n\r\n")
    try:
        hostinfo.write_session_port("sid", port)
        assert hostinfo.pet_alive("sid") is False
    finally:
        srv.close()


class _TimeoutSocket:
    """A socket that accepts the connect but times out answering -- a busy
    but LIVE pet. Must be treated differently from a refused connect: the
    port file is the only record of where that live pet is, so it must
    survive (mirrors bin/claude-pet-motion's send()'s refused-vs-timeout
    distinction, tested in tests/test_motion_helper.py)."""
    def settimeout(self, t): pass
    def connect(self, addr): pass
    def sendall(self, b): pass
    def shutdown(self, how): pass
    def recv(self, n): raise socket.timeout()
    def close(self): pass


def test_pet_alive_false_but_keeps_port_file_on_timeout(tmp_path, monkeypatch):
    # a busy-but-alive pet must NOT have its port file deleted -- only a
    # refused connect (nothing listening at all) proves it, per pet_alive's
    # own docstring ("Any non-refused error... leaves the file alone").
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    hostinfo.write_session_port("sid", 54321)
    path = hostinfo.session_port_file("sid")
    monkeypatch.setattr(hostinfo.socket, "socket", lambda *a, **k: _TimeoutSocket())
    assert hostinfo.pet_alive("sid") is False
    assert os.path.exists(path)              # NOT removed (timeout != refused)


class _RefusingSocket:
    """A socket whose connect() is refused — deterministic on every OS, unlike
    relying on the kernel to refuse a real just-closed port (Windows loopback
    doesn't guarantee that timing)."""
    def settimeout(self, t): pass
    def connect(self, addr): raise ConnectionRefusedError()
    def close(self): pass


def test_pet_alive_false_and_removes_stale_file_on_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    hostinfo.write_session_port("sid", 54321)
    path = hostinfo.session_port_file("sid")
    assert os.path.exists(path)
    # force the refused-connect branch rather than depend on OS port timing
    monkeypatch.setattr(hostinfo.socket, "socket", lambda *a, **k: _RefusingSocket())
    assert hostinfo.pet_alive("sid") is False
    assert not os.path.exists(path)          # stale file cleaned up


def test_pet_alive_false_without_port_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert hostinfo.pet_alive("nope") is False
