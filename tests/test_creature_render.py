import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication
import creature as C

_app = QApplication.instance() or QApplication(sys.argv)

EXPECTED = {"thinking", "work_computer", "work_search", "work_web",
            "work_agent", "work_skill", "attention", "idle",
            "celebrate", "sleeping", "error", "walk"}


def test_states_present():
    assert EXPECTED.issubset(set(C.STATES)), EXPECTED - set(C.STATES)
    assert "waiting" not in C.STATES   # renamed to sleeping


def test_every_state_renders_without_error():
    img = QImage(C.GRID_W * 6, C.GRID_H * 6, QImage.Format.Format_ARGB32)
    for st in EXPECTED:
        for frame in (0, 7, 50, 100):
            p = QPainter(img)
            C.draw_creature(p, 0, 0, 6, st, frame)
            p.end()


def test_speech_states_have_lines():
    assert set(C.SPEECH) <= set(C.STATES)
    for st in C.SPEECH:
        assert C.SPEECH[st]
