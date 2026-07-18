import sys, os, time, socket, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint
from claudlet import pet as P
from claudlet import roambounds
from claudlet.core import hostinfo
from claudlet.core import idle_engine

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


def test_companion_fly_dead_lands_on_floor():
    # a follow-arc lands DEAD (no restitution bounce -- the companion is never
    # user-flung), settling on the floor and reverting to ground-following.
    c = P.Companion()
    try:
        c.x, c.y = 100.0, 100.0
        c.vx, c.vy = 6.0, -8.0
        c._air = True
        floor = 400.0
        settled = False
        for _ in range(2000):
            if c.fly(0.0, 2000.0, 0.0, floor):
                settled = True
                break
        assert settled and not c._air            # settled back to ground mode
        assert abs(c.y - floor) < 2.0
    finally:
        c.close()


def test_companion_stands_on_pets_feet_line(monkeypatch):
    # no windows: through the shared physics the companion settles onto the bare
    # screen floor -- the SAME feet line the pet stands on (shared ground).
    p = P.Pet(session_id="cmpwin")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        p._wins = []
        p.mode = "roam"
        p.x, p.y = 400.0, p.floor_y               # pet resting on the real floor
        p._sync_companion()
        c = p._companion
        c.x = 430.0                               # right beside the pet
        for _ in range(60):
            p._sync_companion()                   # let it settle under gravity
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


def test_companion_teleports_only_after_effort(monkeypatch):
    # the pet lives in a window too high to jump to, with no stepping stones:
    # the companion strains for it and only AFTER COMPANION_REUNITE_TICKS of
    # failing does it blink beside the pet (adopting its window). Give-up is a
    # last resort, not an instant snap.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cmpreunite")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        win = W.Win("w1", 300, 40, 400, 180, "code", 1)   # high, unreachable window
        p._wins = [win]
        p._contain = win
        p.x, p.y = 450.0, 70.0                            # pet up inside it
        p._sync_companion(); c = p._companions[0]
        c._contain = None
        c.x, c.y = 450.0, float(p.floor_y)                # far below on the floor
        landed = None
        for i in range(P.COMPANION_REUNITE_TICKS + 30):
            p._sync_companion()
            if c._contain is not None:
                landed = i
                break
        assert landed is not None and c._contain.wid == "w1"    # blinked in
        assert landed >= P.COMPANION_REUNITE_TICKS - 1          # only after effort
    finally:
        p._cleanup()


def test_companion_perches_beside_pet_on_a_window(monkeypatch):
    # the pet rests ON a window; the companion follows up onto it and settles
    # feet-FLUSH on the same top edge -- sharing the pet's perch feet line
    # (emergent from the shared physics, not a column snap).
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cmpperch")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        win = W.Win("w1", 100, 300, 500, 400, "code", 1)   # wide window, top y=300
        p._wins = [win]
        p.x, p.y = 300.0, 100.0             # above the window, within its column
        _l, _r, _t, floor = p._bounds()     # perched on the window top
        p.y = floor                         # settle there (feet flush at y=300)
        p._sync_companion()
        c = p._companion
        c.x = 340.0                         # beside the pet, same window column
        for _ in range(120):
            p._sync_companion()
        ratio = P.COMPANION_U / float(P.U)
        expected = p.y + P.FOOT_Y * (1.0 - ratio)     # the pet's shared feet line
        assert abs(c.y - expected) < 3.0              # settled on the perch line
        assert abs((c.y + P.FOOT_Y * ratio) - win.y) < 3.0  # feet flush on the top
    finally:
        p._cleanup()


def test_companion_enters_the_pets_window(monkeypatch):
    # the pet lives INSIDE a reachable window; the companion follows it in and
    # becomes contained too -- sitting WITH the pet, not just on window tops
    # (the missing window-entry symptom, fixed).
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cmpenter")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        fy = p.floor_y
        win = W.Win("w1", 300, fy - 160, 400, 300, "code", 1)   # reachable window
        p._wins = [win]
        p._contain = win
        p.x, p.y = 450.0, float(win.y + 30)
        p._sync_companion()
        c = p._companion
        c._contain = None
        c.x, c.y = 450.0, float(p.floor_y)          # on the floor below the window
        got = False
        for _ in range(300):
            p._sync_companion()
            if c._contain is not None:
                got = True
                break
        assert got and c._contain.wid == "w1"
    finally:
        p._cleanup()


def test_companion_falls_onto_a_window_below(monkeypatch):
    # dropped above a window (with the pet on it), the companion falls under
    # gravity and lands feet-FLUSH on its top -- never passing through, never
    # floating.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cmpfall")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        fy = p.floor_y
        win = W.Win("w1", 300, fy - 260, 400, 200, "code", 1)   # window mid-air
        p._wins = [win]
        p.x = 460.0
        p.y = 100.0
        _l, _r, _t, floor = p._bounds()             # pet perched on the window top
        p.y = floor
        p._sync_companion()
        c = p._companion
        c.x, c.y = 460.0, float(win.y - 300)        # start ABOVE the window
        ratio = P.COMPANION_U / float(P.U)
        for _ in range(200):
            p._sync_companion()
        assert abs((c.y + P.FOOT_Y * ratio) - win.y) < 3.0   # landed on the top
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


def test_companion_follows_thrown_pet(monkeypatch):
    # a thrown pet is no longer a special fling for the companion: it is NOT
    # independently launched with the pet's velocity -- it just keeps chasing
    # the pet's (now moving) position through the normal pipeline and closes in
    # once the pet settles.
    p = P.Pet(session_id="cmpfling")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        p._wins = []
        p.x = float(p.screen_rect.left() + 400)
        p.y = float(p.floor_y)
        p._sync_companion()
        c = p._companion
        c.x, c.y = p.x - 300.0, float(p.floor_y)
        p.mode = "thrown"
        p.vx, p.vy = 12.0, -10.0
        p._sync_companion()
        assert not (c.vx == 12.0 and c.vy == -10.0)   # NOT a fling copy of the pet
        for _ in range(400):
            p._tick()                                 # pet physics + companion follow
        d = abs((c.x + c.w / 2) - (p.x + p.w / 2))
        assert d < 150                                # tracked the pet to where it landed
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


def test_spawn_test_companion_override(monkeypatch):
    # the right-click test helper forces companions to appear WITHOUT a real
    # agent, clamps to [0, MAX], and real agents still stack on top.
    p = P.Pet(session_id="dbgcomp")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 0)
        assert p._companions == []
        p._spawn_test_companion(+1)
        assert len(p._companions) == 1 and p._companion.isVisible()
        for _ in range(P.COMPANION_MAX + 3):
            p._spawn_test_companion(+1)
        assert len(p._companions) == P.COMPANION_MAX      # clamped
        p._spawn_test_companion(-1)                       # removed one -> waves bye
        assert len(p._companions) == P.COMPANION_MAX - 1
        # a real agent adds on top of the override count
        monkeypatch.setattr(p.engine, "agents_active",
                            lambda: P.COMPANION_MAX)
        p._sync_companion()
        assert len(p._companions) == P.COMPANION_MAX
    finally:
        p._cleanup()


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


def test_companion_contained_stays_within_window(monkeypatch):
    # a companion sharing the pet's window stays WITHIN that window's interior
    # while following it around inside -- it never walks/falls out the walls.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cmpbounce")
    try:
        monkeypatch.setattr(p.engine, "agents_active", lambda: 1)
        monkeypatch.setattr(p.engine, "agent_state", lambda: "idle")
        win = W.Win("w1", 400, 300, 500, 400, "konsole", 1)
        p._contain = win
        p.x, p.y = 500.0, 400.0
        p._sync_companion()                     # create companion near the pet
        c = p._companion
        c._contain = win
        c.x, c.y = 520.0, 420.0
        for _ in range(200):
            p._sync_companion()
            assert win.x - 2 <= c.x <= win.x + win.w - c.w + 2   # never leaves
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
    # a platform far above the current surface -- beyond the jump apex
    # (~206px with VY_JUMP=24) and with no stepping stone -> STRAIN in
    # place, never a doomed arc. (The old 48px version of this test guarded
    # the previous branch's ~28px apex; 48px is now correctly jumpable.)
    from claudlet.platform import geom as W
    p = P.Pet(session_id="st2")
    try:
        p._follow = True
        p.mode = "roam"
        p.x, p.y = 400.0, float(p.floor_y)               # on the screen floor
        petcx = p.x + p.w / 2.0
        sb = p._screen_bottom_at(petcx)
        wy = sb - 500                                    # way beyond the apex
        win = W.Win("w1", 0, int(wy), 800, 400, "code", 1)
        p._wins = [win]
        p._on_cursor(f"{int(petcx)},{int(wy) - 30}")     # aligned, above it
        p._tick()
        assert p._render_state == "strain"
        assert p.mode != "thrown", "beyond reach must strain, not launch a doomed arc"
    finally:
        p._cleanup()


def test_follow_jumps_onto_small_step_above():
    # a window top a few dozen px above the feet is a real platformer step:
    # follow must LAUNCH (mode thrown) and land feet-flush on the top edge.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="js1")
    try:
        p._follow = True
        p.mode = "roam"
        p.x, p.y = 200.0, float(p.floor_y)
        petcx = p.x + p.w / 2.0
        sb = p._screen_bottom_at(petcx)
        wy = sb - 48                                     # 32px above the feet
        win = W.Win("w1", 0, int(wy), 800, 600, "code", 1)
        p._wins = [win]
        p._on_cursor(f"{int(petcx)},{int(wy) - 30}")     # in the air above it
        p._tick()
        assert p.mode == "thrown" and p.vy < 0, "step in reach -> aimed jump"
        p._tick()
        # in flight the pose must be the STEADY leap -- the in-place "jump"
        # motion bobs ~27px on its own, which fights the ballistic movement
        # and reads as stutter.
        assert p._render_state == "leap"
        for _ in range(300):
            p._tick()
            if p.mode != "thrown":
                break
        assert p.mode == "roam"
        assert abs(p.y - (wy - P.FOOT_Y)) <= 2, "feet should rest on the step"
    finally:
        p._cleanup()


def test_follow_enters_floor_level_window_under_cursor():
    # cursor inside a window whose body reaches the screen floor: the pet
    # standing in front of it steps straight in (contained), no jump needed.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="en1")
    try:
        p._follow = True
        p.mode = "roam"
        p.x, p.y = 340.0, float(p.floor_y)
        petcx = p.x + p.w / 2.0                          # 400
        sb = p._screen_bottom_at(petcx)
        win = W.Win("w1", 300, int(sb - 400), 400, 400, "code", 1)
        p._wins = [win]
        p._on_cursor(f"450,{int(sb - 200)}")             # inside the window
        p._tick()
        assert p._contain is not None and p._contain.wid == "w1"
    finally:
        p._cleanup()


def test_follow_jumps_into_panel_gap_window_and_gets_contained():
    # windows on KDE float above the panel: bottom ~40px over the screen
    # bottom. Too high for the walk-in tolerance, top beyond the apex ->
    # the pet must jump INTO the body and get contained mid-flight.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="pg1")
    try:
        p._follow = True
        p.mode = "roam"
        p.x, p.y = 340.0, float(p.floor_y)
        petcx = p.x + p.w / 2.0                          # 400
        sb = p._screen_bottom_at(petcx)
        win = W.Win("w1", 300, int(sb - 400), 400, 360, "code", 1)  # bottom sb-40
        p._wins = [win]
        p._on_cursor(f"450,{int(sb - 200)}")             # inside the window
        p._tick()
        assert p.mode == "thrown" and p.vy < 0, "must LEAP into the body"
        for _ in range(300):
            p._tick()
            if p.mode != "thrown":
                break
        assert p.mode == "roam"
        assert p._contain is not None and p._contain.wid == "w1"
    finally:
        p._cleanup()


def test_follow_descent_lands_clean_without_bouncing():
    # deliberate follow descents (climb-down off a perch, dropping out of a
    # window) must land DEAD: no restitution flapping, and the airborne pose
    # is the aimed "jump", not the tumbling "falling".
    from claudlet.platform import geom as W
    p = P.Pet(session_id="nb1")
    try:
        p._follow = True
        p.mode = "roam"
        sb = p._screen_bottom_at(400.0)
        top = int(sb - 300)
        win = W.Win("w1", 100, top, 600, 200, "code", 1)   # bottom sb-100
        p._wins = [win]
        p.x, p.y = 340.0, float(top - P.FOOT_Y)            # perched on w1
        petcx = p.x + p.w / 2.0
        p._on_cursor(f"{int(petcx)},{sb - 10}")            # floor below, aligned
        floor_y = float(p.floor_y)
        touched = False
        for _ in range(300):
            p._tick()
            if p.mode == "thrown":
                # "climbdown" lingers on the guard-fire transition tick
                assert p._render_state in ("jump", "climbdown"), \
                    "descent must not tumble"
            if p.y >= floor_y - 1:
                touched = True
            if touched:
                assert p.y >= floor_y - 3, "bounced back up after touching down"
            if touched and p.mode != "thrown":
                break
        assert touched and p.mode == "roam"
    finally:
        p._cleanup()


def test_follow_exit_below_contained_window_climbs_down_not_jumps():
    # contained in a window, cursor on the floor below it: the pet must show
    # a DESCENT (climbdown pose all the way), never the jump pose.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="cx1")
    try:
        p._follow = True
        p.mode = "roam"
        sb = p._screen_bottom_at(400.0)
        win = W.Win("w1", 100, int(sb - 500), 600, 300, "code", 1)  # bottom sb-200
        p._wins = [win]
        p._contain = win
        _l, _r, _t, floor = p._bounds()
        p.x, p.y = 340.0, float(floor)                   # standing inside
        p._on_cursor(f"400,{sb - 10}")                   # floor below, outside
        p._tick()
        assert p._render_state == "climbdown"
        assert p._contain is None, "climbing out must release containment"
        for _ in range(300):
            p._tick()
            if p.mode == "thrown":
                assert p._render_state == "climbdown", \
                    "a straight-down exit must not use the jump pose"
            elif p.y >= float(p.floor_y) - 1:
                break
        assert p.mode == "roam" and abs(p.y - p.floor_y) <= 1
    finally:
        p._cleanup()


def test_follow_jump_lands_without_post_shuffle():
    # discrete flight steps land up to ~2 ticks (~28px) past the aim; the
    # pet then walked BACK, flickering land->walk->stand after every hop.
    # Settling must snap onto the cursor column when it lands nearby.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="sh1")
    try:
        p._follow = True
        p.mode = "roam"
        sb = p._screen_bottom_at(400.0)
        top = int(sb - 166)
        win = W.Win("w1", 300, top, 450, 600, "code", 1)
        p._wins = [win]
        p.x, p.y = 80.0, float(p.floor_y)
        p._on_cursor(f"600,{top - 30}")                  # above the window top
        for _ in range(300):
            p._tick()
            if p._follow_jump:
                break
        assert p._follow_jump, "never launched"
        for _ in range(300):
            p._tick()
            if p.mode != "thrown":
                break
        assert p.mode == "roam"
        landed_x = p.x
        p._tick()
        assert p._render_state != "walk", "post-landing correction shuffle"
        assert p.x == landed_x
    finally:
        p._cleanup()


def test_follow_gap_jump_lands_and_enters_target_window():
    # perched on one window, cursor inside another across a gap: one aimed
    # ballistic hop, landing on the target's top edge, which (because the
    # cursor is inside it) resolves to ENTER -> contained in w2.
    from claudlet.platform import geom as W
    p = P.Pet(session_id="gj1")
    try:
        p._follow = True
        p.mode = "roam"
        sb = p._screen_bottom_at(400.0)
        top = int(sb - 300)
        w1 = W.Win("w1", 50, top, 300, 300, "code", 1)
        w2 = W.Win("w2", 420, top, 300, 300, "code", 2)
        p._wins = [w1, w2]
        p.x, p.y = 150.0, float(top - P.FOOT_Y)          # perched on w1
        p._on_cursor(f"500,{top + 150}")                 # inside w2
        p._tick()
        assert p.mode == "thrown" and p.vx > 0, "gap -> aimed jump toward w2"
        for _ in range(300):
            p._tick()
            if p.mode != "thrown":
                break
        assert p.mode == "roam"
        assert p._contain is not None and p._contain.wid == "w2"
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
        # anchor away from screen edges -- Pet() spawns at a random x, and near
        # an edge the companion's on-screen clamp (pet.py's _sync_companion)
        # can legitimately land it back on top of the pet. That's a separate,
        # pre-existing edge case; this test is about the normal spawn-offset
        # logic, so give it room on both sides.
        left, right, _t, _f = p._bounds()
        p.x = (left + right) / 2.0
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


def test_energy_drains_and_reaches_doze():
    p = P.Pet(session_id="nrg1")
    try:
        p.idle_energy.value = 0.05             # force exhausted
        p.claude_state = "idle"
        p.mode = "roam"
        seen = set()
        for _ in range(400):
            p._tick()
            seen.add(p._idle_behavior)
        assert idle_engine.DOZE in seen or idle_engine.SETTLE in seen
    finally:
        p._cleanup()


def test_energy_does_not_drain_below_zero():
    p = P.Pet(session_id="nrg2")
    try:
        p.claude_state = "idle"
        p.mode = "roam"
        for i in range(3000):
            p.idle_energy.note_event(now=float(i))   # heavy activity drain
            p._tick()
        # _tick's resting-recovery runs last each loop and can nudge the value a
        # floating-point sliver above 0; one final drain lands it back on the floor.
        p.idle_energy.note_event(now=3000.0)
        assert p.idle_energy.value == 0.0            # bottomed out, clamped
        assert p.idle_energy.value >= 0.0            # never negative
    finally:
        p._cleanup()


def test_no_rest_poses_during_autopilot():
    # During auto_web/auto_search (AUTO_ROAM), the pet's visor is on and it is
    # actively "working" -- it must never settle/doze/observe/tic even at rock
    # -bottom energy; it should keep wandering (walk/explore/hop) instead.
    p = P.Pet(session_id="nrg3")
    try:
        p.idle_energy.value = 0.05             # force LOW
        # WebFetch under an autonomous permission mode -> engine reports auto_web
        # (AUTO_VARIANT["work_web"]), which is in AUTO_ROAM -> _roam runs for it.
        p._handle_event({"event": "PreToolUse", "session": "nrg3",
                          "tool_name": "WebFetch", "permission_mode": "auto"})
        p.mode = "roam"
        seen = set()
        for _ in range(400):
            p._tick()
            seen.add(p._idle_behavior)
        assert p.claude_state == "auto_web"
        assert not (seen & idle_engine.RESTING)
    finally:
        p._cleanup()


def test_explore_falls_back_to_walk_without_window_feed():
    # HIGH energy can pick explore/hop, but with no window feed at all there is
    # nothing to travel to -- must degrade to a plain walk leg, never freeze.
    p = P.Pet(session_id="ex1")
    try:
        p.idle_energy.value = 0.9              # HIGH -> may pick explore/hop
        p.claude_state = "idle"
        p.mode = "roam"
        p._wins = []
        x0 = p.x
        moved = False
        for _ in range(300):
            p._tick()
            if p.x != x0:
                moved = True
        assert moved                            # still roams (walks) with no windows
    finally:
        p._cleanup()


def test_explore_sets_target_toward_a_window():
    # force the EXPLORE behavior and a fake window point far to the right;
    # _roam must store it and route toward it via the follow_nav planner
    # (progress in x, or an immediate arrival/consume of the target).
    p = P.Pet(session_id="ex2")
    try:
        p.idle_energy.value = 0.9
        p.claude_state = "idle"
        p.mode = "roam"
        p._explore_point = lambda: (p.x + 500, p.y)
        p._idle_behavior = idle_engine.EXPLORE
        p._behavior_timer = 50
        x0 = p.x
        p._roam()
        assert p._explore_target == (x0 + 500, p.y) or p.x != x0
    finally:
        p._cleanup()


def test_companion_window_flags_keep_bypass_on_x11():
    # Linux/X11 keeps override-redirect: a second managed on-top window fights
    # the pet's interactive drag (jitter). Must NOT regress to StaysOnTop.
    from PyQt6.QtCore import Qt
    f = P._companion_flags("linux")
    assert f & Qt.WindowType.BypassWindowManagerHint
    assert not (f & Qt.WindowType.WindowStaysOnTopHint)


def test_aim_point_uses_explore_target_when_exploring_else_cursor():
    # The airborne-jump aim point routes correctly: follow tracks the live
    # cursor, idle exploration aims at its chosen window point.
    p = P.Pet(session_id="aim1")
    try:
        p._follow = False
        p._explore_target = (1234.0, 56.0)
        assert p._aim_point() == (1234.0, 56.0)     # exploring -> explore target
        p._follow = True
        p._cursor = (10, 20)
        assert p._aim_point() == (10, 20)           # following overrides -> cursor
        p._follow = False
        p._explore_target = None
        p._cursor = (7, 8)
        assert p._aim_point() == (7, 8)             # neither -> cursor
    finally:
        p._cleanup()


def test_explore_jump_enters_targeted_window_midflight():
    # Regression guard: an idle EXPLORE/HOP jump aimed INTO a window (top out of
    # reach -> arc pierces the body) must become CONTAINED, not sail through and
    # fall back out. Before the fix, _physics gated entry on self._follow (which
    # exploration never sets) and used the cursor, not the explore target, so the
    # pet popped in and out. Now entry is gated on _follow_jump and aims via
    # _aim_point().
    p = P.Pet(session_id="enter1")
    try:
        scr = p.screen_rect
        wx, wy = float(scr.left() + 200), float(scr.top() + 150)
        win = P.geom.Win("W1", wx, wy, 300.0, 200.0, "t")
        p._wins = [win]
        p._contain = None
        p._follow = False                            # idle exploration, NOT follow
        aim = (wx + 150.0, wy + 100.0)               # a point inside the window body
        p._explore_target = aim
        p.x = wx + 150.0 - p.w / 2.0                 # center-x over the window
        p.y = wy                                     # feet (y + FOOT_Y) inside the body
        p.mode = "thrown"
        p._follow_jump = True
        p.vx, p.vy = 0.0, 1.0
        p._physics()
        assert p._contain is not None and p._contain.wid == "W1"
    finally:
        p._cleanup()


def test_roam_stays_out_of_no_go():
    p = P.Pet(session_id="nogo")
    try:
        p._roam_area = None
        # Anchor off screen-centre (not Pet()'s random spawn x) so the no-go
        # zone built around it has room to escape on BOTH sides -- a zone
        # abutting a screen edge would leave push_out_x's chosen edge
        # unreachable after clamping back to bounds, which isn't what this
        # test means to exercise.
        left, right, _t, _f = p._bounds()
        p.x = (left + right) / 2.0
        p._no_go = [{"x": p.x - 5.0, "y": float(p.y), "w": p.w + 10.0, "h": 400.0}]
        p.x = float(p._no_go[0]["x"] + 2)     # start inside the zone
        p.claude_state = "idle"               # roaming state -> _roam runs each tick
        for _ in range(30):
            p._tick()
        assert not roambounds.blocks_target(p.x, p.w, p.y + P.FOOT_Y, p._no_go)
    finally:
        p._cleanup()


def test_env_forces_palette(monkeypatch):
    monkeypatch.setenv("CLAUDLET_PALETTE", "shiny_violet")
    p = P.Pet(session_id="pal")
    try:
        assert p._palette == "shiny_violet"
    finally:
        p._cleanup()
