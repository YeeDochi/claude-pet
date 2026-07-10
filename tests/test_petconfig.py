import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import petconfig


def _write(tmp, obj):
    p = os.path.join(tmp, "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return p


def test_valid_overrides_kept():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, {"tools": {"Bash": "work_search", "Grep": "sing"},
                         "events": {"prompt": "jump"}})
        cfg = petconfig.load_config(p)
        assert cfg["tool_states"] == {"Bash": "work_search", "Grep": "sing"}
        assert cfg["event_states"] == {"prompt": "jump"}


def test_invalid_values_and_keys_dropped():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, {"tools": {"Bash": "not_a_state", "Grep": "sing"},
                         "events": {"prompt": "jump", "bogus_slot": "idle",
                                    "done": "not_a_state"}})
        cfg = petconfig.load_config(p)
        assert cfg["tool_states"] == {"Grep": "sing"}     # bad value dropped
        assert cfg["event_states"] == {"prompt": "jump"}  # bad slot/value dropped


def test_missing_or_broken_file_yields_empty():
    assert petconfig.load_config("/no/such/file.json") == {
        "tool_states": {}, "event_states": {}}
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "config.json")
        with open(p, "w") as f:
            f.write("{ this is not json ")
        assert petconfig.load_config(p) == {"tool_states": {}, "event_states": {}}


def test_non_dict_json_yields_empty():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, ["not", "a", "dict"])
        assert petconfig.load_config(p) == {"tool_states": {}, "event_states": {}}


def test_config_path_respects_xdg(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdgtest")
    assert petconfig.config_path() == "/tmp/xdgtest/claude-pet/config.json"
