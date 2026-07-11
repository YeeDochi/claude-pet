from claude_pet import attach


def test_arg_value():
    assert attach._arg_value(["--session", "abc"], "--session") == "abc"
    assert attach._arg_value(["--session"], "--session") is None   # flag, no value
    assert attach._arg_value([], "--session") is None


def test_standalone_launches_unbound(monkeypatch):
    calls = []
    monkeypatch.setattr(attach, "_launch", lambda args: calls.append(args))
    assert attach.main(["--standalone"]) == 0
    assert calls == [[]]                          # no --session/--host


def test_attach_skips_when_already_alive(monkeypatch):
    monkeypatch.setattr(attach.hostinfo, "detect_host", lambda: "konsole")
    monkeypatch.setattr(attach.hostinfo, "pet_alive", lambda sid, **k: True)
    launched = []
    monkeypatch.setattr(attach, "_launch", lambda args: launched.append(args))
    assert attach.main(["--session", "s1"]) == 0
    assert launched == []                          # alive -> don't double-launch


def test_attach_launches_when_dead(monkeypatch):
    monkeypatch.setattr(attach.hostinfo, "detect_host", lambda: "konsole")
    monkeypatch.setattr(attach.hostinfo, "pet_alive", lambda sid, **k: False)
    launched = []
    monkeypatch.setattr(attach, "_launch", lambda args: launched.append(args))
    assert attach.main(["--session", "s1"]) == 0
    assert launched == [["--session", "s1", "--host", "konsole"]]


def test_attach_session_from_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "envsid")
    monkeypatch.setattr(attach.hostinfo, "detect_host", lambda: "code")
    monkeypatch.setattr(attach.hostinfo, "pet_alive", lambda sid, **k: False)
    launched = []
    monkeypatch.setattr(attach, "_launch", lambda args: launched.append(args))
    attach.main([])                                # no --session -> use env
    assert launched == [["--session", "envsid", "--host", "code"]]
