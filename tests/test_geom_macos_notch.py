from claudlet.platform.geom import macos


def test_no_notch_when_safe_top_zero():
    assert macos.notch_geometry(1512, 0, None, None) is None


def test_notch_from_aux_areas():
    # aux_left ends at 656, aux_right starts at 856 -> 200-wide notch, 38 tall
    assert macos.notch_geometry(1512, 38, 656, 856) == (656, 0, 200, 38)


def test_notch_fallback_centered_when_aux_missing():
    # safe_top>0 but aux unknown -> centered NOTCH_FALLBACK_W band
    x, y, w, h = macos.notch_geometry(1512, 38, None, None)
    assert w == macos.NOTCH_FALLBACK_W
    assert y == 0 and h == 38
    assert x == (1512 - macos.NOTCH_FALLBACK_W) // 2  # 656


def test_notch_rect_none_without_appkit(monkeypatch):
    monkeypatch.setattr(macos, "AppKit", None)
    assert macos.notch_rect() is None
