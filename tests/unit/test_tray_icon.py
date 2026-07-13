import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from claudlet.core import creature as C
from claudlet import pet as P

_app = QApplication.instance() or QApplication(sys.argv)


def test_state_icon_renders_for_every_state():
    p = P.Pet()
    try:
        for st in C.STATES:
            icon = p._state_icon(st)
            assert not icon.isNull(), st
            assert not icon.pixmap(32, 32).isNull(), st
    finally:
        p._cleanup()


def test_tray_absent_offscreen_is_safe():
    # offscreen has no system tray -> tray is None and updates are no-ops
    p = P.Pet()
    try:
        assert p.tray is None
        p._update_tray_icon()          # must not raise
    finally:
        p._cleanup()
