import sys, os, time, socket, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint
import pet as P
import hostinfo

_app = QApplication.instance() or QApplication(sys.argv)


class _LeftRelease:
    def button(self):
        return Qt.MouseButton.LeftButton


def test_pet_constructs_and_uses_engine():
    p = P.Pet()
    assert hasattr(p, "engine")
    # feed a PreToolUse and confirm the engine drives the claude state
    p._handle_event({"event": "PreToolUse", "session": "a", "tool_name": "Bash"})
    p._tick()
    assert p.claude_state == "work_computer"
    p._cleanup()


def test_pet_answers_liveness_ping():
    # the pet must reply to {"cmd":"ping"} with its banner so hostinfo.pet_alive
    # can tell a real pet apart from an unrelated process on a reused stale port.
    p = P.Pet(session_id="ping1")
    try:
        port = p.srv.getsockname()[1]
        c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c.settimeout(1.0)
        c.connect((hostinfo.LOOPBACK, port))
        c.sendall(hostinfo.PING)
        c.shutdown(socket.SHUT_WR)
        p._on_conn()                      # simulate the QSocketNotifier firing
        reply = c.recv(256).decode()
        c.close()
        assert hostinfo.BANNER_MARK in reply
        assert p._quit_timer is None      # a ping is NOT a Claude event
    finally:
        p._cleanup()


def test_pid_alive_posix_and_windows(monkeypatch):
    if os.name != "nt":
        assert P._pid_alive(os.getpid()) is True     # this test process is alive
    # Windows branch: liveness comes from a process snapshot, never os.kill
    # (which on Windows would Ctrl+C the target instead of probing it).
    monkeypatch.setattr(P.os, "name", "nt")
    fake = types.ModuleType("windows_win32")
    fake.proc_table = lambda: {4321: ("claude.exe", 1)}
    monkeypatch.setitem(sys.modules, "windows_win32", fake)
    assert P._pid_alive(4321) is True
    assert P._pid_alive(9999) is False               # absent from snapshot -> dead
    fake.proc_table = lambda: {}                      # snapshot failed -> assume alive
    assert P._pid_alive(9999) is True


def test_activate_claude_windows_fallback_uses_win32_classes():
    # With no pid-pinned host window, the Windows click-to-focus fallback must
    # use hostinfo.win_classes (real Win32 class names) rather than the
    # Linux/KWin-flavored self.host_classes ("code" never matches any real
    # Win32 class). "unknown" (native terminals: cmd.exe/PowerShell/Windows
    # Terminal) is the one host with a distinctive-enough Win32 class to
    # trust a fallback guess.
    p = P.Pet(session_id="wf1", host="unknown")
    try:
        p._host_wid = None

        class _FakeGeom:
            def __init__(self):
                self.calls = []

            def find_window_by_class(self, classes):
                self.calls.append(classes)
                return 42

            def activate_hwnd(self, hwnd):
                self.activated = hwnd

        fake = _FakeGeom()
        p._win32_geom = fake
        p._activate_claude_windows()
        assert fake.calls == [hostinfo.win_classes("unknown")]
        assert fake.calls[0] == ["cascadia_hosting_window_class", "consolewindowclass"]
        assert fake.activated == 42
    finally:
        p._cleanup()


def test_activate_claude_windows_no_guess_for_ambiguous_host():
    # VS Code's Win32 class ("chrome_widgetwin_1") is shared by every other
    # Electron/Chromium app -- win_classes("vscode") is [] on purpose, and
    # the fallback must pass that through rather than substituting a guess.
    p = P.Pet(session_id="wf2", host="vscode")
    try:
        p._host_wid = None

        class _FakeGeom:
            def __init__(self):
                self.calls = []

            def find_window_by_class(self, classes):
                self.calls.append(classes)
                return None

            def activate_hwnd(self, hwnd):
                self.activated = hwnd

        fake = _FakeGeom()
        p._win32_geom = fake
        p._activate_claude_windows()
        assert fake.calls == [[]]
        assert not hasattr(fake, "activated")
    finally:
        p._cleanup()


def test_pet_is_session_and_host_aware():
    p = P.Pet(session_id="sess-x", host="vscode")
    try:
        assert p.host_classes == ["code"]
        assert p.port_file.endswith("claude-pet-sess-x.port")
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


def test_visibility_hides_with_ridden_window():
    import windows as W
    p = P.Pet(session_id="hv")
    try:
        p._geom_active = True                      # pretend a geometry feed is active
        host = W.Win("host", 100, 100, 400, 300, "browser", 1)
        top = W.Win("top", 0, 0, 4000, 2000, "code", 2)    # maximized, stacked above
        p._contain = host                         # pet lives in this window
        p.x, p.y = 150.0, 150.0                    # positioned inside the window
        # ridden window fully covered -> hide
        p._wins = [host, top]
        p._update_visibility()
        assert p._hidden_for_win is True
        # covering window gone -> show
        p._wins = [host]
        p._update_visibility()
        assert p._hidden_for_win is False
        # ridden window minimized/closed (drops from the feed) -> hide
        p._wins = []
        p._update_visibility()
        assert p._hidden_for_win is True
    finally:
        p._cleanup()


def test_visibility_partial_cover_masks():
    import windows as W
    p = P.Pet(session_id="hvp")
    try:
        p._geom_active = True
        host = W.Win("host", 0, 0, 400, 300, "browser", 1)
        p._contain = host
        p.x, p.y = 0.0, 0.0
        # a higher window covers only PART of the pet's rect (from x=60 rightward)
        cover = W.Win("cov", 60, 0, 400, 300, "code", 2)
        p._wins = [host, cover]
        p._update_visibility()
        assert p._hidden_for_win is False     # still partly visible
        assert p._masked is True              # clipped to the exposed sliver
        # cover removed -> full again, mask dropped
        p._wins = [host]
        p._update_visibility()
        assert p._masked is False
    finally:
        p._cleanup()


def test_visibility_perched_on_top_not_clipped_by_its_window():
    import windows as W
    p = P.Pet(session_id="hvt")
    try:
        p._geom_active = True
        p._contain = None
        X = W.Win("X", 0, 500, 800, 400, "editor", 1)   # top edge at y=500
        p.x = 100.0
        p.y = float(500 - P.FOOT_Y)                       # feet on X's top edge
        p._wins = [X]
        p._update_visibility()
        # standing ON TOP of X with nothing above -> body must NOT be clipped
        assert p._hidden_for_win is False and p._masked is False
        # a window raised above X, over the pet's body -> now occluded
        Y = W.Win("Y", 0, 300, 800, 400, "code", 2)
        p._wins = [X, Y]
        p._update_visibility()
        assert p._masked is True or p._hidden_for_win is True
    finally:
        p._cleanup()


def test_visibility_desktop_never_hides():
    import windows as W
    p = P.Pet(session_id="hv2")
    try:
        p._geom_active = True
        p._contain = None                         # roaming the wallpaper, not on a window
        p.x, p.y = 100.0, 100.0
        p._wins = [W.Win("big", 0, 0, 4000, 2000, "code", 2)]   # maximized window exists
        p._update_visibility()
        assert p._hidden_for_win is False         # not perched on it -> stays visible
    finally:
        p._cleanup()


def test_visibility_off_without_feed():
    import windows as W
    p = P.Pet(session_id="hv3")
    try:
        p._geom_active = False                     # no geometry feed
        p._contain = W.Win("host", 100, 100, 400, 300, "x", 1)
        p._wins = []                              # would hide if the feed were active
        p._update_visibility()
        assert p._hidden_for_win is False
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


def test_motion_command_overrides_render_state():
    p = P.Pet(session_id="m1")
    try:
        p._handle_event({"cmd": "motion", "motion": "jump", "dur": 2.0})
        assert p._motion == "jump"
        p.mode = "roam"
        p._tick()
        assert p._render_state == "jump"
    finally:
        p._cleanup()


def test_motion_command_does_not_cancel_quit_timer():
    p = P.Pet(session_id="m2")
    try:
        p._handle_event({"event": "SessionEnd", "session": "m2"})
        assert p._quit_timer is not None
        p._handle_event({"cmd": "motion", "motion": "wave", "dur": 1.0})
        assert p._quit_timer is not None      # a motion cmd is NOT a Claude event
        assert p._motion == "wave"
    finally:
        p._cleanup()


def test_float_toggle_and_stop_restores_gravity():
    p = P.Pet(session_id="m3")
    try:
        p._handle_event({"cmd": "motion", "motion": "float", "dur": 0})
        assert p._floating is True
        assert p._motion is None          # float is a mode, not a render override
        p._handle_event({"cmd": "motion", "motion": None, "dur": 0})
        assert p._floating is False
        assert p.mode == "thrown"         # stop restores gravity
    finally:
        p._cleanup()


def test_float_rises_and_hovers_without_falling():
    p = P.Pet(session_id="m4")
    try:
        p.mode = "roam"
        p.y = float(p.floor_y)
        p._handle_event({"cmd": "motion", "motion": "float", "dur": 0})
        # rose off the floor, velocity killed, still roam (so hovering engages)
        assert p.y < p.floor_y
        assert p.vy == 0.0 and p.mode == "roam"
        hover_y = p.y
        # ticking must NOT pull it down (gravity is skipped while floating)
        for _ in range(5):
            p._tick()
        assert p.y == hover_y            # hovers in place, no fall, no snap
    finally:
        p._cleanup()


def test_menu_helpers_play_motion_and_toggle_float():
    p = P.Pet(session_id="m6")
    try:
        p._play_motion("jump", 2.0)
        assert p._motion == "jump"
        # float toggle flips on, then off (off restores gravity)
        assert p._floating is False
        p._toggle_float()
        assert p._floating is True
        p._toggle_float()
        assert p._floating is False and p.mode == "thrown"
    finally:
        p._cleanup()


def test_follow_toggle_and_tick_glides_toward_cursor():
    p = P.Pet(session_id="m7")
    try:
        assert p._follow is False
        p._toggle_follow()
        assert p._follow is True
        # place the pet far from the cursor; ticking must glide it toward the
        # cursor (position changes) and stay within the desktop, without crashing
        p.mode = "roam"
        p.x, p.y = float(p.screen_rect.right() - p.w), float(p.floor_y)
        start = (p.x, p.y)
        for _ in range(3):
            p._tick()
        assert (p.x, p.y) != start
        assert p.screen_rect.left() <= p.x <= p.screen_rect.right()
        p._toggle_follow()
        assert p._follow is False
    finally:
        p._cleanup()


def test_small_window_centres_pet_instead_of_jutting():
    import windows as W
    p = P.Pet(session_id="sm")
    try:
        # window narrower AND shorter than the pet -> centre, don't clamp to a corner
        p._contain = W.Win("0x1", 500, 500, 20, 20, "X")
        left, right, top, floor = p._bounds()
        assert left == right                 # no horizontal travel room
        assert top == floor
        assert left < 500 and top < 500      # centred (negative offset), not stuck at c.x
    finally:
        p._cleanup()


def test_work_search_anchors_locally_and_clears():
    p = P.Pet(session_id="ws")
    try:
        p.mode = "roam"
        p._handle_event({"event": "PreToolUse", "session": "ws", "tool_name": "Grep"})
        p._tick()
        assert p.claude_state == "work_search"
        assert p._search_anchor is not None          # anchored on entering search
        # leaving search clears the anchor so the next episode re-anchors
        p._handle_event({"event": "UserPromptSubmit", "session": "ws"})
        p._handle_event({"cmd": "motion", "motion": None})   # ensure not floating
        for _ in range(3):
            p._tick()
        if p.claude_state != "work_search":
            assert p._search_anchor is None
    finally:
        p._cleanup()


def test_roam_wanders_locally_within_bounds():
    import random
    random.seed(20260710)
    p = P.Pet(session_id="rw")
    try:
        p._wins = []
        p.mode = "roam"
        p.claude_state = "idle"
        p.target_x = None
        left, right, *_ = p._bounds()
        p.x = float((left + right) / 2)      # start mid-screen
        start_x = p.x
        picked = None
        for _ in range(2000):
            p._roam()
            if p.target_x is not None:
                picked = p.target_x
                break
        assert picked is not None            # eventually decided to wander
        assert left <= picked <= right       # target stays on-screen
        assert abs(picked - start_x) <= 900 + 1   # local wander, not teleport
        assert 1.8 <= p._walk_speed <= 2.8   # per-trip pace variety
    finally:
        p._cleanup()


def test_cursor_feed_parsed_and_used():
    p = P.Pet(session_id="m12")
    try:
        assert p._cursor is None                 # falls back to QCursor until fed
        p._on_cursor("640,480")
        assert p._cursor == (640, 480)
        assert p._cursor_pos() == (640, 480)     # compositor value preferred
        p._on_cursor("garbage")                  # must not crash or corrupt
        assert p._cursor == (640, 480)
    finally:
        p._cleanup()


def test_floating_follow_tracks_x_and_y():
    p = P.Pet(session_id="m11")
    try:
        p.mode = "roam"
        p._follow = True
        p._floating = True
        p.x = float(p.screen_rect.right() - p.w)
        p.y = float(p.screen_rect.bottom() - p.h)
        start_y = p.y
        for _ in range(3):
            p._tick()
        # unlike grounded follow (x only), floating follow also moves in y
        assert p.y != start_y
        assert p._render_state == "float"
    finally:
        p._cleanup()


def test_fling_inside_window_bounces_within_it():
    import windows as W
    p = P.Pet(session_id="m8")
    try:
        p._wins = [W.Win("0x1", 0, 0, 4000, 2000, "X")]   # window under the pet
        p.x, p.y = 100.0, 100.0
        p._moved = True
        p._floating = False
        now = time.monotonic()
        # fast flick: 60px in 0.02s -> speed well over the fling threshold
        p._vel_samples = [(now, QPoint(0, 0)), (now + 0.02, QPoint(60, 0))]
        p.mouseReleaseEvent(_LeftRelease())
        assert p.mode == "thrown"        # thrown -> bounces off the interior
        assert p._contain is not None    # but stays inside the window
    finally:
        p._cleanup()


def test_gentle_drop_on_window_perches():
    import windows as W
    p = P.Pet(session_id="m9")
    try:
        p._wins = [W.Win("0x1", 0, 0, 4000, 2000, "X")]
        p.x, p.y = 100.0, 100.0
        p._moved = True
        p._floating = False
        now = time.monotonic()
        # slow drop: 2px over 0.1s -> below the fling threshold
        p._vel_samples = [(now, QPoint(0, 0)), (now + 0.1, QPoint(2, 0))]
        p.mouseReleaseEvent(_LeftRelease())
        assert p._contain is not None    # settled into the window
        assert p.mode == "roam"
    finally:
        p._cleanup()


def test_drag_centre_out_of_window_leaves_it():
    import windows as W
    p = P.Pet(session_id="m10")
    try:
        p._contain = W.Win("0x1", 0, 0, 100, 100, "X")   # was living in a window
        p._wins = [p._contain]
        p.x, p.y = 3000.0, 500.0        # centre now well outside the window
        p._moved = True
        p._floating = False
        now = time.monotonic()
        p._vel_samples = [(now, QPoint(0, 0)), (now + 0.1, QPoint(1, 0))]
        p.mouseReleaseEvent(_LeftRelease())
        assert p._contain is None        # left the window
        assert p.mode == "thrown"
    finally:
        p._cleanup()


def test_float_still_shows_claude_animation():
    p = P.Pet(session_id="m5")
    try:
        # a working Claude state while floating should still render as working,
        # not be masked by the float mode
        p._handle_event({"event": "PreToolUse", "session": "m5", "tool_name": "Bash"})
        p._handle_event({"cmd": "motion", "motion": "float", "dur": 0})
        p._tick()
        assert p._floating is True
        assert p._render_state == "work_computer"   # animation NOT masked by float
        # and a transient motion still plays over the float
        p._handle_event({"cmd": "motion", "motion": "jump", "dur": 2.0})
        p._tick()
        assert p._render_state == "jump"
    finally:
        p._cleanup()
