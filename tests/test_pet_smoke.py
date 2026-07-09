import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from PyQt6.QtWidgets import QApplication
import pet as P

_app = QApplication.instance() or QApplication(sys.argv)


def test_pet_constructs_and_uses_engine():
    p = P.Pet()
    assert hasattr(p, "engine")
    # feed a PreToolUse and confirm the engine drives the claude state
    p._handle_event({"event": "PreToolUse", "session": "a", "tool_name": "Bash"})
    p._tick()
    assert p.claude_state == "work_computer"
    p._cleanup()


def test_pet_is_session_and_host_aware():
    p = P.Pet(session_id="sess-x", host="vscode")
    try:
        assert p.host_classes == ["code"]
        assert p.sock_path.endswith("claude-pet-sess-x.sock")
        assert p._wtitle == "claude-pet-sess-x"
    finally:
        p._cleanup()


def test_sessionend_quit_is_cancelled_by_later_event():
    p = P.Pet(session_id="q1")
    try:
        p._handle_event({"event": "SessionEnd", "session": "q1"})
        assert p._quit_timer is not None          # quit armed
        p._handle_event({"event": "UserPromptSubmit", "session": "q1"})
        assert p._quit_timer is None              # a later event cancels it
    finally:
        p._cleanup()


def test_bounds_desktop_vs_contained():
    import windows as W
    p = P.Pet(session_id="pb")
    try:
        # desktop: with no polled windows, floor is the screen floor
        p._wins = []
        left, right, top, floor = p._bounds()
        assert left == p.screen_rect.left()
        # contained: bounds come from the window rect
        p._contain = W.Win("0x1", 300, 400, 500, 350, "X")
        cl, cr, ct, cf = p._bounds()
        assert cl == 300 and ct == 400
        assert cr <= 300 + 500 and cf <= 400 + 350
    finally:
        p._cleanup()


def test_roam_falls_when_surface_dropped_away():
    p = P.Pet(session_id="rf")
    try:
        p._wins = []
        _l, _r, _t, floor = p._bounds()
        p.y = floor - 300          # airborne (surface is far below)
        p.mode = "roam"
        p.walk_pause = 5           # would have early-returned before the fix
        p._roam()
        assert p.mode == "thrown"  # falls instead of teleporting
    finally:
        p._cleanup()
