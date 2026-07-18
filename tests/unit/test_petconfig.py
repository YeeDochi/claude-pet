import os, json, tempfile

from claudlet.core import petconfig


def _write(tmp, obj):
    p = os.path.join(tmp, "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return p


EMPTY = {"tool_states": {}, "event_states": {}, "raw_events": {}, "lang": "auto",
         "roam_area": None, "no_go": []}


def test_valid_overrides_kept():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, {"tools": {"Bash": "work_search", "Grep": "sing"},
                         "events": {"prompt": "jump"},
                         "raw_events": {"PostToolUse": "celebrate"}})
        cfg = petconfig.load_config(p)
        assert cfg["tool_states"] == {"Bash": "work_search", "Grep": "sing"}
        assert cfg["event_states"] == {"prompt": "jump"}
        assert cfg["raw_events"] == {"PostToolUse": "celebrate"}


def test_invalid_values_and_keys_dropped():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, {"tools": {"Bash": "not_a_state", "Grep": "sing"},
                         "events": {"prompt": "jump", "bogus_slot": "idle",
                                    "done": "not_a_state"},
                         "raw_events": {"PostToolUse": "wave", "X": "not_a_state"}})
        cfg = petconfig.load_config(p)
        assert cfg["tool_states"] == {"Grep": "sing"}     # bad value dropped
        assert cfg["event_states"] == {"prompt": "jump"}  # bad slot/value dropped
        assert cfg["raw_events"] == {"PostToolUse": "wave"}  # bad value dropped


def test_missing_or_broken_file_yields_empty():
    assert petconfig.load_config("/no/such/file.json") == EMPTY
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "config.json")
        with open(p, "w") as f:
            f.write("{ this is not json ")
        assert petconfig.load_config(p) == EMPTY


def test_non_dict_json_yields_empty():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, ["not", "a", "dict"])
        assert petconfig.load_config(p) == EMPTY


def test_config_path_respects_xdg(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdgtest")
    assert petconfig.config_path() == os.path.join("/tmp/xdgtest", "claudlet", "config.json")


def test_lang_parsed_and_defaulted(tmp_path):
    p = _write(str(tmp_path), {"lang": "en"})
    assert petconfig.load_config(p)["lang"] == "en"
    p2 = _write(str(tmp_path), {"lang": "nonsense"})
    assert petconfig.load_config(p2)["lang"] == "auto"   # bad value -> auto
    p3 = _write(str(tmp_path), {})
    assert petconfig.load_config(p3)["lang"] == "auto"    # absent -> auto


def test_resolve_lang(monkeypatch):
    assert petconfig.resolve_lang("ko") == "ko"
    assert petconfig.resolve_lang("en") == "en"
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    assert petconfig.resolve_lang("auto") == "ko"
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert petconfig.resolve_lang("auto") == "en"


def test_roam_area_parsed():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = petconfig.load_config(_write(tmp, {"roam_area": {"x": 0, "y": 0, "w": 800, "h": 600}}))
        assert cfg["roam_area"] == {"x": 0.0, "y": 0.0, "w": 800.0, "h": 600.0}


def test_roam_area_invalid_dropped():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = petconfig.load_config(_write(tmp, {"roam_area": {"x": 0, "y": 0, "w": -5, "h": 600}}))
        assert cfg["roam_area"] is None


def test_no_go_filters_invalid():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = petconfig.load_config(_write(tmp, {"no_go": [
            {"x": 1, "y": 2, "w": 3, "h": 4},
            {"x": 1, "y": 2, "w": 0, "h": 4},      # w<=0 dropped
            "nonsense",                             # non-dict dropped
        ]}))
        assert cfg["no_go"] == [{"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}]


def test_roam_keys_default_absent():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = petconfig.load_config(_write(tmp, {}))
        assert cfg["roam_area"] is None and cfg["no_go"] == []
