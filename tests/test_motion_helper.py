import sys, os, json, types, socket

MOD_PATH = os.path.join(os.path.dirname(__file__), "..", "bin", "claude-pet-motion")
mod = types.ModuleType("claude_pet_motion")
mod.__file__ = MOD_PATH
with open(MOD_PATH, encoding="utf-8") as f:
    exec(compile(f.read(), MOD_PATH, "exec"), mod.__dict__)


def test_new_motions_present():
    for m in ("jump", "wave", "sing", "juggle", "float"):
        assert m in mod.MOTIONS


def test_float_holds_by_default():
    assert mod.MOTIONS["float"] == 0.0
    assert mod.resolve_dur("float", None) == 0.0


def test_resolve_dur_override_wins():
    assert mod.resolve_dur("jump", "5") == 5.0
    assert mod.resolve_dur("jump", None) == mod.MOTIONS["jump"]


def test_build_message_is_json_line():
    line = mod.build_motion_message("jump", 2.5)
    assert line.endswith("\n")
    obj = json.loads(line)
    assert obj == {"cmd": "motion", "motion": "jump", "dur": 2.5}


def test_build_message_clear():
    obj = json.loads(mod.build_motion_message(None, 0))
    assert obj["cmd"] == "motion" and obj["motion"] is None


def test_main_list_and_unknown(capsys):
    assert mod.main(["claude-pet-motion", "list"]) == 0
    assert mod.main(["claude-pet-motion", "bogus"]) == 1


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_send_removes_stale_port_file(tmp_path, monkeypatch):
    # a dead pet leaves its .port file behind; nothing listens on the port
    # it names, so the connect is refused -> that's the "stale" signal.
    stale = tmp_path / "claude-pet-dead.port"
    stale.write_text(str(_free_port()))
    monkeypatch.setattr(mod, "port_files", lambda: [str(stale)])

    n = mod.send(mod.build_motion_message("jump", 1.0))

    assert n == 0
    assert not stale.exists()


def test_send_keeps_live_port_file(tmp_path, monkeypatch):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        live = tmp_path / "claude-pet-live.port"
        live.write_text(str(srv.getsockname()[1]))
        monkeypatch.setattr(mod, "port_files", lambda: [str(live)])

        n = mod.send(mod.build_motion_message("jump", 1.0))
        conn, _ = srv.accept()
        data = conn.recv(200)
        conn.close()
    finally:
        srv.close()

    assert n == 1
    assert live.exists()
    assert b"jump" in data


class _TimeoutSock:
    """Stand-in socket whose connect times out (a live-but-busy pet), to prove
    send() does NOT delete the port file on anything but a refused connect."""
    def settimeout(self, t): pass
    def connect(self, addr): raise socket.timeout()
    def sendall(self, b): pass
    def close(self): pass


def test_send_keeps_port_file_on_timeout(tmp_path, monkeypatch):
    # a busy pet whose event loop is momentarily blocked -> connect times out.
    # deleting its .port then would permanently sever a LIVE pet, so keep it.
    slow = tmp_path / "claude-pet-slow.port"
    slow.write_text("55555")
    monkeypatch.setattr(mod, "port_files", lambda: [str(slow)])
    monkeypatch.setattr(mod.socket, "socket", lambda *a, **k: _TimeoutSock())

    n = mod.send(mod.build_motion_message("jump", 1.0))

    assert n == 0
    assert slow.exists()          # NOT removed (timeout != refused)


def test_send_ignores_malformed_port_file(tmp_path, monkeypatch):
    # malformed content, not a refused connection -> not the dead-pet signal
    # this cleanup targets, so leave it alone rather than guessing.
    bad = tmp_path / "claude-pet-bad.port"
    bad.write_text("not-a-port")
    monkeypatch.setattr(mod, "port_files", lambda: [str(bad)])

    n = mod.send(mod.build_motion_message("jump", 1.0))

    assert n == 0
    assert bad.exists()
