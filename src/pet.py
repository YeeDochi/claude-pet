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
from state_engine import StateEngine
import focus
import hostinfo
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
    "attention": "입력 대기!", "celebrate": "완료!", "error": "에러",
}
# representative animation frame to freeze for each state's tray icon
_ICON_FRAME = {"work_computer": 100, "walk": 6, "work_search": 4}

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

        scr = QApplication.primaryScreen().availableGeometry()
        self.screen_rect = scr
        self.floor_y = scr.bottom() - self.h
        self.x = float(random.uniform(scr.left(), max(scr.left(), scr.right() - self.w)))
        self.y = float(self.floor_y)
        self.move(int(self.x), int(self.y))

        self.frame = 0
        self.facing = 1
        self.engine = StateEngine(is_focused=self._is_focused)
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

        roaming = eff in ("idle", "sleeping") and self.mode == "roam" and not self.dnd

        if self.mode == "thrown":
            self._physics()
        elif roaming:
            self._roam()
        else:
            # stationary Claude state (working / attention / thinking / ...)
            if eff == "work_search":
                # quick random horizontal darts while rummaging
                lft, rgt, _t, _f = self._bounds()
                if self.target_x is None or abs(self.target_x - self.x) < 4:
                    span = self.w * 3
                    self.target_x = min(max(self.x + random.uniform(-span, span),
                                            lft), rgt)
                dx = self.target_x - self.x
                self.facing = 1 if dx > 0 else -1
                self.x += max(-6, min(6, dx))     # fast step
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
            self.y = floor
            self._render_state = self.claude_state
            return
        if self.target_x is None:
            if random.random() < 0.012:
                self.target_x = random.uniform(left, max(left, right))
            self.y = floor
            self._render_state = self.claude_state
            return
        speed = 2.2
        dx = self.target_x - self.x
        if abs(dx) <= speed:
            self.x = self.target_x
            self.target_x = None
            self.walk_pause = random.randint(20, 90)
            self._render_state = self.claude_state
        else:
            self.facing = 1 if dx > 0 else -1
            self.x += speed * self.facing
            self._render_state = "walk"
        self.y = floor

    def _physics(self):
        left, right, top, floor = self._bounds()
        self.x, self.y, self.vx, self.vy, settled = physics.advance(
            self.x, self.y, self.vx, self.vy, left, right, top, floor)
        if settled:
            self.mode = "roam"
        self._render_state = self.claude_state

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
            'function _dump(){'
            '  var ws=(typeof workspace.windowList==="function")'
            '    ?workspace.windowList():workspace.clientList();'
            '  var o=[];'
            '  for(var i=0;i<ws.length;i++){var c=ws[i];var g=c.frameGeometry;'
            '    if(g)o.push(c.internalId+";"+(c.resourceClass||"")+";"'
            '      +g.x+","+g.y+","+g.width+","+g.height);}'
            '  callDBus(SVC,"/","","push",o.join("|"));'
            '}'
            'function _hook(c){if(c&&c.frameGeometryChanged&&'
            '  (""+(c.resourceClass||"")).toLowerCase().indexOf("claude-pet")<0)'
            '  c.frameGeometryChanged.connect(_dump);}'
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
            left = c.x
            right = max(left, c.x + c.w - self.w)
            top = c.y
            floor = max(top, c.y + c.h - self.h)
            return left, right, top, floor
        scr = self.screen_rect
        left = scr.left()
        right = scr.right() - self.w
        top = scr.top()
        cx = self.x + self.w / 2.0
        feet = self.y + FOOT_Y
        surface = windows.support_surface_under(cx, self._wins, scr.bottom(), feet)
        if surface >= scr.bottom():
            floor = surface - self.h        # screen floor: keep window fully on-screen
        else:
            floor = surface - FOOT_Y        # window perch: feet on the top edge
        return left, right, top, floor

    # ---------- painting ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        state = getattr(self, "_render_state", self.claude_state)
        # facing handled inside draw_creature (body mirrors, text stays upright)
        C.draw_creature(p, PAD_X * U, PAD_Y * U, U, state, self.frame, facing=self.facing)
        p.end()

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
        else:
            cxp = int(self.x + self.w / 2)
            cyp = int(self.y + self.h / 2)
            win = windows.window_at(cxp, cyp, self._wins)
            if win is not None:
                # dropped onto a window -> live inside it
                self._contain = win
                self.mode = "roam"
                self.target_x = None
            else:
                # dropped on the desktop -> leave any window and throw
                self._contain = None
                if len(self._vel_samples) >= 2:
                    (t0, p0), (t1, p1) = self._vel_samples[0], self._vel_samples[-1]
                    dt = max(1e-3, t1 - t0)
                    self.vx = (p1.x() - p0.x()) / dt / FPS
                    self.vy = (p1.y() - p0.y()) / dt / FPS
                self.mode = "thrown"
        self._press_global = None

    def _menu(self, gpos):
        m = QMenu()
        a_come = QAction("이리와", m)
        a_dnd = QAction("조용히 (알림 끔)", m, checkable=True)
        a_dnd.setChecked(self.dnd)
        a_quit = QAction("종료", m)
        m.addAction(a_come)
        m.addAction(a_dnd)
        a_release = None
        if self._contain is not None:
            a_release = QAction("창에서 꺼내기", m)
            m.addAction(a_release)
        m.addSeparator()
        m.addAction(a_quit)
        chosen = m.exec(gpos)
        if chosen == a_come:
            self._come_here()
        elif chosen == a_dnd:
            self._toggle_dnd()
        elif a_release is not None and chosen == a_release:
            self._contain = None
        elif chosen == a_quit:
            self._quit()

    # ---------- shared menu actions (used by both the pet and the tray) ----------
    def _come_here(self):
        c = QCursor.pos()
        self.target_x = min(max(c.x() - self.w // 2, self.screen_rect.left()),
                            self.screen_rect.right() - self.w)
        self.walk_pause = 0
        self.mode = "roam"

    def _toggle_dnd(self):
        self.dnd = not self.dnd
        if getattr(self, "_act_dnd", None) is not None:
            self._act_dnd.setChecked(self.dnd)

    def _quit(self):
        self._cleanup()
        QApplication.quit()

    # ---------- system tray ----------
    def _init_tray(self):
        self._tray_state = None
        self._act_dnd = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(self)
        m = QMenu()
        act_come = QAction("이리와", m)
        self._act_dnd = QAction("조용히 (알림 끔)", m, checkable=True)
        act_quit = QAction("종료", m)
        m.addAction(act_come)
        m.addAction(self._act_dnd)
        m.addSeparator()
        m.addAction(act_quit)
        act_come.triggered.connect(self._come_here)
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
        """Load, run and unload a one-shot KWin script. Best-effort; never raises."""
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
                path = f.name
            sid = subprocess.check_output(
                ["qdbus6", "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.loadScript", path],
                text=True, timeout=3).strip()
            subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.start"], timeout=3)
            subprocess.run(["qdbus6", "org.kde.KWin", f"/Scripting/Script{sid}",
                            "org.kde.kwin.Script.stop"], timeout=3,
                           stderr=subprocess.DEVNULL)
            os.unlink(path)
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
                subprocess.run(
                    ["wmctrl", "-F", "-r", self._wtitle,
                     "-b", "add,skip_taskbar,skip_pager"],
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
            '  }'
            '}'
        )

    def _cleanup(self):
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="default")
    ap.add_argument("--host", default="unknown")
    args, _ = ap.parse_known_args()

    app = QApplication(sys.argv[:1])          # keep our flags away from Qt
    app.setApplicationName("claude-pet")
    app.setDesktopFileName("claude-pet")
    app.setQuitOnLastWindowClosed(False)
    pet = Pet(session_id=args.session, host=args.host)
    # always tear down the KWin geom script — including on `kill`/SIGTERM, which
    # otherwise skips _cleanup and leaks a script that keeps pushing geometry.
    app.aboutToQuit.connect(pet._cleanup)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # wake the interpreter periodically so Python signal handlers run under Qt
    _sig_timer = QTimer()
    _sig_timer.timeout.connect(lambda: None)
    _sig_timer.start(300)
    pet.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
