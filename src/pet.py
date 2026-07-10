#!/usr/bin/env python3
"""claude-pet — a roaming desktop buddy that reacts to Claude Code.

A frameless, translucent, always-on-top creature that wanders the desktop,
can be dragged & thrown, and switches expression based on Claude Code hook
events delivered over a unix socket by `claude-pet-hook`.

Runs on KDE Wayland via XWayland (forced xcb platform) so the window can
position itself freely across the screen.
"""
import os
# Force XWayland: native Wayland forbids clients positioning their own windows,
# which a roaming pet needs. xcb (XWayland) allows self-positioning.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import sys
import json
import math
import random
import re
import shutil
import socket
import subprocess
import tempfile
import time

from PyQt6.QtWidgets import QApplication, QWidget, QMenu, QSystemTrayIcon
from PyQt6.QtGui import QPainter, QAction, QCursor, QIcon, QPixmap, QColor
from PyQt6.QtCore import Qt, QTimer, QSocketNotifier, QPoint, QObject, pyqtSlot
from PyQt6.QtDBus import QDBusConnection

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import creature as C
from state_engine import StateEngine, AUTO_STATES
import focus
import hostinfo
import petconfig
import sprites
import physics
import windows

# ---- config ----
U = 5                                   # art-pixel size in device px
PAD_X, PAD_Y = 1, 2                     # padding (art px) around creature for props
FPS = 20
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

# short label per state, shown as the tray tooltip
STATE_LABELS = {
    "idle": "대기", "sleeping": "자는 중", "walk": "산책",
    "thinking": "고민 중", "work_computer": "작업 중", "work_search": "탐색 중",
    "work_web": "연락 중", "work_agent": "서브에이전트", "work_skill": "스킬 사용",
    "autopilot": "자동 진행", "auto_computer": "자동·코딩",
    "auto_search": "자동·탐색", "auto_web": "자동·웹", "auto_agent": "자동·에이전트",
    "auto_skill": "자동·스킬", "attention": "입력 대기!", "celebrate": "완료!",
    "error": "에러",
}
# representative animation frame to freeze for each state's tray icon
_ICON_FRAME = {"work_computer": 100, "walk": 6, "work_search": 4}

# transient motions offered in the right-click / tray menus: (label, name, seconds)
MOTION_MENU = [
    ("점프", "jump", 2.5),
    ("손 흔들기", "wave", 2.5),
    ("노래", "sing", 3.0),
    ("저글링", "juggle", 3.0),
    ("축하", "celebrate", 2.5),
]

# device-px from the pet window's top down to the creature's feet (legs bottom).
# creature legs bottom ~15.8 art rows; with PAD_Y=2 and U=5: (2 + 15.8) * 5 ≈ 89.
# used to land the FEET on a window's top edge when perching (not the window box).
FOOT_Y = 89


class _GeomReceiver(QObject):
    """D-Bus object the KWin geometry script pushes window dumps to."""
    def __init__(self, pet):
        super().__init__()
        self._pet = pet

    @pyqtSlot(str)
    def push(self, dump):
        self._pet._on_geom(dump)

    @pyqtSlot(str)
    def cursor(self, xy):
        self._pet._on_cursor(xy)


class Pet(QWidget):
    def __init__(self, session_id="default", host="unknown"):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # per-session identity: unique caption lets the skip-taskbar match hit
        # only THIS pet, and the per-session socket isolates its event stream.
        self.session_id = session_id
        self.host = host
        self.host_classes = hostinfo.host_classes(host)
        self._wtitle = "claude-pet-" + str(session_id)
        self.setWindowTitle(self._wtitle)
        self.sock_path = hostinfo.session_sock(session_id)

        self.w = (C.GRID_W + 2 * PAD_X) * U
        self.h = (C.GRID_H + 2 * PAD_Y) * U
        self.setFixedSize(self.w, self.h)

        primary = QApplication.primaryScreen().availableGeometry()
        # Roam across ALL monitors: screen_rect is the union of every screen's
        # available area (drives horizontal roam/physics bounds); per-monitor
        # floors are resolved per-x in _screen_bottom_at so the pet doesn't
        # bounce at the primary monitor's edge.
        self._screens = [s.availableGeometry() for s in QApplication.screens()]
        union = self._screens[0]
        for g in self._screens[1:]:
            union = union.united(g)
        self.screen_rect = union
        self.floor_y = primary.bottom() - self.h
        self.x = float(random.uniform(primary.left(), max(primary.left(), primary.right() - self.w)))
        self.y = float(self.floor_y)
        self.move(int(self.x), int(self.y))

        self.frame = 0
        self.facing = 1
        cfg = petconfig.load_config()
        self.engine = StateEngine(is_focused=self._is_focused,
                                  tool_states=cfg["tool_states"],
                                  event_states=cfg["event_states"],
                                  raw_events=cfg["raw_events"])
        # optional user art: assets/<state>.gif|png overrides the code drawing
        self._sprites = sprites.load_overrides(ASSETS, C.STATES)
        self.claude_state = "sleeping"       # last state the engine reported
        self.dnd = False                     # do-not-disturb
        self._quit_timer = None              # pending SessionEnd -> quit timer
        self._wins = []                      # last window-geometry poll
        self._contain = None                 # Win we're living inside, or None

        # movement
        self.mode = "roam"                   # roam | held | thrown
        self.target_x = None
        self.walk_pause = 0.0
        self.vx = self.vy = 0.0
        self._walk_speed = 2.2               # per-trip roam speed (varied a little)
        self._search_anchor = None           # x the work_search darts stay around

        # transient motion override (jump/wave/... — timed; overrides the render)
        self._motion = None
        self._motion_expiry = None       # monotonic deadline; None = hold
        # float is a MODE, not a render override: suspends gravity so the pet
        # hovers, while its normal animation keeps playing. Cleared by `stop`.
        self._floating = False
        # follow mode: walk toward the mouse cursor until toggled off
        self._follow = False
        # latest GLOBAL cursor pos pushed by the KWin script. Qt's QCursor.pos()
        # only updates while the cursor is over our own (XWayland) surface, so on
        # Wayland the compositor is the only reliable source off-surface.
        self._cursor = None
        self._cursor_plugin = None       # KWin cursor-feed script, loaded on follow
        self._activate_plugin = None     # one-shot click-to-focus KWin script

        # drag tracking
        self._press_global = None
        self._press_winpos = None
        self._moved = False
        self._vel_samples = []

        self._init_socket()
        self._init_tray()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(int(1000 / FPS))

        self._geom_script_id = None
        self._setup_geom_feed()

        # drop the taskbar/pager entry once the window is mapped (KWin script)
        QTimer.singleShot(400, self._skip_taskbar)

    # ---------- Claude Code hook socket ----------
    def _init_socket(self):
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.sock_path)
        self.srv.listen(16)
        self.srv.setblocking(False)
        self.notifier = QSocketNotifier(self.srv.fileno(), QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self._on_conn)

    def _on_conn(self):
        try:
            conn, _ = self.srv.accept()
        except (BlockingIOError, OSError):
            return
        with conn:
            conn.settimeout(0.2)
            buf = b""
            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
            except (socket.timeout, OSError):
                pass
        for line in buf.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line:
                try:
                    self._handle_event(json.loads(line))
                except json.JSONDecodeError:
                    pass

    def _handle_event(self, ev):
        # A motion command is a user override, NOT a Claude event: it must not
        # touch the engine or the SessionEnd quit timer.
        if ev.get("cmd") == "motion":
            motion = ev.get("motion")
            if not motion:
                # `stop` clears everything and restores gravity if we were floating
                was_floating = self._floating
                self._floating = False
                self._motion = None
                self._motion_expiry = None
                if was_floating and self.mode != "held":
                    self.mode = "thrown"        # gravity brings the floater home
                self._sync_float_check()
            elif motion == "float":
                # float is a MODE toggle, not a transient render override — it
                # does NOT touch self._motion, so the pet keeps its normal
                # animation while hovering. Anti-gravity: rise a little, kill
                # velocity; roam/physics are skipped while floating.
                self._floating = True
                if self.mode != "held":
                    self.vx = self.vy = 0.0
                    self.mode = "roam"
                    self.y = max(float(self.screen_rect.top()), self.y - 240.0)
                self._sync_float_check()
            else:
                dur = ev.get("dur", 0) or 0
                self._motion = motion
                self._motion_expiry = (time.monotonic() + dur) if dur > 0 else None
            return
        self.engine.handle(ev, time.monotonic())
        name = ev.get("event") or ev.get("hook_event_name") or ""
        if name == "SessionEnd":
            self._arm_quit()          # session ended -> wind down (cancellable)
        else:
            self._cancel_quit()       # any other event means the session lives on

    def _arm_quit(self):
        self._cancel_quit()
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(self._quit)
        t.start(1500)
        self._quit_timer = t

    def _cancel_quit(self):
        if self._quit_timer is not None:
            self._quit_timer.stop()
            self._quit_timer = None

    def _is_focused(self):
        return focus.terminal_focused(self.host_classes)

    # ---------- main loop ----------
    def _tick(self):
        self.frame += 1
        now = time.monotonic()
        self.claude_state = self.engine.display_state(now)
        eff = self.claude_state
        self._update_tray_icon()

        # transient motion override (jump/wave/sing/juggle + exposed states):
        # plays for its duration then reverts. Never overrides drag/throw.
        motion_active = False
        if self._motion and self.mode not in ("held", "thrown"):
            if self._motion_expiry is not None and now >= self._motion_expiry:
                self._motion = None
                self._motion_expiry = None
            else:
                self._render_state = self._motion
                motion_active = True

        # float is a MODE: it suspends gravity/roam so the pet hovers where it is
        # (and wherever you drag it), but the pet keeps its normal animation.
        floating = self._floating and self.mode not in ("held", "thrown")
        following = self._follow and self.mode not in ("held", "thrown")
        # auto/bypass work states wander too (visor on): they roam like idle does
        roaming = (eff in ("idle", "sleeping") or eff in AUTO_STATES) \
            and self.mode == "roam" and not self.dnd

        if self.mode == "held":
            self._render_state = "held"     # dangling from the cursor
        elif self.mode == "thrown":
            self._physics()
        elif motion_active:
            pass                            # transient motion already set the render
        elif following and floating:
            # floating + follow: no gravity, so glide to the cursor in x AND y.
            curx, cury = self._cursor_pos()
            tx = min(max(curx - self.w / 2.0, self.screen_rect.left()),
                     self.screen_rect.right() - self.w)
            ty = min(max(cury - self.h / 2.0, self.screen_rect.top()),
                     self.screen_rect.bottom() - self.h)
            dx, dy = tx - self.x, ty - self.y
            dist = (dx * dx + dy * dy) ** 0.5
            step = 5.0                     # constant glide (no speed-up when far)
            if abs(dx) > 1.0:
                self.facing = 1 if dx > 0 else -1
            if dist <= step:
                self.x, self.y = tx, ty
            else:
                self.x += dx / dist * step
                self.y += dy / dist * step
            self._render_state = "float"
        elif following:
            # grounded follow: walk left/right toward the cursor's column along
            # the floor. Bounds come from _bounds(), so a pet perched inside a
            # window follows WITHIN that window rather than leaving it.
            left, right, _t, floor = self._bounds()
            curx, _cury = self._cursor_pos()
            self.target_x = min(max(curx - self.w / 2.0, left), right)
            dx = self.target_x - self.x
            speed = 10.0                    # constant pace (no speed-up when far)
            if abs(dx) <= speed:
                self.x = self.target_x
                self._render_state = eff    # arrived: resume normal animation
            else:
                self.facing = 1 if dx > 0 else -1
                self.x += speed * self.facing
                self._render_state = "walk"
            self.y = floor
        elif floating:
            # hover in place (no gravity): show the floaty pose when idle,
            # otherwise keep the live Claude-activity animation.
            self._render_state = "float" if eff in ("idle", "sleeping") else eff
        elif roaming:
            self._roam()
        else:
            # stationary Claude state (working / attention / thinking / ...).
            # still gravity-bound: rest on the surface, and fall if it drops away
            # (a window closes under us, or we're mid-air) — physics isn't only
            # for idle/thrown.
            lft, rgt, _t, floor = self._bounds()
            if self.y < floor - 2:
                self.vx = 0.0
                self.vy = 0.0
                self.mode = "thrown"          # fall onto the surface, even mid-state
            else:
                if eff == "work_search":
                    # quick random horizontal darts while rummaging, kept LOCAL:
                    # pick targets around a fixed anchor (clamped to bounds) so it
                    # darts both ways in place instead of random-walking off across
                    # the screen / through window walls.
                    if self._search_anchor is None:
                        self._search_anchor = self.x
                    if self.target_x is None or abs(self.target_x - self.x) < 4:
                        span = self.w * 1.5
                        self.target_x = min(max(self._search_anchor
                                                + random.uniform(-span, span),
                                                lft), rgt)
                    dx = self.target_x - self.x
                    self.facing = 1 if dx > 0 else -1
                    self.x += max(-6, min(6, dx))     # fast step
                else:
                    self._search_anchor = None        # re-anchor next search episode
                self.y = floor
                self._render_state = eff

        self.move(int(self.x), int(self.y))
        self.update()

    def _roam(self):
        left, right, top, floor = self._bounds()
        # surface under us dropped away (window closed/moved, or we walked off a
        # ledge) -> fall to it instead of snapping/teleporting.
        if self.y < floor - 2:
            self.vx = 0.0
            self.vy = 0.0
            self.mode = "thrown"
            self.target_x = None
            return
        if self.walk_pause > 0:
            self.walk_pause -= 1
            # occasionally glance the other way while resting (looks alive)
            if random.random() < 0.01:
                self.facing = -self.facing
            self.y = floor
            self._render_state = self.claude_state
            return
        if self.target_x is None:
            if random.random() < 0.012:
                # wander mostly nearby; now and then take a longer stroll
                reach = (random.uniform(120, 320) if random.random() < 0.8
                         else random.uniform(320, 900))
                direction = 1 if random.random() < 0.5 else -1
                self.target_x = min(max(self.x + direction * reach, left), right)
                self._walk_speed = random.uniform(1.8, 2.8)   # slight pace variety
            self.y = floor
            self._render_state = self.claude_state
            return
        speed = self._walk_speed
        dx = self.target_x - self.x
        if abs(dx) <= speed:
            self.x = self.target_x
            self.target_x = None
            # mostly short pauses, occasionally a longer rest
            self.walk_pause = (random.randint(20, 90) if random.random() < 0.8
                               else random.randint(120, 260))
            self._render_state = self.claude_state
        else:
            self.facing = 1 if dx > 0 else -1
            self.x += speed * self.facing
            self._render_state = self._walk_render()
        self.y = floor

    def _walk_render(self):
        """Render state while walking a roam leg: an auto_* variant walks with its
        visor + prop on; plain idle/waiting roaming shows the generic walk."""
        return self.claude_state if self.claude_state in AUTO_STATES else "walk"

    def _on_cursor(self, xy):
        try:
            xs, ys = xy.split(",")
            self._cursor = (int(float(xs)), int(float(ys)))
        except (ValueError, AttributeError):
            pass

    def _cursor_pos(self):
        """Global cursor (x, y). Prefer the compositor-pushed value (works even
        when the cursor is over another window); fall back to Qt's own, which is
        only accurate while the cursor is over our surface."""
        if self._cursor is not None:
            return self._cursor
        p = QCursor.pos()
        return (p.x(), p.y())

    def _physics(self):
        left, right, top, floor = self._bounds()
        self.x, self.y, self.vx, self.vy, settled = physics.advance(
            self.x, self.y, self.vx, self.vy, left, right, top, floor)
        if settled:
            self.mode = "roam"
            self._render_state = self.claude_state
        else:
            self._render_state = "falling"   # tumbling through the air

    def _setup_geom_feed(self):
        """Register a D-Bus service and start a persistent KWin script that pushes
        window geometry to it. All KDE-specific; any failure -> feature just off
        (self._wins stays empty, behaviour == pre-perch)."""
        try:
            safe = re.sub(r"[^A-Za-z0-9_]", "_", str(self.session_id))
            self._dbus_name = "org.claudepet.geom_" + safe
            self._receiver = _GeomReceiver(self)
            bus = QDBusConnection.sessionBus()
            if not bus.registerService(self._dbus_name):
                self._dbus_name = None
                return
            bus.registerObject("/", self._receiver,
                               QDBusConnection.RegisterOption.ExportAllSlots)
            self._start_geom_script()
        except Exception:
            self._dbus_name = None

    def _start_geom_script(self):
        svc = self._dbus_name
        js = (
            'var SVC="' + svc + '";'
            # only windows on the CURRENT virtual desktop count (a perched pet is
            # sticky/all-desktops, so a window that leaves the desktop must drop
            # out of the feed -> pet falls to the desktop floor instead of
            # hovering where the vanished window was).
            'function _onDesk(c){'
            '  if(c.onAllDesktops)return true;'
            '  try{'
            '    if(c.desktops&&c.desktops.length!==undefined){var cur=workspace.currentDesktop;'
            '      for(var k=0;k<c.desktops.length;k++){if(c.desktops[k]===cur)return true;}'
            '      return false;}'
            '    if(typeof c.desktop==="number")'
            '      return c.desktop<0||c.desktop===workspace.currentDesktop;'
            '  }catch(e){}'
            '  return true;}'                             # unknown API -> don't filter
            'function _dump(){'
            # stackingOrder is bottom->top, so windows.window_at's "last match
            # wins" correctly picks the TOPMOST window under the pet.
            '  var ws=(typeof workspace.stackingOrder!=="undefined"&&workspace.stackingOrder)'
            '    ?workspace.stackingOrder'
            '    :((typeof workspace.windowList==="function")'
            '      ?workspace.windowList():workspace.clientList());'
            '  var o=[];'
            '  for(var i=0;i<ws.length;i++){var c=ws[i];var g=c.frameGeometry;'
            '    if(g&&!c.minimized&&!c.hidden&&_onDesk(c))'   # visible, on this desktop
            '      o.push(c.internalId+";"+(c.resourceClass||"")+";"'
            '      +g.x+","+g.y+","+g.width+","+g.height);}'
            '  callDBus(SVC,"/","","push",o.join("|"));'
            '}'
            'function _hook(c){if(!c)return;'
            '  if((""+(c.resourceClass||"")).toLowerCase().indexOf("claude-pet")>=0)'
            '    return;'                                  # never react to our own window
            '  if(c.frameGeometryChanged)c.frameGeometryChanged.connect(_dump);'
            '  if(c.minimizedChanged)c.minimizedChanged.connect(_dump);}'  # refresh on (un)minimize
            'var _w=(typeof workspace.windowList==="function")'
            '  ?workspace.windowList():workspace.clientList();'
            'for(var i=0;i<_w.length;i++)_hook(_w[i]);'
            'if(workspace.windowAdded)workspace.windowAdded.connect('
            '  function(c){_hook(c);_dump();});'
            'if(workspace.windowRemoved)workspace.windowRemoved.connect(_dump);'
            '_dump();'
        )
        # stable plugin name so a re-launched pet for the SAME session replaces
        # its old script instead of stacking a new one (orphans otherwise pile up
        # and each keeps re-dumping on every geometry change).
        self._geom_plugin = "claudepet_geom_" + re.sub(
            r"[^A-Za-z0-9_]", "_", str(self.session_id))
        try:
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.unloadScript", self._geom_plugin],
                           timeout=3, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
                path = f.name
            sid = subprocess.check_output(
                ["qdbus6", "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.loadScript", path, self._geom_plugin],
                text=True, timeout=3).strip()
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.start"], timeout=3)
            self._geom_script_id = sid          # persistent — do NOT stop now
            os.unlink(path)
        except Exception:
            pass

    def _start_cursor_feed(self):
        """Load a KWin script that pushes the global cursor position on move.
        Loaded ONLY while follow is on (idle cost is zero otherwise)."""
        svc = getattr(self, "_dbus_name", None)
        if not svc:
            return                              # no DBus channel -> QCursor fallback
        js = (
            'var SVC="' + svc + '";var _cx=-999,_cy=-999;'
            'if(workspace.cursorPosChanged)workspace.cursorPosChanged.connect('
            '  function(){var p=workspace.cursorPos;'
            '    if(Math.abs(p.x-_cx)+Math.abs(p.y-_cy)>=3){_cx=p.x;_cy=p.y;'
            '      callDBus(SVC,"/","","cursor",p.x+","+p.y);}});'
        )
        self._cursor_plugin = "claudepet_cursor_" + re.sub(
            r"[^A-Za-z0-9_]", "_", str(self.session_id))
        try:
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.unloadScript", self._cursor_plugin],
                           timeout=3, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
                path = f.name
            subprocess.check_output(
                ["qdbus6", "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.loadScript", path, self._cursor_plugin],
                text=True, timeout=3)
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.start"], timeout=3)
            os.unlink(path)
        except Exception:
            pass

    def _stop_cursor_feed(self):
        plugin = getattr(self, "_cursor_plugin", None)
        if plugin:
            try:
                subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                "org.kde.kwin.Scripting.unloadScript", plugin],
                               timeout=3, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            except Exception:
                pass
            self._cursor_plugin = None
        self._cursor = None                     # drop stale pos -> QCursor fallback

    def _on_geom(self, dump):
        if dump == getattr(self, "_last_dump", None):
            return                       # coalesce identical pushes (cheap anti-spam)
        self._last_dump = dump
        self._wins = windows.parse_kwin_dump(dump)
        if self._contain is not None:
            self._contain = next(
                (w for w in self._wins if w.wid == self._contain.wid), None)

    def _bounds(self):
        """(left, right, top, floor) for the current context. On the desktop the
        floor is dynamic — the top edge of whatever window is under us (perch).
        When contained, bounds are the window's interior."""
        if self._contain is not None:
            c = self._contain
            if c.w < self.w:                 # window narrower than the pet:
                left = right = c.x + (c.w - self.w) / 2.0   # centre it, don't jut right
            else:
                left = c.x
                right = c.x + c.w - self.w
            if c.h < self.h:                 # window shorter than the pet: centre
                top = floor = c.y + (c.h - self.h) / 2.0
            else:
                top = c.y
                floor = c.y + c.h - self.h
            return left, right, top, floor
        scr = self.screen_rect
        left = scr.left()
        right = scr.right() - self.w
        top = scr.top()
        cx = self.x + self.w / 2.0
        feet = self.y + FOOT_Y
        screen_bottom = self._screen_bottom_at(cx)
        surface = windows.support_surface_under(cx, self._wins, screen_bottom, feet)
        if surface >= screen_bottom:
            floor = surface - self.h        # screen floor: keep window fully on-screen
        else:
            floor = surface - FOOT_Y        # window perch: feet on the top edge
        return left, right, top, floor

    def _screen_bottom_at(self, cx):
        """Bottom (floor) of the monitor whose column covers cx, so a pet on a
        taller/shorter/offset monitor rests on that monitor's floor rather than a
        single global bottom. Falls back to the union bottom for dead columns."""
        for g in self._screens:
            if g.left() <= cx <= g.right():
                return g.bottom()
        return self.screen_rect.bottom()

    # ---------- painting ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        state = getattr(self, "_render_state", self.claude_state)
        frames = self._sprites.get(state)
        if frames:
            self._blit_sprite(p, frames[self.frame % len(frames)])
        else:
            # facing handled inside draw_creature (body mirrors, text upright)
            C.draw_creature(p, PAD_X * U, PAD_Y * U, U, state, self.frame,
                            facing=self.facing)
        p.end()

    def _blit_sprite(self, p, pm):
        """Draw a user sprite frame fit inside the window (aspect-preserving,
        centred), mirrored when facing left. Nearest-neighbour keeps pixel art
        crisp."""
        scaled = pm.scaled(self.w, self.h, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.FastTransformation)
        x = (self.w - scaled.width()) // 2
        y = (self.h - scaled.height()) // 2
        if self.facing < 0:
            p.save()
            p.translate(self.w, 0)
            p.scale(-1, 1)
            p.drawPixmap(x, y, scaled)   # centred, so the mirror stays in place
            p.restore()
        else:
            p.drawPixmap(x, y, scaled)

    # ---------- interaction ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_global = e.globalPosition().toPoint()
            self._press_winpos = self.frameGeometry().topLeft()
            self._moved = False
            self._vel_samples = [(time.monotonic(), self._press_global)]
            self.mode = "held"
        elif e.button() == Qt.MouseButton.RightButton:
            self._menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self._press_global is None:
            return
        g = e.globalPosition().toPoint()
        delta = g - self._press_global
        if delta.manhattanLength() > 6:
            self._moved = True
        newpos = self._press_winpos + delta
        self.x = float(newpos.x())
        self.y = float(newpos.y())
        self.move(int(self.x), int(self.y))
        self._vel_samples.append((time.monotonic(), g))
        self._vel_samples = self._vel_samples[-6:]

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if not self._moved:
            self._activate_claude()
            self.mode = "roam"
        elif self._floating:
            # floating: stay put wherever you drop it — no fall, no perch, no
            # snap-back. `stop` is what restores gravity.
            self._contain = None
            self.vx = self.vy = 0.0
            self.mode = "roam"
        else:
            vx = vy = 0.0
            if len(self._vel_samples) >= 2:
                (t0, p0), (t1, p1) = self._vel_samples[0], self._vel_samples[-1]
                dt = max(1e-3, t1 - t0)
                vx = (p1.x() - p0.x()) / dt / FPS
                vy = (p1.y() - p0.y()) / dt / FPS
            cxp = int(self.x + self.w / 2)
            cyp = int(self.y + self.h / 2)
            win = windows.window_at(cxp, cyp, self._wins)
            fling = (vx * vx + vy * vy) ** 0.5 >= 8.0
            if win is not None:
                # inside a window: a fling bounces around its interior walls,
                # a gentle drop just perches. Drag the pet's centre OUT of the
                # window to leave it.
                self._contain = win
                if fling:
                    self.vx, self.vy = vx, vy
                    self.mode = "thrown"      # bounces within the window bounds
                else:
                    self.mode = "roam"
                    self.target_x = None
            else:
                # on the desktop -> leave any window and fly
                self._contain = None
                self.vx, self.vy = vx, vy
                self.mode = "thrown"
        self._press_global = None

    def _menu(self, gpos):
        m = QMenu()
        a_follow = QAction("커서 따라오기", m, checkable=True)
        a_follow.setChecked(self._follow)
        m.addAction(a_follow)

        sub = m.addMenu("모션")
        motion_acts = {}
        for label, name, dur in MOTION_MENU:
            act = QAction(label, sub)
            sub.addAction(act)
            motion_acts[act] = (name, dur)

        a_float = QAction("둥둥 띄우기 (중력 끄기)", m, checkable=True)
        a_float.setChecked(self._floating)
        m.addAction(a_float)

        a_dnd = QAction("조용히 (알림 끔)", m, checkable=True)
        a_dnd.setChecked(self.dnd)
        m.addAction(a_dnd)
        a_release = None
        if self._contain is not None:
            a_release = QAction("창에서 꺼내기", m)
            m.addAction(a_release)
        m.addSeparator()
        a_quit = QAction("종료", m)
        m.addAction(a_quit)
        chosen = m.exec(gpos)
        if chosen is None:
            return
        if chosen == a_follow:
            self._toggle_follow()
        elif chosen in motion_acts:
            name, dur = motion_acts[chosen]
            self._play_motion(name, dur)
        elif chosen == a_float:
            self._toggle_float()
        elif chosen == a_dnd:
            self._toggle_dnd()
        elif a_release is not None and chosen == a_release:
            self._contain = None
        elif chosen == a_quit:
            self._quit()

    # ---------- shared menu actions (used by both the pet and the tray) ----------
    def _toggle_follow(self):
        self._follow = not self._follow
        if self._follow:
            self.walk_pause = 0           # follows within its window if perched
            if self.mode == "thrown":
                self.mode = "roam"
            self._start_cursor_feed()     # start reading the cursor only now
        else:
            self._stop_cursor_feed()      # stop the feed -> zero idle cost
        if getattr(self, "_act_follow", None) is not None:
            self._act_follow.setChecked(self._follow)

    def _toggle_dnd(self):
        self.dnd = not self.dnd
        if getattr(self, "_act_dnd", None) is not None:
            self._act_dnd.setChecked(self.dnd)

    def _play_motion(self, name, dur=2.5):
        # reuse the same path as a socket motion command (menu is in-process)
        self._handle_event({"cmd": "motion", "motion": name, "dur": dur})

    def _toggle_float(self):
        # off -> clear (restores gravity); on -> float mode
        self._handle_event({"cmd": "motion",
                            "motion": None if self._floating else "float",
                            "dur": 0})

    def _sync_float_check(self):
        # keep the persistent tray checkbox in step with the float mode
        if getattr(self, "_act_float", None) is not None:
            self._act_float.setChecked(self._floating)

    def _quit(self):
        self._cleanup()
        QApplication.quit()

    # ---------- system tray ----------
    def _init_tray(self):
        self._tray_state = None
        self._act_dnd = None
        self._act_float = None
        self._act_follow = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(self)
        m = QMenu()
        self._act_follow = QAction("커서 따라오기", m, checkable=True)
        m.addAction(self._act_follow)
        self._act_follow.triggered.connect(self._toggle_follow)

        sub = m.addMenu("모션")
        for label, name, dur in MOTION_MENU:
            act = QAction(label, sub)
            sub.addAction(act)
            act.triggered.connect(
                lambda _checked=False, n=name, d=dur: self._play_motion(n, d))

        self._act_float = QAction("둥둥 띄우기 (중력 끄기)", m, checkable=True)
        m.addAction(self._act_float)
        self._act_float.triggered.connect(self._toggle_float)

        self._act_dnd = QAction("조용히 (알림 끔)", m, checkable=True)
        m.addAction(self._act_dnd)
        act_quit = QAction("종료", m)
        m.addSeparator()
        m.addAction(act_quit)
        self._act_dnd.triggered.connect(self._toggle_dnd)
        act_quit.triggered.connect(self._quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._on_tray_activated)
        self._update_tray_icon(force=True)
        self.tray.show()

    def _on_tray_activated(self, reason):
        # left-click (Trigger) mirrors clicking the pet: raise the terminal
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._activate_claude()

    def _update_tray_icon(self, force=False):
        tray = getattr(self, "tray", None)
        if tray is None:
            return
        st = self.claude_state
        if not force and st == self._tray_state:
            return
        self._tray_state = st
        tray.setIcon(self._state_icon(st))
        tray.setToolTip("claude-pet — " + STATE_LABELS.get(st, st))

    def _state_icon(self, state):
        """Render one representative frame of `state` into a tray QIcon."""
        u = 2
        cw, ch = C.GRID_W * u, C.GRID_H * u
        side = max(cw, ch)
        pm = QPixmap(side, side)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        ox = (side - cw) // 2
        oy = (side - ch) // 2
        C.draw_creature(p, ox, oy, u, state, _ICON_FRAME.get(state, 3))
        p.end()
        return QIcon(pm)

    # ---------- KWin scripting helper (KDE Wayland) ----------
    def _run_kwin_script(self, js):
        """Load and run a one-shot KWin script under a STABLE plugin name, so the
        next call (and _cleanup) unloads the previous one instead of leaving a
        stopped-but-registered script behind on every click-to-focus. Best-effort;
        never raises."""
        plugin = "claudepet_act_" + re.sub(r"[^A-Za-z0-9_]", "_", str(self.session_id))
        try:
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.unloadScript", plugin],
                           timeout=3, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
                path = f.name
            subprocess.check_output(
                ["qdbus6", "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.loadScript", path, plugin],
                text=True, timeout=3)
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.start"], timeout=3)
            os.unlink(path)
            self._activate_plugin = plugin
        except Exception:
            pass

    # ---------- bring the Claude Code terminal forward (KDE Wayland) ----------
    def _activate_claude(self):
        classes = self.host_classes or ["konsole"]
        want = "[" + ",".join('"%s"' % c for c in classes) + "]"
        self._run_kwin_script(
            'var want = ' + want + ';'
            'var cs = (typeof workspace.windowList === "function") '
            '? workspace.windowList() : workspace.clientList();'
            'for (var i = 0; i < cs.length; i++) {'
            '  var c = cs[i];'
            '  var rc = (c.resourceClass || "").toString().toLowerCase();'
            '  var hit = false;'
            '  for (var j = 0; j < want.length; j++) {'
            '    if (rc.indexOf(want[j]) >= 0) { hit = true; break; }'
            '  }'
            '  if (hit) {'
            '    try { workspace.activeWindow = c; } catch (e) { workspace.activeClient = c; }'
            '    c.minimized = false; break;'
            '  }'
            '}'
        )

    # ---------- drop our own taskbar/pager entry (KDE Wayland) ----------
    def _skip_taskbar(self):
        # EWMH via wmctrl is the reliable path on X11/XWayland. (KWin scripting
        # sets skipPager/skipSwitcher but NOT skipTaskbar — verified 2026-07-09.)
        # Match the window by its exact title so we don't hit other windows
        # (e.g. an editor whose title merely contains "claude-pet").
        if shutil.which("wmctrl"):
            try:
                # sticky = show on every virtual desktop, so switching desktops
                # doesn't make the pet vanish.
                subprocess.run(
                    ["wmctrl", "-F", "-r", self._wtitle,
                     "-b", "add,skip_taskbar,skip_pager,sticky"],
                    timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass
        # fallback (no wmctrl): KWin scripting — sets pager/switcher at least.
        self._run_kwin_script(
            'var cs = (typeof workspace.windowList === "function") '
            '? workspace.windowList() : workspace.clientList();'
            'for (var i = 0; i < cs.length; i++) {'
            '  var c = cs[i];'
            '  var cap = (c.caption || "").toString().toLowerCase();'
            '  var rc = (c.resourceClass || "").toString().toLowerCase();'
            '  if (cap.indexOf("claude-pet") >= 0 || rc.indexOf("claude-pet") >= 0) {'
            '    c.skipTaskbar = true; c.skipPager = true; c.skipSwitcher = true;'
            '    c.onAllDesktops = true;'
            '  }'
            '}'
        )

    def _cleanup(self):
        self._stop_cursor_feed()
        for plugin in (getattr(self, "_activate_plugin", None),):
            if plugin:
                try:
                    subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                    "org.kde.kwin.Scripting.unloadScript", plugin],
                                   timeout=3, stderr=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL)
                except Exception:
                    pass
        if getattr(self, "_geom_plugin", None):
            try:
                subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                                "org.kde.kwin.Scripting.unloadScript", self._geom_plugin],
                               timeout=3, stderr=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL)
            except Exception:
                pass
        try:
            os.unlink(self.sock_path)
        except OSError:
            pass


def main():
    import argparse
    import signal
    import fcntl
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="default")
    ap.add_argument("--host", default="unknown")
    ap.add_argument("--claude-pid", type=int, default=0)
    args, _ = ap.parse_known_args()

    # One pet per session: hold an exclusive lock. If another pet already holds
    # it (e.g. two SessionStart hooks racing), exit BEFORE touching the shared
    # socket — otherwise the second pet would unlink the first's socket.
    lock_fd = os.open(hostinfo.session_sock(args.session) + ".lock",
                      os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock_fd)
        return                                # another pet for this session lives

    app = QApplication(sys.argv[:1])          # keep our flags away from Qt
    app.setApplicationName("claude-pet")
    app.setDesktopFileName("claude-pet")
    app.setQuitOnLastWindowClosed(False)
    pet = Pet(session_id=args.session, host=args.host)
    pet._lock_fd = lock_fd                    # keep the fd (and the lock) alive
    # always tear down the KWin geom script — including on `kill`/SIGTERM, which
    # otherwise skips _cleanup and leaks a script that keeps pushing geometry.
    app.aboutToQuit.connect(pet._cleanup)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # wake the interpreter periodically so Python signal handlers run under Qt
    _sig_timer = QTimer()
    _sig_timer.timeout.connect(lambda: None)
    _sig_timer.start(300)
    # orphan reaper: if the Claude process that spawned us dies without sending
    # SessionEnd (e.g. SIGKILL), wind down instead of lingering forever.
    _reaper = None
    if args.claude_pid > 0:
        def _check_parent():
            try:
                os.kill(args.claude_pid, 0)
            except ProcessLookupError:
                app.quit()
            except OSError:
                pass                          # EPERM etc. -> assume still alive
        _reaper = QTimer()
        _reaper.timeout.connect(_check_parent)
        _reaper.start(3000)
    pet.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
