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


def test_pet_alive_false_and_removes_stale_file_on_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    # a free (then-closed) port: connect is refused -> nothing is there -> stale
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()
    hostinfo.write_session_port("sid", dead_port)
    path = hostinfo.session_port_file("sid")
    assert os.path.exists(path)
    assert hostinfo.pet_alive("sid") is False
    assert not os.path.exists(path)          # stale file cleaned up


def test_pet_alive_false_without_port_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert hostinfo.pet_alive("nope") is False
