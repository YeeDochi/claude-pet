import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication
from claudlet.core import creature as C

_app = QApplication.instance() or QApplication(sys.argv)

EXPECTED = {"thinking", "work_computer", "work_search", "work_web",
            "work_agent", "work_skill", "attention", "idle",
            "celebrate", "sleeping", "error", "walk", "held", "falling"}


def test_states_present():
    assert EXPECTED.issubset(set(C.STATES)), EXPECTED - set(C.STATES)
    assert "waiting" not in C.STATES   # renamed to sleeping


def test_every_state_renders_without_error():
    img = QImage(C.GRID_W * 6, C.GRID_H * 6, QImage.Format.Format_ARGB32)
    for st in EXPECTED:
        for frame in (0, 7, 50, 100):
            for facing in (1, -1):     # left-facing mirrors the body only
                p = QPainter(img)
                C.draw_creature(p, 0, 0, 6, st, frame, facing=facing)
                p.end()


def test_speech_states_have_lines():
    assert set(C.SPEECH) <= set(C.STATES)
    for st in C.SPEECH:
        assert C.SPEECH[st]


NEW_MOTIONS = {"jump", "wave", "sing", "juggle", "float"}


def test_new_motions_present():
    assert NEW_MOTIONS.issubset(set(C.STATES)), NEW_MOTIONS - set(C.STATES)


def test_new_motions_render_without_error():
    img = QImage(C.GRID_W * 6, C.GRID_H * 6, QImage.Format.Format_ARGB32)
    for st in NEW_MOTIONS:
        for frame in (0, 7, 50, 100):
            for facing in (1, -1):
                p = QPainter(img)
                C.draw_creature(p, 0, 0, 6, st, frame, facing=facing)
                p.end()


NEW_LOOKS = {"climbdown", "strain", "leap"}


def test_new_looks_present():
    assert NEW_LOOKS.issubset(set(C.STATES)), NEW_LOOKS - set(C.STATES)


def test_new_looks_render_without_error():
    img = QImage(C.GRID_W * 6, C.GRID_H * 6, QImage.Format.Format_ARGB32)
    for st in NEW_LOOKS:
        for frame in (0, 7, 50, 100):
            for facing in (1, -1):
                p = QPainter(img)
                C.draw_creature(p, 0, 0, 6, st, frame, facing=facing)
                p.end()


def test_speech_language_switch():
    # set_lang flips the bubble text; default is Korean
    C.set_lang("ko")
    assert C._speech("thinking") == "고민중…"
    C.set_lang("en")
    assert C._speech("thinking") == "hmm…"
    assert C._speech("asking") == "yeah?"
    C.set_lang("bogus")          # unknown -> Korean fallback
    assert C._speech("thinking") == "고민중…"
    C.set_lang("ko")             # restore default for other tests


def test_energy_param_renders_all_levels_without_error():
    img = QImage(C.GRID_W * 6, C.GRID_H * 6, QImage.Format.Format_ARGB32)
    for st in ("idle", "walk"):
        for energy in (0.0, 0.5, 1.0):
            for frame in (0, 30, 90):
                p = QPainter(img)
                C.draw_creature(p, 0, 0, 6, st, frame, energy=energy)
                p.end()


def test_energy_defaults_to_full_and_is_keyword():
    import inspect
    sig = inspect.signature(C.draw_creature)
    assert sig.parameters["energy"].default == 1.0


def test_energy_droop_changes_render_and_full_matches_default():
    from PyQt6.QtGui import QImage, QPainter

    def _render(state, frame, **kw):
        img = QImage(C.GRID_W * 6, C.GRID_H * 6, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        C.draw_creature(p, 0, 0, 6, state, frame, **kw)
        p.end()
        return bytes(img.constBits().asarray(img.sizeInBytes()))

    for state in ("idle", "walk"):
        # a tired creature must render differently from a fresh one at some frame
        assert any(_render(state, f, energy=0.0) != _render(state, f, energy=1.0)
                   for f in (0, 20, 45, 60, 90)), f"{state}: droop had no visible effect"
        # energy=1.0 must be byte-identical to omitting energy (backward compat)
        for f in (0, 20, 45, 60, 90):
            assert _render(state, f, energy=1.0) == _render(state, f), \
                f"{state} frame {f}: energy=1.0 differs from default"
