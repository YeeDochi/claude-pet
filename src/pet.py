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
import socket
import subprocess
import tempfile
import time

from PyQt6.QtWidgets import QApplication, QWidget, QMenu
from PyQt6.QtGui import QPainter, QAction, QCursor
from PyQt6.QtCore import Qt, QTimer, QSocketNotifier, QPoint

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import creature as C
from state_engine import StateEngine
import focus

# ---- config ----
U = 5                                   # art-pixel size in device px
PAD_X, PAD_Y = 1, 2                     # padding (art px) around creature for props
FPS = 20
SOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "claude-pet.sock")
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


class Pet(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.w = (C.GRID_W + 2 * PAD_X) * U
        self.h = (C.GRID_H + 2 * PAD_Y) * U
        self.setFixedSize(self.w, self.h)

        scr = QApplication.primaryScreen().availableGeometry()
        self.screen_rect = scr
        self.floor_y = scr.bottom() - self.h
        self.x = float(scr.left() + scr.width() // 2)
        self.y = float(self.floor_y)
        self.move(int(self.x), int(self.y))

        self.frame = 0
        self.facing = 1
        self.engine = StateEngine(is_focused=focus.terminal_focused)
        self.claude_state = "sleeping"       # last state the engine reported
        self.dnd = False                     # do-not-disturb

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

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(int(1000 / FPS))

    # ---------- Claude Code hook socket ----------
    def _init_socket(self):
        try:
            os.unlink(SOCK_PATH)
        except FileNotFoundError:
            pass
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(SOCK_PATH)
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

    # ---------- main loop ----------
    def _tick(self):
        self.frame += 1
        now = time.monotonic()
        self.claude_state = self.engine.display_state(now)
        eff = self.claude_state

        roaming = eff in ("idle", "sleeping") and self.mode == "roam" and not self.dnd

        if self.mode == "thrown":
            self._physics()
        elif roaming:
            self._roam()
        else:
            # stationary Claude state (working / attention / thinking / ...)
            if eff == "work_search":
                # quick random horizontal darts while rummaging
                if self.target_x is None or abs(self.target_x - self.x) < 4:
                    span = self.w * 3
                    self.target_x = min(max(self.x + random.uniform(-span, span),
                                            self.screen_rect.left()),
                                        self.screen_rect.right() - self.w)
                dx = self.target_x - self.x
                self.facing = 1 if dx > 0 else -1
                self.x += max(-6, min(6, dx))     # fast step
            self._render_state = eff

        self.move(int(self.x), int(self.y))
        self.update()

    def _roam(self):
        if self.walk_pause > 0:
            self.walk_pause -= 1
            self._render_state = self.claude_state
            return
        if self.target_x is None:
            if random.random() < 0.012:      # occasionally decide to wander
                margin = self.w
                self.target_x = random.uniform(self.screen_rect.left(),
                                                self.screen_rect.right() - margin)
            self._render_state = self.claude_state
            return
        # walk toward target
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
            self.y = self.floor_y
            self._render_state = "walk"

    def _physics(self):
        g = 1.4
        self.vy += g
        self.x += self.vx
        self.y += self.vy
        L, R = self.screen_rect.left(), self.screen_rect.right() - self.w
        if self.x < L:
            self.x = L; self.vx = -self.vx * 0.5
        elif self.x > R:
            self.x = R; self.vx = -self.vx * 0.5
        if self.y >= self.floor_y:
            self.y = self.floor_y
            self.vy = -self.vy * 0.45
            self.vx *= 0.6
            if abs(self.vy) < 2 and abs(self.vx) < 0.6:
                self.vy = self.vx = 0.0
                self.mode = "roam"
        self._render_state = self.claude_state

    # ---------- painting ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        state = getattr(self, "_render_state", self.claude_state)
        p.save()
        if self.facing < 0:
            p.translate(self.w, 0)
            p.scale(-1, 1)
        C.draw_creature(p, PAD_X * U, PAD_Y * U, U, state, self.frame, facing=self.facing)
        p.restore()
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
            # compute throw velocity from recent samples
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
        m.addSeparator()
        m.addAction(a_quit)
        chosen = m.exec(gpos)
        if chosen == a_come:
            c = QCursor.pos()
            self.target_x = min(max(c.x() - self.w // 2, self.screen_rect.left()),
                                self.screen_rect.right() - self.w)
            self.walk_pause = 0
            self.mode = "roam"
        elif chosen == a_dnd:
            self.dnd = not self.dnd
        elif chosen == a_quit:
            self._cleanup()
            QApplication.quit()

    # ---------- bring the Claude Code terminal forward (KDE Wayland) ----------
    def _activate_claude(self):
        js = (
            'var cs = (typeof workspace.windowList === "function") '
            '? workspace.windowList() : workspace.clientList();'
            'for (var i = 0; i < cs.length; i++) {'
            '  var c = cs[i];'
            '  var rc = (c.resourceClass || "").toString().toLowerCase();'
            '  if (rc.indexOf("konsole") >= 0) {'
            '    try { workspace.activeWindow = c; } catch (e) { workspace.activeClient = c; }'
            '    c.minimized = false;'
            '    break;'
            '  }'
            '}'
        )
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
            # best-effort unload
            subprocess.run(["qdbus6", "org.kde.KWin", f"/Scripting/Script{sid}",
                            "org.kde.kwin.Script.stop"], timeout=3,
                           stderr=subprocess.DEVNULL)
            os.unlink(path)
        except Exception:
            pass

    def _cleanup(self):
        try:
            os.unlink(SOCK_PATH)
        except OSError:
            pass


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    pet = Pet()
    pet.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
