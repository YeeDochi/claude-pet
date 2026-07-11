"""Tests for the pure parts of the macOS Quartz geometry backend.

The actual CGWindowListCopyWindowInfo call can only be exercised on real
macOS hardware (which nobody writing this had — the module is SPECULATIVE);
these tests cover what's testable anywhere: import safety, the no-backend
no-op path, the info-dict -> row filtering, and the wire-format output
round-tripping through windows.parse_kwin_dump."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import macos_geom
import windows


def _info(layer=0, x=10, y=20, w=300, h=200, pid=555, owner="Terminal",
          name=None, alpha=None, number=42):
    d = {
        macos_geom.K_LAYER: layer,
        macos_geom.K_BOUNDS: {"X": float(x), "Y": float(y),
                              "Width": float(w), "Height": float(h)},
        macos_geom.K_OWNER_PID: pid,
        macos_geom.K_NUMBER: number,
    }
    if owner is not None:
        d[macos_geom.K_OWNER_NAME] = owner
    if name is not None:
        d[macos_geom.K_NAME] = name
    if alpha is not None:
        d[macos_geom.K_ALPHA] = alpha
    return d


def test_import_and_dump_noop_without_quartz(monkeypatch):
    # On non-macOS (and macOS without pyobjc) Quartz is None: importable,
    # available() False, dump() just "".
    monkeypatch.setattr(macos_geom, "Quartz", None)
    assert macos_geom.available() is False
    assert macos_geom.dump() == ""
    assert macos_geom.dump(exclude_pid=123) == ""
    assert macos_geom._enum_windows() == []


def test_row_from_info_normal_window():
    row = macos_geom._row_from_info(_info())
    assert row == (42, "terminal", 10, 20, 300, 200, 555)


def test_row_from_info_filters():
    assert macos_geom._row_from_info(_info(layer=25)) is None      # menu bar etc.
    assert macos_geom._row_from_info(_info(alpha=0.0)) is None     # fully transparent
    assert macos_geom._row_from_info(_info(w=0)) is None           # degenerate rect
    assert macos_geom._row_from_info(_info(), exclude_pid=555) is None  # the pet itself
    assert macos_geom._row_from_info({macos_geom.K_LAYER: 0}) is None   # no bounds
    assert macos_geom._row_from_info({}) is None                   # empty/odd dict


def test_row_from_info_alpha_partial_kept():
    assert macos_geom._row_from_info(_info(alpha=0.9)) is not None


def test_row_class_falls_back_to_window_name():
    # No Screen Recording permission normally means kCGWindowName is absent
    # and kCGWindowOwnerName present; the reverse fallback still yields a class.
    row = macos_geom._row_from_info(_info(owner=None, name="My App"))
    assert row[1] == "my app"
    row = macos_geom._row_from_info(_info(owner=None, name=None))
    assert row[1] == ""      # parse_kwin_dump's EXCLUDE_CLASSES drops it later


def test_row_class_sanitizes_wire_delimiters():
    row = macos_geom._row_from_info(_info(owner="We;rd|App"))
    assert ";" not in row[1] and "|" not in row[1]


def test_row_rounds_float_bounds():
    row = macos_geom._row_from_info(_info(x=10.6, y=19.4, w=300.5, h=199.5))
    assert row[2:6] == (11, 19, 300, 200)


class _FakeQuartz:
    """Just enough Quartz surface for dump(): option constants + the call."""
    kCGWindowListOptionOnScreenOnly = 1
    kCGWindowListExcludeDesktopElements = 16
    kCGNullWindowID = 0

    def __init__(self, infos):
        self._infos = infos
        self.calls = []

    def CGWindowListCopyWindowInfo(self, opts, relative_to):
        self.calls.append((opts, relative_to))
        return self._infos


def test_dump_reverses_to_bottom_up_and_roundtrips(monkeypatch):
    # CGWindowListCopyWindowInfo returns topmost-FIRST; the wire format wants
    # bottom-to-top, so the front window must come LAST in the dump.
    fake = _FakeQuartz([
        _info(number=1, owner="Front App", x=0, y=0, w=500, h=400, pid=100),
        _info(number=99, layer=25, owner="Menubar"),          # filtered out
        _info(number=2, owner="Back App", x=50, y=60, w=640, h=480, pid=200),
    ])
    monkeypatch.setattr(macos_geom, "Quartz", fake)
    dump = macos_geom.dump()
    assert dump == "2;back app;50,60,640,480;200|1;front app;0,0,500,400;100"
    # both option flags requested, relative to the null window id
    assert fake.calls == [(17, 0)]

    wins = windows.parse_kwin_dump(dump)
    assert [w.wid for w in wins] == ["2", "1"]
    assert wins[-1].title == "front app"        # topmost last, per contract
    assert wins[-1].pid == 100
    # topmost-last order is what windows.window_at relies on
    assert windows.window_at(10, 10, wins).wid == "1"


def test_dump_excludes_pid(monkeypatch):
    fake = _FakeQuartz([
        _info(number=1, pid=100),
        _info(number=2, pid=200),
    ])
    monkeypatch.setattr(macos_geom, "Quartz", fake)
    dump = macos_geom.dump(exclude_pid=100)
    assert "100" not in dump
    assert dump.startswith("2;")


def test_dump_empty_feed(monkeypatch):
    monkeypatch.setattr(macos_geom, "Quartz", _FakeQuartz(None))
    assert macos_geom.dump() == ""
    monkeypatch.setattr(macos_geom, "Quartz", _FakeQuartz([]))
    assert macos_geom.dump() == ""


def test_dump_survives_raising_backend(monkeypatch):
    class _Boom(_FakeQuartz):
        def CGWindowListCopyWindowInfo(self, opts, relative_to):
            raise RuntimeError("no window server connection")
    monkeypatch.setattr(macos_geom, "Quartz", _Boom([]))
    assert macos_geom.dump() == ""      # never raises into the poll timer


# --- proc_ancestors (ps-based; does NOT need pyobjc, so it's exercised anywhere) ---

def test_proc_ancestors_empty_for_bad_pid():
    assert macos_geom.proc_ancestors(None) == set()
    assert macos_geom.proc_ancestors("not-a-pid") == set()


def test_proc_ancestors_empty_without_ps(monkeypatch):
    monkeypatch.setattr(macos_geom, "_proc_parents", lambda: {})
    assert macos_geom.proc_ancestors(1234) == set()


def test_proc_ancestors_walks_mocked_tree(monkeypatch):
    # 4321 -> 300 -> 200 -> 1 (init); the walk collects the chain, stops at root
    monkeypatch.setattr(macos_geom, "_proc_parents",
                        lambda: {4321: 300, 300: 200, 200: 1, 999: 998})
    assert macos_geom.proc_ancestors(4321) == {4321, 300, 200}


def test_proc_ancestors_survives_a_cycle(monkeypatch):
    # a bogus ppid cycle must terminate (cur-in-acc guard), not spin forever
    monkeypatch.setattr(macos_geom, "_proc_parents", lambda: {10: 20, 20: 10})
    assert macos_geom.proc_ancestors(10) == {10, 20}


def test_proc_ancestors_respects_max_hops(monkeypatch):
    chain = {i: i + 1 for i in range(2, 100)}
    monkeypatch.setattr(macos_geom, "_proc_parents", lambda: chain)
    assert len(macos_geom.proc_ancestors(2, max_hops=5)) == 5


def test_proc_ancestors_walks_real_process_tree():
    if sys.platform != "darwin":
        return
    acc = macos_geom.proc_ancestors(os.getpid())
    assert os.getpid() in acc
    assert len(acc) >= 1
