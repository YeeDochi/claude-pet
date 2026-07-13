import sys, os, time, socket, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint
from claudlet import pet as P
from claudlet.core import hostinfo

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


def test_companion_follows_when_far_and_stops_when_near():
    # only walks toward the pet once the gap exceeds FOLLOW_START, converges to
    # within FOLLOW_STOP, then stays put (hysteresis) — no jitter, and crucially
    # no facing-based side jump when the pet turns.
    c = P.Companion()
    try:
        c.x, c.y = 0.0, 0.0
        far = 1000.0                         # pet centre far to the right
        c.advance(far, 0.0)
        assert c.x > 0 and c._state == "walk"      # started walking toward it
        for _ in range(600):
            c.advance(far, 0.0)
        gap = abs(far - (c.x + c.w / 2.0))
        assert gap <= P.COMPANION_FOLLOW_STOP + P.COMPANION_SPEED   # settled at the stop gap
        assert c._state != "walk"                  # stopped
        # a target just inside FOLLOW_START must NOT restart the walk (hysteresis)
        settled = c.x
        near = (c.x + c.w / 2.0) + P.COMPANION_FOLLOW_STOP + 5
        c.advance(near, 0.0)
        assert c.x == settled
    finally:
        c.close()


def test_companion_fling_bounces_with_own_physics():
    # thrown: the companion gets the pet's launch velocity and flies its own arc
    # with the real physics engine — it hits the floor and BOUNCES (breakout
    # style) rather than lerp-trailing, and eventually settles back to following.
    c = P.Companion()
    try:
        c.x, c.y = 100.0, 100.0
        c.fling(6.0, 0.0)
        assert c._air
        floor = 400.0
        bounced = False
        prev_vy = 0.0
        for _ in range(2000):
            c.fly(0.0, 2000.0, 0.0, floor)
            if prev_vy > 0 and c.vy < 0:
                bounced = True                   # downward -> upward = floor bounce
            prev_vy = c.vy
            if not c._air:
                break
        assert bounced
        assert not c._air                        # settled back to ground mode
        assert abs(c.y - floor) < 2.0
    finally:
        c.close()


def test_companion_stands_on_pets_feet_line(monkeypatch):
    # with no windows around, the companion resolves its OWN ground to the
    # bare screen floor -- which happens to be the same line the pet itself
    # stands on, so this still reduces to "feet on the pet's feet line".
    p = P.Pet(session_id="cmpwin")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        p.mode = "roam"
        p.x, p.y = 400.0, p.floor_y               # pet resting on the real floor
        p._sync_companion()
        c = p._companion
        expected = p.y + P.FOOT_Y * (1.0 - P.COMPANION_U / float(P.U))
        assert abs(c.y - expected) < 1.0         # feet on the (shared) floor line
    finally:
        p._cleanup()


def test_companion_blinks_over_when_a_level_apart(monkeypatch):
    # landed a throw on a different level: it first TRIES to walk itself back
    # (Task 6 grace period) and only teleports beside the pet after failing to
    # reunite for COMPANION_REUNITE_TICKS.
    p = P.Pet(session_id="cmpblink")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        p.mode = "roam"
        p._sync_companion()
        c = p._companion
        c.x, c.y = p.x + 500, p.y + P.COMPANION_BLINK_DY + 200   # far + a level below
        for _ in range(P.COMPANION_REUNITE_TICKS):
            c.y = p.y + P.COMPANION_BLINK_DY + 200   # stays stranded on its level
            p._sync_companion()
        assert abs((c.x + c.w / 2.0) - (p.x + p.w / 2.0)) < c.w  # blinked to the pet
    finally:
        p._cleanup()


def test_companion_walks_back_before_blinking(monkeypatch):
    p = P.Pet(session_id="cmpwalkback")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        p._wins = []                                  # flat floor, no windows
        p.x = 100.0; p.y = p.floor_y
        p._sync_companion()
        c = p._companions[0]
        c.x = 900.0                                     # far from the pet, SAME level
        x0 = c.x
        p._sync_companion()
        # same level -> it should WALK toward the pet, not blink-snap to pet.x
        assert c.x != p.x + (p.w - c.w) / 2.0           # did not teleport
        assert c.x < x0                                 # moved toward the pet (leftward)
    finally:
        p._cleanup()


def test_separated_companion_blinks_only_after_effort(monkeypatch):
    p = P.Pet(session_id="cmpreunite")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        p._wins = []; p.x = 100.0; p.y = p.floor_y
        p._sync_companion(); c = p._companions[0]
        # strand it on a different level (as if it landed a throw up high)
        c.y = p.floor_y - 400; c.x = 900.0
        # first tick while separated: it should NOT immediately blink
        p._sync_companion()
        assert c._reunite_ticks >= 1
        assert c.x != p.x + (p.w - c.w) / 2.0            # not teleported yet
        # after exceeding the budget while still separated: it blinks back
        c._reunite_ticks = P.COMPANION_REUNITE_TICKS
        c.y = p.floor_y - 400
        p._sync_companion()
        assert abs(c.x - (p.x + (p.w - c.w) / 2.0)) < 1.0   # blinked to the pet
    finally:
        p._cleanup()


def test_companion_rests_on_its_own_window(monkeypatch):
    # one active agent -> one companion; a window sits under the companion's
    # OWN column but NOT under the pet's -> the companion must rest on that
    # window's top, not float/clip at the pet's shared floor level.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cmpown")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        p.x, p.y = 50.0, p.floor_y                 # pet on the floor, left
        p._wins = [W.Win("w1", 500, 250, 300, 400, "code", 1)]  # window far right
        p._sync_companion()
        c = p._companion
        c.x = 560.0                                # move companion over the window
        p._sync_companion()
        # companion's feet should be on the window top (~y=250), well above
        # the pet's own floor line.
        assert c.y < p.floor_y - 100
    finally:
        p._cleanup()


def test_companion_perch_identity_on_a_window(monkeypatch):
    # PERCH-CASE identity: the pet resting ON a window, a companion in the SAME
    # window column -> the companion's feet sit FLUSH on that window top, and
    # its ground reduces to the pet's shared feet line (identity holds on a
    # window perch, not only on the bare floor).
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cmpperch")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        win = W.Win("w1", 100, 300, 400, 400, "code", 1)   # window top y=300
        p._wins = [win]
        p.x, p.y = 200.0, 100.0             # above the window, within its column
        _l, _r, _t, floor = p._bounds()     # perched on the window top
        p.y = floor                         # settle there (feet flush at y=300)
        p._sync_companion()
        c = p._companion
        c.x = 200.0                         # same column as the pet
        p._sync_companion()
        ratio = P.COMPANION_U / float(P.U)
        expected = p.y + P.FOOT_Y * (1.0 - ratio)     # the pet's shared feet line
        assert abs(c.y - expected) < 1.0              # identity holds on the perch
        assert abs((c.y + P.FOOT_Y * ratio) - win.y) < 1.0   # feet flush on the top
    finally:
        p._cleanup()


def test_companion_rests_on_nearer_of_overlapping_windows(monkeypatch):
    # two overlapping windows in the companion's column -> it rests on the
    # NEARER (lower) one, never floating up to the global-topmost.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cmpovl")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        p.x, p.y = 50.0, p.floor_y                     # pet on the floor, left
        hi = W.Win("hi", 500, 150, 300, 600, "code", 1)   # top y=150 (far/high)
        lo = W.Win("lo", 500, 450, 300, 300, "code", 2)   # top y=450 (nearer floor)
        p._wins = [hi, lo]
        p._sync_companion()
        c = p._companion
        c.x = 560.0                                    # over BOTH windows
        p._sync_companion()
        ratio = P.COMPANION_U / float(P.U)
        # feet flush on the NEARER (lower) window top, not the topmost one
        assert abs((c.y + P.FOOT_Y * ratio) - lo.y) < 1.0
        assert c.y > (hi.y - P.FOOT_Y * ratio) + 50    # clearly not the high one
    finally:
        p._cleanup()


def test_companion_gathers_beside_held_pet(monkeypatch):
    # lifting the pet makes the companion hurry to the cursor and dangle beside
    # it, so a subsequent throw launches the two side by side.
    p = P.Pet(session_id="cmpheld")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        p._sync_companion()
        c = p._companion
        c.x, c.y = p.x - 600, p.y + 300          # far away on the ground
        p.mode = "held"
        d0 = abs((c.x + c.w / 2) - (p.x + p.w / 2)) + abs(c.y - p.y)
        for _ in range(200):
            p._sync_companion()
        d1 = abs((c.x + c.w / 2) - (p.x + p.w / 2)) + abs(c.y - p.y)
        assert d1 < d0                            # closed in on the held pet
        assert c._state == "held"                 # dangling beside it
    finally:
        p._cleanup()


def test_pet_throw_flings_companion_once(monkeypatch):
    p = P.Pet(session_id="cmpfling")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        # deterministic spawn away from the walls: facing right -> the companion
        # spawns to the LEFT, so a rightward throw carries it into open space
        # (not straight into a wall it would bounce off).
        p.x = float(p.screen_rect.left() + 300)
        p.facing = 1
        p._sync_companion()                      # create companion (roam)
        p.mode = "thrown"
        p.vx, p.vy = 9.0, -4.0
        p._sync_companion()
        c = p._companion
        # launched with the pet's velocity (one physics tick may already have
        # applied drag/gravity — direction is what matters)
        assert c._air and c.vx > 0 and c.vy < 0
    finally:
        p._cleanup()


def test_companion_shows_rest_state_when_settled():
    # when not walking, the companion mirrors the subagent's activity (rest_state)
    c = P.Companion()
    try:
        c.x = c.y = 0.0
        c.advance(c.x + c.w / 2.0, 0.0, rest_state="work_computer")   # target on top -> settled
        assert c._state == "work_computer"
    finally:
        c.close()


def test_companion_paints_without_error():
    c = P.Companion()
    try:
        c.x = c.y = 5.0
        px = c.grab()                       # runs its paintEvent offscreen
        assert not px.isNull()
    finally:
        c.close()


def test_pet_shows_companion_only_while_agents_active(monkeypatch):
    p = P.Pet(session_id="cmp")
    try:
        active = {"n": 0}
        monkeypatch.setattr(p.engine, "agents_active", lambda: active["n"])
        p._sync_companion()
        assert p._companion is None
        active["n"] = 1
        p._sync_companion()
        assert p._companion is not None and p._companion.isVisible()
        active["n"] = 0
        p._sync_companion()
        assert p._companion is None            # closed and removed
    finally:
        p._cleanup()


def test_companion_waves_goodbye_then_closes(monkeypatch):
    # an agent finishing doesn't blink its companion away: it celebrates
    # ("다 됐다!") for BYE_DUR, then the window closes.
    p = P.Pet(session_id="cmpbye")
    try:
        active = {"n": 1}
        monkeypatch.setattr(p.engine, "agents_active", lambda: active["n"])
        p._sync_companion()
        c = p._companion
        active["n"] = 0
        p._sync_companion()
        assert p._companions == [] and p._departing == [c]
        assert c._state == "celebrate" and c.isVisible()   # announcing the finish
        monkeypatch.setattr(P, "COMPANION_BYE_DUR", 0.0)   # not for the deadline set above
        c._depart_until = 0.0                              # force the deadline past
        p._sync_companion()
        assert p._departing == []                          # closed and removed
    finally:
        p._cleanup()


def test_companion_flung_inside_window_stays_inside(monkeypatch):
    # flung while the pet lives in a window: the companion bounces within that
    # window's interior instead of sailing out to the screen edges.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cmpbounce")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        win = W.Win("w1", 400, 300, 500, 400, "konsole", 1)
        p._contain = win
        p.x, p.y = 500.0, 400.0
        p._sync_companion()                     # create companion near the pet
        c = p._companion
        p.mode = "thrown"
        p.vx, p.vy = 25.0, -10.0                # a hard fling
        for _ in range(300):
            p._sync_companion()
            assert win.x - 1 <= c.x <= win.x + win.w - c.w + 1
            if not c._air:
                break
    finally:
        p._cleanup()


def test_companion_chain_grows_with_agents_and_caps(monkeypatch):
    # one companion per running agent, trailing as a chain, capped at MAX.
    p = P.Pet(session_id="cmpchain")
    try:
        active = {"n": 2}
        monkeypatch.setattr(p.engine, "agents_active", lambda: active["n"])
        p._sync_companion()
        assert len(p._companions) == 2
        active["n"] = 7                        # more agents than the cap
        p._sync_companion()
        assert len(p._companions) == P.COMPANION_MAX
        active["n"] = 1                        # agents finished -> chain shrinks
        p._sync_companion()
        assert len(p._companions) == 1
    finally:
        p._cleanup()


def test_pet_quit_command_triggers_shutdown():
    # claudlet-uninstall broadcasts {"cmd":"quit"} to tear pets down. The pet
    # must treat it as a shutdown request (clean _quit), NOT feed it to the
    # state engine like a Claude event.
    p = P.Pet(session_id="quitcmd")
    called = []
    p._quit = lambda: called.append(True)
    p._handle_event({"cmd": "quit"})
    assert called == [True]
    p._cleanup()


def test_pid_alive_posix_and_windows(monkeypatch):
    if os.name != "nt":
        assert P._pid_alive(os.getpid()) is True     # this test process is alive
    # Windows branch: liveness comes from a process snapshot, never os.kill
    # (which on Windows would Ctrl+C the target instead of probing it).
    monkeypatch.setattr(P.os, "name", "nt")
    import claudlet.platform.geom as geom_pkg
    fake = types.ModuleType("win32")
    fake.proc_table = lambda: {4321: ("claude.exe", 1)}
    monkeypatch.setattr(geom_pkg, "win32", fake, raising=False)
    assert P._pid_alive(4321) is True
    assert P._pid_alive(9999) is False               # absent from snapshot -> dead
    fake.proc_table = lambda: {}                      # snapshot failed -> assume alive
    assert P._pid_alive(9999) is True


def test_activate_claude_windows_passes_win32_classes():
    # Windows click-to-focus hands find_focus_target the host's real Win32 class
    # substrings (hostinfo.win_classes), NOT the Linux/KWin-flavored
    # self.host_classes ("code" never matches a Win32 class). "unknown" (native
    # terminals: cmd.exe/PowerShell/Windows Terminal) is the host with a
    # distinctive-enough class to trust; the returned hwnd is activated.
    p = P.Pet(session_id="wf1", host="unknown")
    try:
        class _FakeGeom:
            def __init__(self):
                self.calls = []

            def find_focus_target(self, ancestor_pids, class_subs):
                self.calls.append(class_subs)
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


def test_activate_claude_windows_no_class_guess_for_ambiguous_host():
    # VS Code's Win32 class ("chrome_widgetwin_1") is shared by every other
    # Electron/Chromium app -- win_classes("vscode") is [] on purpose, so no
    # blind class guess is passed. With nothing to match, no window is activated
    # (a real pid-ancestry match is find_focus_target's own concern, covered by
    # windows.pick_focus_target tests).
    p = P.Pet(session_id="wf2", host="vscode")
    try:
        class _FakeGeom:
            def __init__(self):
                self.calls = []
                self.activated = None

            def find_focus_target(self, ancestor_pids, class_subs):
                self.calls.append(class_subs)
                return None

            def activate_hwnd(self, hwnd):
                self.activated = hwnd

        fake = _FakeGeom()
        p._win32_geom = fake
        p._activate_claude_windows()
        assert fake.calls == [[]]
        assert fake.activated is None
    finally:
        p._cleanup()


def test_pet_is_session_and_host_aware():
    p = P.Pet(session_id="sess-x", host="vscode")
    try:
        assert p.host_classes == ["code"]
        assert p.port_file.endswith("claudlet-sess-x.port")
        assert p._wtitle == "claudlet-sess-x"
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
    from claudlet.platform import geom as W
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
    from claudlet.platform import geom as W
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
    from claudlet.platform import geom as W
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
    from claudlet.platform import geom as W
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
    from claudlet.platform import geom as W
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
    from claudlet.platform import geom as W
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


def test_follow_falls_when_support_drops():
    # grounded follow perches on a window's top edge like _roam does; if that
    # window vanishes it must fall (mode "thrown"), not snap straight to
    # whatever floor is now underneath (the pre-fix teleport bug).
    from claudlet.platform import geom as W
    p = P.Pet(session_id="ff1")
    try:
        p._follow = True
        p.mode = "roam"
        win = W.Win("w1", 0, 300, 800, 400, "code", 1)   # window top at y=300
        p._wins = [win]
        p.x, p.y = 340.0, 100.0            # above the window, within its column
        _l, _r, _t, floor = p._bounds()    # floor = the window's top edge
        p.y = floor                        # already resting there (settled)
        p._on_cursor("400,320")            # cursor over the window
        p._tick()
        assert p.mode == "roam" and p.y == floor   # sanity: stays perched
        p._wins = []                       # window closed
        p._tick()
        assert p.mode == "thrown", "support dropped -> should fall, not snap"
    finally:
        p._cleanup()


def test_follow_walks_on_flat_floor_without_hopping():
    # regression: on the bare screen floor (no windows) there is NO ledge, so
    # grounded follow must WALK toward the cursor, never launch the ledge-leap.
    # The bug: comparing the probe surface to an approximate feet line
    # (self.y + FOOT_Y) instead of surface-to-surface false-positived every
    # tick on flat ground (floor there is surface - self.h, ~16px off FOOT_Y),
    # so the pet hopped (mode "thrown") forever instead of walking.
    p = P.Pet(session_id="ff2")
    try:
        p._follow = True
        p.mode = "roam"
        p._wins = []                       # bare desktop: only the screen floor
        _l, _r, _t, floor = p._bounds()
        p.x = float(p.screen_rect.left())  # far left; cursor is off to the right
        p.y = floor
        p._on_cursor(f"{p.screen_rect.right()},{int(p.y)}")
        for _ in range(5):
            p._tick()
            assert p.mode != "thrown", "flat floor has no ledge -> must walk, not hop"
        assert p.x > float(p.screen_rect.left())   # actually made progress walking
    finally:
        p._cleanup()


def test_follow_strain_hops_when_cursor_unreachably_above():
    # cursor is aligned and far above the pet, but there's nothing to land on
    # (no windows) -> an in-place strain-hop (squint-eyed jump rig), never a
    # doomed ballistic arc toward empty air.
    p = P.Pet(session_id="st1")
    try:
        p._follow = True
        p.mode = "roam"
        p._wins = []                                    # nothing to land on above
        p.x, p.y = 400.0, p.floor_y                      # on the screen floor
        petcx = p.x + p.w / 2.0
        p._on_cursor(f"{int(petcx)},{int(p.y) - 400}")   # aligned, far above -> unreachable
        p._tick()
        assert p._render_state == "strain"
        assert p.mode != "thrown", "unreachable above must not launch a doomed arc"
    finally:
        p._cleanup()


def test_follow_strains_when_cursor_above_but_beyond_jump_reach():
    # a platform ~48px above the current surface -- inside the OLD JUMP_REACH=70
    # (would have launched a doomed arc -> hop loop) but beyond the achievable
    # apex. ③ must STRAIN in place, never launch.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="st2")
    try:
        p._follow = True
        p.mode = "roam"
        p.x, p.y = 400.0, float(p.floor_y)               # on the screen floor
        petcx = p.x + p.w / 2.0
        sb = p._screen_bottom_at(petcx)
        # FIXED 48px above the current surface: inside the old JUMP_REACH=70
        # (would have wrongly launched) but well beyond the ~28px apex. Fixed,
        # NOT derived from JUMP_REACH, so it stays RED if JUMP_REACH regresses.
        wy = sb - 48
        win = W.Win("w1", 0, int(wy), 800, 400, "code", 1)
        p._wins = [win]
        p._on_cursor(f"{int(petcx)},{int(p.y) - 60}")     # aligned, above margin
        p._tick()
        assert p._render_state == "strain"
        assert p.mode != "thrown", "beyond reach must strain, not launch a doomed arc"
    finally:
        p._cleanup()


def test_follow_climbs_down_when_cursor_below_on_window():
    # perched on a window; cursor sits aligned and well below the window's
    # surface -> climb down in place on the first tick (the fall guard takes
    # over on a later tick once the surface drops out of reach).
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cd1")
    try:
        p._follow = True
        p.mode = "roam"
        win = W.Win("w1", 0, 300, 800, 400, "code", 1)    # window top at y=300
        p._wins = [win]
        p.x, p.y = 340.0, 100.0              # above the window, within its column
        _l, _r, _t, floor = p._bounds()      # floor = perched on the window's top
        p.y = floor                          # settle onto the perch
        petcx = p.x + p.w / 2.0
        p._on_cursor(f"{int(petcx)},{int(p.y) + P.FOOT_Y + 100}")   # aligned, well below
        p._tick()
        assert p._render_state == "climbdown"
        assert p.mode != "thrown", "first tick should descend in place, not free-fall"
    finally:
        p._cleanup()


def test_small_window_centres_pet_instead_of_jutting():
    from claudlet.platform import geom as W
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
    from claudlet.platform import geom as W
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
    from claudlet.platform import geom as W
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
    from claudlet.platform import geom as W
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


def test_companion_survives_backgrounded_subagent_lifecycle():
    # issue #2 end-to-end through the real pet: a subagent that yields while its
    # background work runs must keep its companion (shown idle), and only depart
    # -- with the goodbye wave -- once the work truly finishes.
    p = P.Pet(session_id="bg")
    try:
        p._handle_event({"event": "PreToolUse", "session": "bg", "tool_name": "Agent"})
        p._tick()
        assert len(p._companions) == 1                       # dispatched -> appears

        # yielded, but background_tasks still shows work running
        p._handle_event({"event": "SubagentStop", "session": "bg",
                         "bg_agents": 0, "bg_tasks": 1})
        p._tick()
        assert len(p._companions) == 1                       # stays (was the bug)
        assert p._departing == []
        assert p.engine.agent_state() == "idle"              # waits idle

        # work truly finished -> empty snapshot. NOT gone yet: it lingers for
        # the depart grace so it trails Claude Code's UI instead of leading it.
        p._handle_event({"event": "SubagentStop", "session": "bg",
                         "bg_agents": 0, "bg_tasks": 0})
        p._tick()
        assert len(p._companions) == 1                       # grace: still around
        assert p._departing == []

        # ...then, once the grace has passed (backdate the timer rather than
        # sleep), it departs with the goodbye wave.
        from claudlet.core import state_engine as SE
        p.engine.sessions["bg"].agent_gone_since = (
            time.monotonic() - SE.COMPANION_DEPART_GRACE - 1.0)
        p._tick()
        assert p._companions == []
        assert len(p._departing) == 1                        # waving goodbye, not vanished
    finally:
        p._cleanup()


def test_companion_spawns_without_overlapping_pet():
    # a freshly spawned companion used to pop in exactly on top of the pet
    # (same x). It must spawn clear of the pet's body, then ease into the chain.
    p = P.Pet(session_id="spawn")
    try:
        p._handle_event({"event": "PreToolUse", "session": "spawn", "tool_name": "Agent"})
        p._tick()
        c = p._companions[0]
        overlap = not (c.x + c.w <= p.x or c.x >= p.x + p.w)
        assert not overlap, "companion spawned overlapping the pet body"
    finally:
        p._cleanup()


def test_companion_window_flags_match_pet_zorder_off_x11():
    # Windows/macOS: BypassWindowManagerHint is an X11 concept and gives no
    # always-on-top behaviour, so the companion sank behind windows while the
    # pet (WindowStaysOnTopHint) stayed in front. Off X11 it must use
    # StaysOnTop too, matching the pet's z-order.
    from PyQt6.QtCore import Qt
    for plat in ("win32", "darwin"):
        f = P._companion_flags(plat)
        assert f & Qt.WindowType.WindowStaysOnTopHint, plat
        assert not (f & Qt.WindowType.BypassWindowManagerHint), plat


def test_companion_window_flags_keep_bypass_on_x11():
    # Linux/X11 keeps override-redirect: a second managed on-top window fights
    # the pet's interactive drag (jitter). Must NOT regress to StaysOnTop.
    from PyQt6.QtCore import Qt
    f = P._companion_flags("linux")
    assert f & Qt.WindowType.BypassWindowManagerHint
    assert not (f & Qt.WindowType.WindowStaysOnTopHint)
