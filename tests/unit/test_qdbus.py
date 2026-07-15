from claudlet.platform import qdbus


def _which_of(available):
    """Fake shutil.which: returns a path for names in `available`, else None."""
    avail = set(available)
    return lambda name: (f"/usr/bin/{name}" if name in avail else None)


def test_resolve_prefers_first_available_in_order():
    # qdbus6 present -> chosen even though later candidates also exist
    got = qdbus.resolve(("qdbus6", "qdbus-qt6", "qdbus"),
                        _which_of({"qdbus6", "qdbus"}))
    assert got == "qdbus6"


def test_resolve_falls_through_to_next_candidate():
    # qdbus6 absent (e.g. distro ships qdbus-qt6) -> pick the next present one
    got = qdbus.resolve(("qdbus6", "qdbus-qt6", "qdbus"),
                        _which_of({"qdbus-qt6"}))
    assert got == "qdbus-qt6"


def test_resolve_returns_none_when_all_absent():
    got = qdbus.resolve(("qdbus6", "qdbus-qt6", "qdbus"), _which_of(set()))
    assert got is None


def test_qdbus_bin_falls_back_to_qdbus6_when_none_found(monkeypatch):
    # last-resort name so callers still build a command (fails soft at exec).
    qdbus.qdbus_bin.cache_clear()
    monkeypatch.setattr(qdbus.shutil, "which", lambda name: None)
    assert qdbus.qdbus_bin() == "qdbus6"
    qdbus.qdbus_bin.cache_clear()


def test_qdbus_bin_returns_resolved_name(monkeypatch):
    qdbus.qdbus_bin.cache_clear()
    monkeypatch.setattr(qdbus.shutil, "which",
                        _which_of({"qdbus-qt6"}))
    assert qdbus.qdbus_bin() == "qdbus-qt6"
    qdbus.qdbus_bin.cache_clear()
