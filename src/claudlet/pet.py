#!/usr/bin/env python3
"""claudlet — a roaming desktop buddy that reacts to Claude Code.

A frameless, translucent, always-on-top creature that wanders the desktop,
can be dragged & thrown, and switches expression based on Claude Code hook
events delivered over a loopback TCP socket by `claudlet-hook`.

Runs on KDE Wayland via XWayland (forced xcb platform) so the window can
position itself freely across the screen.
"""
import os
import sys
# On Linux, force XWayland (xcb): native Wayland forbids clients positioning
# their own windows, which a roaming pet needs. On macOS/Windows keep Qt's
# native platform (cocoa/windows) — forcing xcb there would fail to start.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

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
from PyQt6.QtGui import QPainter, QAction, QCursor, QIcon, QPixmap, QColor, QRegion, QPainterPath
from PyQt6.QtCore import Qt, QTimer, QSocketNotifier, QPoint, QRect, QRectF

from claudlet import roambounds
from claudlet.core import creature as C
from claudlet.core.state_engine import StateEngine, AUTO_ROAM, AUTO_STATES
from claudlet.platform import focus
from claudlet.platform import konsole
from claudlet.platform.qdbus import qdbus_bin
from claudlet.core import hostinfo
from claudlet.core import petconfig
from claudlet.core import physics
from claudlet.core import follow_nav
from claudlet.core import petting
from claudlet.core import social
from claudlet.core import idle_engine
from claudlet.core.idle_engine import IdleEnergy
from claudlet.platform import geom

# ---- config ----
U = 5                                   # art-pixel size in device px
PAD_X, PAD_Y = 1, 2                     # padding (art px) around creature for props
# Agent companion: an INDEPENDENT little creature in its own window that FOLLOWS
# the pet while a subagent runs — see the Companion class. It only walks toward
# the pet once the gap exceeds FOLLOW_START, and stops once within FOLLOW_STOP
# (hysteresis), like a real sidekick trailing along; no facing-based side pick
# (that made it teleport across when the pet turned).
COMPANION_U = 2.5                       # companion art-pixel size (half the pet's U=5)
# Follow feel: sets off soon after the pet leaves (short START gap), dawdles at a
# slow amble while close behind, but SPRINTS when left far behind — the "어?
# 늦었다!" scramble: speed*(1+gap/FACTOR), capped at speed*CAP.
COMPANION_SPEED = 1.8                   # base amble px/tick (pet walks 1.8-2.8)
COMPANION_RUN_FACTOR = 90.0             # gap that roughly doubles the speed
COMPANION_RUN_CAP = 8.0                 # sprint ceiling (~14 px/tick when far)
COMPANION_FOLLOW_START = 90             # center-gap (px) that makes it start following
COMPANION_FOLLOW_STOP = 60              # center-gap (px) it settles at / stops
COMPANION_BLINK_DY = 140                # feet-line y-gap that teleports it to the pet
                                        #   (landed on a different level after a throw)
COMPANION_REUNITE_TICKS = 90            # ticks a separated companion keeps trying to
                                        #   walk back before giving up and blinking
COMPANION_MAX = 3                       # companion cap: one per running agent, up to
                                        #   this many trailing in a duckling chain
COMPANION_BYE_DUR = 1.6                 # departing celebrate ("다 됐다!") before closing
FPS = 20

# short label per state (tray tooltip), per language
STATE_LABELS = {
    "ko": {
        "idle": "대기", "sleeping": "자는 중", "walk": "산책",
        "thinking": "고민 중", "work_computer": "작업 중", "work_search": "탐색 중",
        "work_web": "연락 중", "work_agent": "서브에이전트", "work_skill": "스킬 사용",
        "attention": "입력 대기!", "asking": "답 기다림", "autopilot": "자동 진행",
        "auto_computer": "자동·코딩", "auto_search": "자동·탐색", "auto_web": "자동·웹",
        "auto_agent": "자동·에이전트", "auto_skill": "자동·스킬",
        "celebrate": "완료!", "error": "에러",
    },
    "en": {
        "idle": "idle", "sleeping": "sleeping", "walk": "strolling",
        "thinking": "thinking", "work_computer": "working", "work_search": "searching",
        "work_web": "web", "work_agent": "subagent", "work_skill": "skill",
        "attention": "needs you!", "asking": "waiting", "autopilot": "autopilot",
        "auto_computer": "auto·edit", "auto_search": "auto·search", "auto_web": "auto·web",
        "auto_agent": "auto·subagent", "auto_skill": "auto·skill",
        "celebrate": "done!", "error": "error",
    },
}
# representative animation frame to freeze for each state's tray icon
_ICON_FRAME = {"work_computer": 100, "walk": 6, "work_search": 4}

# right-click / tray menu UI strings, per language
UI = {
    "ko": {"follow": "커서 따라오기", "motions": "모션",
           "float": "주머니 쏙 (고개만 빼꼼)", "quiet": "조용히 (알림 끔)",
           "release": "창에서 꺼내기", "quit": "종료",
           "comp_add": "🐣 컴패니언 추가 (테스트)",
           "comp_del": "컴패니언 제거 (테스트)",
           "zone_edit": "🚫 금지구역 편집", "zone_clear": "금지구역 지우기"},
    "en": {"follow": "Follow cursor", "motions": "Motions",
           "float": "Pocket (peek out)", "quiet": "Quiet (mute)",
           "release": "Release from window", "quit": "Quit",
           "comp_add": "🐣 Add companion (test)",
           "comp_del": "Remove companion (test)",
           "zone_edit": "🚫 Edit no-go zones", "zone_clear": "Clear no-go zones"},
}

# transient motions offered in the menus: (name, seconds, {lang: label})
MOTION_MENU = [
    ("jump", 2.5, {"ko": "점프", "en": "Jump"}),
    ("wave", 2.5, {"ko": "손 흔들기", "en": "Wave"}),
    ("sing", 3.0, {"ko": "노래", "en": "Sing"}),
    ("juggle", 3.0, {"ko": "저글링", "en": "Juggle"}),
    ("celebrate", 2.5, {"ko": "축하", "en": "Celebrate"}),
]

# device-px from the pet window's top down to the creature's feet (legs bottom).
# creature legs bottom ~15.8 art rows; with PAD_Y=2 and U=5: (2 + 15.8) * 5 ≈ 89.
# used to land the FEET on a window's top edge when perching (not the window box).
FOOT_Y = 89

PET_REACT_SEC = 1.5                     # 쓰다듬기 하트 반응 지속(초)

# follow-mode navigation thresholds (jump reach, alignment, strain margins)
# live in core/follow_nav.py -- the pure planner the follow branch delegates to.


def _macos_keep_visible(widget):
    """macOS-only: keep this Qt.Tool window on screen. Two AppKit fixes, both
    no-ops off macOS or without pyobjc, both safe from any widget's showEvent
    (the native NSView/NSWindow exists by then — see geom/macos.py for the why):
      - stop AppKit auto-hiding it when the pet's app is deactivated (user clicks
        another window);
      - stop the Show-Desktop / Mission Control gesture sweeping it off-screen."""
    if sys.platform != "darwin":
        return
    try:
        from claudlet.platform.geom import macos
        macos.keep_visible_on_deactivate(widget.winId())
        macos.keep_stationary_on_desktop(widget.winId())
    except Exception:
        pass


def _companion_flags(platform):
    """Window flags for the agent companion (pure, so it's unit-tested).

    It should sit at the same on-top z-order as the pet. On X11/Linux, though, a
    second *managed* always-on-top window fights the pet's interactive-move
    (drag) — that fight made the dragged pet jitter — so there we use
    BypassWindowManagerHint (override-redirect, WM leaves it alone) and position
    it by hand. BypassWindowManagerHint is X11-only: on Windows/macOS it gives no
    on-top behaviour at all, so the companion sank BEHIND windows while the pet
    (WindowStaysOnTopHint) stayed in front. Off X11, use StaysOnTop to match."""
    base = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
    if platform.startswith("linux"):
        return base | Qt.WindowType.BypassWindowManagerHint
    return base | Qt.WindowType.WindowStaysOnTopHint


def _same_win(a, b):
    """Two window handles refer to the same window (by id), or both are None."""
    if a is None or b is None:
        return a is None and b is None
    return a.wid == b.wid


class Companion(QWidget):
    """An independent little creature in its own window that FOLLOWS the pet
    while a subagent runs, through the SAME pure nav+physics core the pet uses
    (`follow_nav.plan_move` + `physics.advance`): it walks, jumps between
    windows, drops INTO a window to sit with the pet, climbs down, and falls
    under gravity — a real sidekick, not a lerp. When it truly can't reach
    (unreachably above / stranded a level away) it teleports beside the pet.
    Not user-grabbable (WA_TransparentForMouseEvents); the driving lives in
    Pet._sync_companion, which owns the window feed and screen bounds."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(_companion_flags(sys.platform))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # purely decorative: never take clicks/focus.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # COMPANION_U may be fractional (half the pet's U) — window dims are ints
        self.w = int((C.GRID_W + 2 * PAD_X) * COMPANION_U)
        self.h = int((C.GRID_H + 2 * PAD_Y) * COMPANION_U)
        self.setFixedSize(self.w, self.h)
        self.x = 0.0
        self.y = 0.0
        self.frame = 0
        self.facing = -1
        self._moving = False           # follow hysteresis: are we currently chasing?
        self._state = "idle"           # walk while chasing, idle when settled
        self._masked = False           # occlusion mask state (same trick as the pet)
        self._last_mask = None
        self.vx = 0.0                  # own physics while airborne (see fly)
        self.vy = 0.0
        self._air = False              # True while flying/bouncing on its own
        self._contain = None           # Win it lives INSIDE, or None (mirrors Pet)
        self.target_x = None           # current walk-leg target (pipeline)
        self._follow_jump = False      # air arc is a deliberate follow move ->
                                       # dead landing + window-entry resolution
        self._depart_until = None      # monotonic deadline of the goodbye wave
        self._reunite_ticks = 0        # ticks spent separated, trying to walk back
        self.hat = random.choice(C.HAT_KINDS)   # each sidekick gets its own hat

    def depart_tick(self):
        """One tick of the goodbye: stand and celebrate ('다 됐다!' bubble) until
        the deadline — the pet then closes this window. Announces the finish
        instead of blinking out of existence."""
        self._state = "celebrate"
        self.frame = (self.frame + 1) % 100000
        self.update()

    def apply_mask(self, region):
        """Mask-only visibility, mirroring Pet._apply_mask: full region drops the
        clip; an EMPTY region must become a 1px off-widget mask because Qt treats
        setMask(<empty>) as 'no mask' (would show everything)."""
        full = QRegion(QRect(0, 0, self.w, self.h))
        if region == full:
            if self._masked:
                self.clearMask()
                self._masked = False
                self._last_mask = None
            return
        if region.isEmpty():
            region = QRegion(QRect(-1, -1, 1, 1))
        if not self._masked or region != self._last_mask:
            self.setMask(region)
            self._masked = True
            self._last_mask = region

    def advance(self, target_x, ground_y, rest_state="idle"):
        """Follow the pet like a real sidekick: only START walking once the gap to
        the pet exceeds FOLLOW_START, and STOP once within FOLLOW_STOP (hysteresis
        so it doesn't jitter at the boundary). No facing-based side pick — it
        simply walks toward the pet from whichever side it's on, so the pet
        turning around never makes it teleport across. Stays on `ground_y`. When
        settled it shows `rest_state` — the subagent's current activity — so the
        companion mirrors what the agent is doing; while catching up it walks."""
        cx = self.x + self.w / 2.0
        dx = target_x - cx
        dist = abs(dx)
        if not self._moving and dist > COMPANION_FOLLOW_START:
            self._moving = True
        elif self._moving and dist <= COMPANION_FOLLOW_STOP:
            self._moving = False
        if self._moving:
            self.facing = 1 if dx > 0 else -1
            # hurry when far behind: speed grows with the gap, capped, then
            # settles back to a walk.
            speed = min(COMPANION_SPEED * (1.0 + dist / COMPANION_RUN_FACTOR),
                        COMPANION_SPEED * COMPANION_RUN_CAP)
            move = min(dist - COMPANION_FOLLOW_STOP, speed)
            if move > 0:
                self.x += self.facing * move
            self._state = "walk"
        else:
            self._state = rest_state or "idle"
        self.y = ground_y
        self.frame = (self.frame + 1) % 100000
        self.move(int(self.x), int(self.y))
        self.update()      # repaint EVERY tick — without this the walk cycle/bob
                           # never animates (move() alone doesn't trigger a paint)

    def hover_to(self, tx, ty, ease=0.22):
        """While the pet is HELD: hurry to the cursor and get 'picked up' too —
        ease toward a spot beside the held pet (both axes), dangling once there.
        So a throw launches the two from side by side, not screen-widths apart."""
        dx, dy = tx - self.x, ty - self.y
        if abs(dx) > 0.5:
            self.facing = 1 if dx > 0 else -1
        self.x += dx * ease
        self.y += dy * ease
        near = abs(dx) < 8 and abs(dy) < 8
        self._state = "held" if near else "walk"    # dangle once it arrives
        self._moving = True
        self._air = False                           # a grab cancels any flight
        self.frame = (self.frame + 1) % 100000
        self.move(int(self.x), int(self.y))
        self.update()

    def fly(self, left, right, top, floor):
        """One tick of a deliberate follow-arc -- a jump toward the leader, or a
        fall onto a surface below -- run through the pet's own physics engine
        with a DEAD landing (no restitution flapping), matching Pet._physics.
        The companion is never user-flung (not grabbable), so there is no
        bouncing toss to model. Settles -> back to ground-following; returns
        whether it settled this tick."""
        self.x, self.y, self.vx, self.vy, settled = physics.advance(
            self.x, self.y, self.vx, self.vy, left, right, top, floor,
            floor_restitution=0.0)
        if settled:
            self._air = False
            self._moving = True             # walk the remaining gap to the leader
        if abs(self.vx) > 0.2:
            self.facing = 1 if self.vx > 0 else -1
        # straight-down descents read as climbing down; real arcs show the leap.
        if not settled:
            self._state = ("climbdown" if abs(self.vx) < 0.5 and self.vy >= 0
                           else "leap")
        self.frame = (self.frame + 1) % 100000
        self.move(int(self.x), int(self.y))
        self.update()
        return settled

    def showEvent(self, e):
        super().showEvent(e)
        _macos_keep_visible(self)      # stop AppKit hiding it on app deactivate

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        C.draw_creature(p, PAD_X * COMPANION_U, PAD_Y * COMPANION_U,
                        COMPANION_U, self._state, self.frame, facing=self.facing,
                        cap=self.hat)
        p.end()


class ZoneOverlay(QWidget):
    """One translucent overlay per monitor, for drawing no-go zones.

    Zones are stored in absolute virtual-desktop pixels. A single window can NOT
    reliably cover the whole virtual desktop: KWin/XWayland (and other WMs) clamp
    a frameless window to ONE monitor, and even then place it below top panels —
    so the old "one union-sized window, local + union.topLeft() = absolute" math
    put every zone on the wrong monitor once a second screen existed. Instead
    _enter_zone_edit spawns one overlay per screen (each un-clampable), and we
    read/write GLOBAL coordinates directly: capture via e.globalPosition() and
    paint via mapToGlobal(0,0) — the window's REAL origin, panel offset and all —
    never an assumed screen.topLeft()."""
    def __init__(self, screen_rect, zones, on_zone, on_done):
        super().__init__(None)
        self._zones = list(zones)          # absolute-coord rects, for display
        self._on_zone = on_zone
        self._on_done = on_done
        self._drag = None                  # (x0,y0,x1,y1) GLOBAL, in-progress
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(screen_rect)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def on_zone(self, rect):
        """Entry point the controller/tests call when a zone is finalized."""
        self._zones.append(rect)
        self._on_zone(rect)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self._finish(); return
        g = e.globalPosition()
        self._drag = (g.x(), g.y(), g.x(), g.y())

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            g = e.globalPosition()
            self._drag = (self._drag[0], self._drag[1], g.x(), g.y())
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return
        x0, y0, x1, y1 = self._drag        # already GLOBAL
        self._drag = None
        rect = roambounds.normalize_rect(x0, y0, x1, y1)
        if rect is not None:
            self.on_zone(rect)             # absolute-coord rect
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._finish()

    def _finish(self):
        cb, self._on_done = self._on_done, None
        self.close()
        if cb is not None:
            cb()

    def closeEvent(self, e):
        if self._on_done is not None:
            cb, self._on_done = self._on_done, None
            cb()
        super().closeEvent(e)

    def paintEvent(self, _e):
        from PyQt6.QtGui import QPainter, QColor
        p = QPainter(self)
        og = self.mapToGlobal(QPoint(0, 0))   # this window's REAL origin
        ox, oy = og.x(), og.y()
        fill = QColor(220, 60, 50, 70)
        edge = QColor(220, 60, 50, 160)
        for z in self._zones:
            p.fillRect(int(z["x"] - ox), int(z["y"] - oy), int(z["w"]), int(z["h"]), fill)
            p.setPen(edge)
            p.drawRect(int(z["x"] - ox), int(z["y"] - oy), int(z["w"]), int(z["h"]))
        if self._drag is not None:
            x0, y0, x1, y1 = self._drag        # global -> local for this window
            p.fillRect(int(min(x0, x1) - ox), int(min(y0, y1) - oy),
                       int(abs(x1 - x0)), int(abs(y1 - y0)), fill)
        p.end()


class Pet(QWidget):
    def __init__(self, session_id="default", host="unknown", claude_pid=0):
        super().__init__()
        # The KWin geom feed and geom.EXCLUDE_CLASSES filter our own windows
        # out by resourceClass "claudlet", which Qt derives from the application
        # name — main() sets it, but a Pet constructed directly (demo/embedding)
        # would otherwise see ITSELF and its companion as perchable windows and
        # perch on / get contained in its own companion (wall-sticking, popping
        # out elsewhere, being masked hidden). Enforce it here.
        app = QApplication.instance()
        if app is not None and "claudlet" not in app.applicationName().lower():
            app.setApplicationName("claudlet")
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
        self._wtitle = "claudlet-" + str(session_id)
        self.setWindowTitle(self._wtitle)
        self.port_file = hostinfo.session_port_file(session_id)

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
        self._roam_area = cfg.get("roam_area")
        self._no_go = cfg.get("no_go") or []
        self._zone_overlays = []             # one open ZoneOverlay per monitor
        self._zone_overlay = None            # back-compat handle (first overlay)
        _pal = os.environ.get("CLAUDLET_PALETTE") or cfg.get("palette", "auto")
        _rng = random.Random()
        self._palette = petconfig.resolve_palette(_pal, _rng.random(), _rng.random())
        self.engine = StateEngine(is_focused=self._is_focused,
                                  tool_states=cfg["tool_states"],
                                  event_states=cfg["event_states"],
                                  raw_events=cfg["raw_events"])
        # language for user-facing strings (speech bubbles, tray, menus)
        self.lang = petconfig.resolve_lang(cfg.get("lang", "auto"))
        C.set_lang(self.lang)
        self.labels = STATE_LABELS[self.lang]
        self.ui = UI[self.lang]
        self.claude_state = "sleeping"       # last state the engine reported
        self.dnd = False                     # do-not-disturb
        self._quit_timer = None              # pending SessionEnd -> quit timer
        self._wins = []                      # last window-geometry poll
        self._contain = None                 # Win we're living inside, or None
        # host-window tracking: hide the pet when its own console/IDE window is
        # minimized or fully covered, and aim click-to-focus at THAT window. The
        # host window is the one whose pid is an ancestor of our Claude process.
        self._ancestor_pids = self._proc_ancestors(claude_pid)
        self._host_wid = None                # internalId of our host window (focus)
        self._companions = []                # agent followers, one per running agent
        self._departing = []                 # finished agents' companions waving goodbye
        self._debug_companions = 0           # test override: force >=N companions
                                             # (right-click menu), atop real agents
        # 소셜: idle+컴패니언일 때 랜덤 합동동작(마주보기/줄서기/탑쌓기/하이파이브)
        self._social_act = None              # 현재 act 이름 or None
        self._social_until = 0.0             # act 종료 시각(monotonic)
        self._social_targets = []            # arrange() 결과(컴패니언 순서)
        self._last_social = 0.0              # 쿨다운 기준
        self._hidden_for_win = False         # hidden because our perch/host went away
        self._masked = False                 # pet clipped to a window's exposed part
        self._last_mask = None               # last applied QRegion (skip redundant sets)

        # movement
        self.mode = "roam"                   # roam | held | thrown
        self.target_x = None
        self.vx = self.vy = 0.0
        self._walk_speed = 2.2               # per-trip roam speed (varied a little)
        self._search_anchor = None           # x the work_search darts stay around
        self.idle_energy = IdleEnergy()
        self._idle_behavior = idle_engine.WALK
        self._behavior_timer = 0             # ticks left before choosing a new behavior
        self._explore_target = None          # (x, y) window point EXPLORE/HOP is walking to

        # transient motion override (jump/wave/... — timed; overrides the render)
        self._motion = None
        self._motion_expiry = None       # monotonic deadline; None = hold
        # float is a MODE, not a render override: suspends gravity so the pet
        # hovers, while its normal animation keeps playing. Cleared by `stop`.
        self._floating = False
        # 쓰다듬기: 버튼 없는 호버 왕복 감지 -> 하트+행복 표정 반응
        self._hover_samples = []         # [(t, cursor_x)] 최근 호버
        self._pet_react_until = 0.0      # 하트 반응 종료 시각(monotonic)
        self._last_pet_fire = None       # 쿨다운 기준
        self.setMouseTracking(True)      # 버튼 없이도 mouseMoveEvent 수신
        # follow mode: walk toward the mouse cursor until toggled off
        self._follow = False
        self._follow_jump = False        # airborne on a follow-aimed jump
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
        # Qt's default "coarse" timer rounds to the OS system-tick boundary
        # (~15.6ms on Windows) for power saving — a 50ms (20fps) request
        # actually fires at ~62.5ms (~16fps) with real jitter, which is very
        # noticeable for an animation loop. PreciseTimer keeps it on-interval.
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(int(1000 / FPS))

        self._geom_kde = None
        self._setup_geom_feed()

        # drop the taskbar/pager entry once the window is mapped (KWin script)
        QTimer.singleShot(400, self._skip_taskbar)

    # ---------- Claude Code hook socket ----------
    def _init_socket(self):
        # Loopback TCP, not AF_UNIX: stock Windows Python builds don't have
        # unix domain sockets at all. Bind port 0 (OS picks a free one) and
        # publish it via the port file so the hook/motion scripts can find us.
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((hostinfo.LOOPBACK, 0))
        self.srv.listen(16)
        self.srv.setblocking(False)
        hostinfo.write_session_port(self.session_id, self.srv.getsockname()[1])
        self.notifier = QSocketNotifier(self.srv.fileno(), QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self._on_conn)

    def _on_conn(self):
        try:
            conn, _ = self.srv.accept()
        except (BlockingIOError, OSError):
            return
        events = []
        ping = False
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
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("cmd") == "ping":
                    ping = True            # liveness probe, not a Claude event
                else:
                    events.append(ev)
            if ping:
                # answer with our banner so the prober can tell a real pet from
                # an unrelated process that inherited a stale port number.
                try:
                    conn.sendall((json.dumps(
                        {"pet": hostinfo.BANNER_MARK, "session": self.session_id}
                    ) + "\n").encode())
                except OSError:
                    pass
        for ev in events:
            self._handle_event(ev)

    def _handle_event(self, ev):
        # A quit command (claudlet-uninstall teardown) is a shutdown request,
        # not a Claude event: shut down cleanly and stop processing.
        if ev.get("cmd") == "quit":
            self._quit()
            return
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
        now = time.monotonic()
        was_idle = self.claude_state in ("idle", "sleeping")
        self.idle_energy.note_event(now)
        if was_idle and ev.get("event") not in ("Stop", "Notification"):
            self.idle_energy.wake(now)   # real activity resumed -> startle
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

    def snapshot(self):
        """Read-only view of what the pet is currently *displaying*.

        This is the pet's stable observation surface: tests assert against
        this dict instead of reaching into private attributes, so an internal
        rename (e.g. ``_render_state`` -> something) ripples into this one
        method rather than across the whole suite. Keys are observable facts —
        logical/painted state, physics mode, active toggles, containment and
        companion counts — not internal physics scratch (vx/vy/timers)."""
        return {
            "state": self.claude_state,                       # engine's logical state
            "render": getattr(self, "_render_state", self.claude_state),  # painted state
            "mode": self.mode,                                # roam | held | thrown
            "facing": self.facing,                            # 1 right, -1 left
            "motion": self._motion,                           # forced motion or None
            "floating": self._floating,
            "petted": time.monotonic() < self._pet_react_until,   # 하트 반응 활성

            "following": self._follow,
            "contained": self._contain.wid if self._contain else None,
            "companions": len(self._companions),
            "social": self._social_act,          # 현재 소셜 act or None

            "departing": len(self._departing),
            "quit_armed": self._quit_timer is not None,       # SessionEnd quit pending
            "palette": self._palette,
            "hidden": self._hidden_for_win,                   # occluded away entirely
            "masked": self._masked,                           # clipped to exposed sliver
            "no_go": len(self._no_go),
        }

    # ---------- main loop ----------
    def _tick(self):
        self.frame += 1
        now = time.monotonic()
        self.claude_state = self.engine.display_state(now)
        self._auto = self.engine.auto_active()   # keep the visor on across states
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
        # in auto mode the "looking things up" states wander (visor on); coding/
        # agent/skill stay put and focus. idle/waiting roam as before.
        roaming = (eff in ("idle", "sleeping") or eff in AUTO_ROAM) \
            and self.mode == "roam" and not self.dnd
        resting = self._idle_behavior in idle_engine.RESTING
        self.idle_energy.update(now, resting=(roaming and resting))

        if self.mode == "held":
            self._render_state = "held"     # dangling from the cursor
        elif self.mode == "thrown":
            self._physics()
        elif motion_active:
            pass                            # transient motion already set the render
        elif floating:
            # 주머니 빼꼼: 제자리에 틈을 내고 고개만 내민다. 중력·로밍 정지,
            # 커서도 따라가지 않는다(follow보다 우선). 표정은 라이브 상태 그대로
            # 두고, paintEvent가 pocket=True로 립/손을 덧그린다.
            self._render_state = eff
        elif following:
            # grounded follow: plan ONE move toward the cursor's place each
            # tick -- walk the current surface, launch an aimed ballistic jump
            # (mode "thrown" flies it; _physics resolves the landing), enter
            # the window under the cursor, strain when it's unreachably above,
            # climb down when it's below. The decision lives in the pure
            # core/follow_nav planner; this block only applies intents.
            left, right, _t, floor = self._bounds()
            if self.y < floor - 2:
                # surface dropped away (window closed/moved, or we stepped off
                # a ledge / dropped into an entered window) -> fall to it
                # instead of snapping/teleporting. It's a follow-motivated
                # descent, so fly it like an aimed jump: "jump" pose, dead
                # landing (no tumbling, no restitution flapping).
                self.vx = 0.0
                self.vy = 0.0
                self.mode = "thrown"
                self._follow_jump = True
                self.target_x = None
            else:
                # NOTE: do NOT snap y to floor before planning -- climbdown
                # escapes its surface by stepping the feet just past the
                # support tolerance, and a pre-plan snap would cancel that
                # step every tick (an infinite 6px trembling loop). Standing
                # intents snap below instead.
                curx, cury = self._cursor_pos()
                scr = self.screen_rect
                intent = follow_nav.plan_move(
                    self.x, self.y, self._nav_box(), self._contain,
                    self._wins, scr.left(), scr.right(),
                    self._screen_bottom_at(self.x + self.w / 2.0),
                    curx, cury)
                self._apply_follow_intent(intent, left, right, floor)
        elif self._social_active(now):
            # 소셜 act 중엔 펫이 앵커로 정지(안 그러면 배회 때문에 대형이 흩어짐),
            # 컴패니언 쪽을 바라봄. 하이파이브는 펫도 팔을 든다.
            if self._companions:
                ccx = sum(c.x + c.w / 2.0 for c in self._companions) / len(self._companions)
                self.facing = 1 if ccx >= self.x + self.w / 2.0 else -1
            self._render_state = "wave" if self._social_act == "highfive" else eff
        elif roaming:
            self._roam()
            # _roam's own push-out only guards its ENTRY into this tick; the
            # walk/explore step it takes afterward can land right back in a
            # no-go zone (the pet then oscillates at the zone edge forever
            # instead of clearing it). Re-apply after it moves so the position
            # actually published this tick is clear, not just the one before.
            left, right, _t, _f = self._bounds()
            self.x = roambounds.push_out_x(self.x, self.w, self.y + FOOT_Y, self._no_go, left, right)
            self.x = min(max(self.x, left), right)   # containment wins over no-go
            self._vacate_if_trapped(_f)
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
                        cand = min(max(self._search_anchor
                                       + random.uniform(-span, span), lft), rgt)
                        if roambounds.blocks_target(cand, self.w, self.y + FOOT_Y, self._no_go):
                            cand = min(max(self._search_anchor, lft), rgt)
                        self.target_x = cand
                    dx = self.target_x - self.x
                    self.facing = 1 if dx > 0 else -1
                    self.x += max(-6, min(6, dx))     # fast step
                else:
                    self._search_anchor = None        # re-anchor next search episode
                self.x = min(max(self.x, lft), rgt)   # stay inside current bounds
                self.x = roambounds.push_out_x(self.x, self.w, self.y + FOOT_Y, self._no_go, lft, rgt)
                self.x = min(max(self.x, lft), rgt)   # containment wins over no-go
                self._vacate_if_trapped(floor)
                self.y = floor
                self._render_state = eff

        # 소셜 act: 만료되면 종료(일반 follow 복귀), 없으면 적격 시 새 act 롤
        if self._social_act is not None and now >= self._social_until:
            self._social_act = None
        elif self._social_act is None:
            self._social_start(now)

        self.move(int(self.x), int(self.y))
        # hide/show with the window we're riding (perched-on / contained-in)
        self._update_visibility()
        self.update()
        self._sync_companion()

    @property
    def _companion(self):
        """First companion or None (accessor for tests/back-compat)."""
        return self._companions[0] if self._companions else None

    def _social_active(self, now):
        return self._social_act is not None and now < self._social_until

    def _social_eligible(self):
        return (self.claude_state in ("idle", "waiting")
                and self.mode == "roam" and not self.dnd
                and len(self._companions) >= 1)

    def _social_start(self, now):
        # 적격이면 확률 롤 -> act 시작(arrange로 컴패니언 목표 배치 계산·저장).
        if not self._social_eligible():
            return
        if not social.should_start(random.random(),
                                   now - self._last_social >= social.COOLDOWN):
            return
        act = social.pick(random.random(), len(self._companions))
        if act is None:
            return
        leader = (self.x, self.y, float(self.w))
        comps = [(c.x, c.y, float(c.w)) for c in self._companions]
        # 탑쌓기 층 간격 = 컴패니언 높이(펫 높이 아님)라야 촘촘히 쌓인다
        ch = float(self._companions[0].h) if self._companions else float(self.h)
        self._social_targets = social.arrange(act, leader, comps, creature_h=ch)
        self._social_act = act
        self._social_until = now + social.DURATION.get(act, 2.0)
        self._last_social = now

    def _drive_social(self):
        # act 동안 각 컴패니언을 arrange 타겟으로 직접 ease(팔로우/물리 개입 차단).
        # x는 항상, y는 stack만(지상 act는 c.y 유지). 도착하면 facing 고정.
        stack = self._social_act == "stack"
        spd = COMPANION_SPEED * (2.5 if stack else 1.0)   # 탑은 층까지 닿게 빠르게
        for c, (tx, ty, facing, pose) in zip(self._companions, self._social_targets):
            c._contain = None
            c._air = False
            c.x += max(-spd, min(spd, tx - c.x))
            if stack:
                c.y += max(-spd, min(spd, ty - c.y))
            if abs(tx - c.x) <= spd:
                c.facing = facing            # 도착: act 방향으로 고정
            elif tx != c.x:
                c.facing = 1 if tx > c.x else -1
            c._state = pose
            c.frame = (c.frame + 1) % 100000
            c.move(int(c.x), int(c.y))
            self._occlude_companion(c)
            if not c.isVisible():
                c.show()
            c.update()

    def _sync_companion(self):
        """Show/hide + drive the agent followers: one companion per running
        agent (capped at COMPANION_MAX), trailing in a duckling chain — #1
        follows the pet, #2 follows #1, and so on."""
        try:
            active = self.engine.agents_active()
        except Exception:
            active = 0
        # the test override forces at least N companions with no real agents.
        n = min(max(active, self._debug_companions), COMPANION_MAX)
        now = time.monotonic()
        while len(self._companions) > max(n, 0):     # an agent finished:
            c = self._companions.pop()               # announce, then vanish
            c._depart_until = now + COMPANION_BYE_DUR
            self._departing.append(c)
        for c in self._departing[:]:                 # goodbye celebrate, then close
            if now >= c._depart_until:
                self._departing.remove(c)
                c.close()
            else:
                c.depart_tick()
        if n <= 0:
            return
        while len(self._companions) < n:             # a new agent started
            c = Companion()
            prev = self._companions[-1] if self._companions else self
            # spawn just BEHIND the leader (opposite the pet's heading), clear of
            # its body, so it doesn't pop in on top of the pet -- then it eases
            # into the chain. GAP is past the leader's edge so the rects never
            # overlap at spawn.
            GAP = 12
            if getattr(self, "facing", 1) >= 0:      # heading right -> trail LEFT
                c.x = float(prev.x) - c.w - GAP
            else:                                    # heading left  -> trail RIGHT
                c.x = float(prev.x) + getattr(prev, "w", self.w) + GAP
            # keep the spawn on-screen (near a wall the offset could land it off
            # the edge, where the throw physics would bounce it oddly).
            c.x = min(max(c.x, float(self.screen_rect.left())),
                      float(self.screen_rect.right() - c.w))
            c.y = float(prev.y)
            self._companions.append(c)

        if self.mode == "held":
            # the pet is lifted: the whole chain scurries to the cursor and
            # dangles UNDER the held pet. A release/throw just drops them back
            # into the follow pipeline (they fall/navigate to where it lands).
            for i, c in enumerate(self._companions):
                c.hover_to(self.x + (self.w - c.w) / 2.0,
                           self.y + self.h + 2 + i * int(c.h * 0.75))
                c._contain = None            # re-navigate from scratch on release
                c._air = False
                c._follow_jump = False
                self._occlude_companion(c)
                if not c.isVisible():
                    c.show()
            return

        # 소셜 act 진행 중: 일반 follow 대신 합동동작 배치로 몰고 복귀.
        if self._social_active(time.monotonic()):
            self._drive_social()
            return

        # Every other mode (roam AND thrown) drives each companion through the
        # SAME pure nav+physics core the pet uses: aim at the LEADER (the pet
        # for #1, the companion ahead for the rest — a duckling chain) and let
        # follow_nav.plan_move + physics.advance walk / jump between windows /
        # drop IN to sit with it / climb down / fall. This is the "share the
        # pet's physics" requirement: a thrown pet is just a moving target the
        # companion chases, not a special fling.
        ratio = COMPANION_U / float(U)
        scr = self.screen_rect
        leader = self
        for c in self._companions:
            box = self._companion_nav_box(c)
            foot = box.foot_y
            lead_foot = FOOT_Y if leader is self else FOOT_Y * ratio
            lead_x = leader.x + leader.w / 2.0
            lead_feet = leader.y + lead_foot
            lead_contain = self._contain if leader is self else leader._contain
            # target point fed to the planner: when the leader is PERCHED (not
            # contained), its feet sit exactly on a window's top edge, which
            # window_at reads as "inside" -- so the companion would try to drop
            # INTO the window instead of perching beside it. Nudge the target
            # just above the edge so it reads as a spot ON the top. When the
            # leader is genuinely contained, keep the true feet (aim inside).
            tgt_feet = (lead_feet if lead_contain is not None
                        else lead_feet - (follow_nav.SURF_TOL + 2))
            ccx = c.x + c.w / 2.0
            if c._air:
                # a deliberate follow-arc mid-flight: same engine as the pet
                # (dead landing), entering the leader's window the moment its
                # feet pierce it, or on landing.
                if c._contain is None:
                    win = follow_nav.midflight_enter(
                        c.x, c.y, box, self._wins, lead_x, tgt_feet)
                    if win is not None:
                        c._contain = win
                left, right, top, floor = self._companion_bounds(c)
                if c._contain is None and c._follow_jump and c.vy < 0:
                    # one-way platforms: an ascending arc sails PAST window tops
                    # (support catches only on the way down), like the pet.
                    floor = follow_nav.floor_feet(
                        self._screen_bottom_at(ccx), box) - foot
                if c.fly(left, right, top, floor) and c._follow_jump:
                    c._follow_jump = False
                    # entering the leader's window is the landing's MEANING
                    # (perch/floor need no action — support already gives them).
                    r = follow_nav.resolve_landing(
                        c.x, c.y, box, self._wins,
                        self._screen_bottom_at(c.x + c.w / 2.0),
                        scr.left(), scr.right(), lead_x, tgt_feet)
                    if r[0] == "enter":
                        c._contain = r[1]
            else:
                left, right, top, floor = self._companion_bounds(c)
                if c.y < floor - 2:
                    # the surface under it dropped away (walked off a ledge, a
                    # ridden window closed/moved, or it must descend to the pet)
                    # -> FALL, flown as a dead-landing follow arc rather than
                    # snapped. (Fixes the missing-fall symptom.)
                    c.vx = 0.0
                    c.vy = 0.0
                    c._air = True
                    c._follow_jump = True
                    c.target_x = None
                else:
                    intent = follow_nav.plan_move(
                        c.x, c.y, box, c._contain, self._wins,
                        scr.left(), scr.right(), self._screen_bottom_at(ccx),
                        lead_x, tgt_feet)
                    self._drive_companion(c, intent, left, right, floor,
                                          lead_feet, foot, lead_contain)
            self._occlude_companion(c)
            if not c.isVisible():
                c.show()
            leader = c

    def _companion_nav_box(self, c):
        """A follow_nav.Box for the companion whose feet lines (screen floor,
        window perch, window interior) coincide with the PET's, despite its
        smaller window. The trick: box.h - foot_y is kept equal to the pet's
        (self.h - FOOT_Y), while foot_y is the companion's TRUE drawn foot
        (FOOT_Y*ratio) so a resolved position lands the DRAWN feet on the
        surface. box.w is the real companion width, for the screen/edge clamps."""
        foot = FOOT_Y * (COMPANION_U / float(U))
        return follow_nav.Box(c.w, (self.h - FOOT_Y) + foot, foot)

    def _companion_bounds(self, c):
        """(left, right, top, floor) for a companion's current context: the
        window interior when contained, else the perch/screen-floor under its
        own column. `floor` is the top-left y at which its DRAWN feet rest on
        that surface — mirrors Pet._bounds for the companion box, so the two
        share one feet line."""
        box = self._companion_nav_box(c)
        foot = box.foot_y
        if c._contain is not None:
            w = c._contain
            if w.w < c.w:                    # window narrower than the companion
                left = right = w.x + (w.w - c.w) / 2.0
            else:
                left = w.x
                right = w.x + w.w - c.w
            top = w.y
            floor = follow_nav.inside_feet(w, box) - foot
            return left, right, top, floor
        scr = self.screen_rect
        left = scr.left()
        right = scr.right() - c.w
        top = scr.top()
        ccx = c.x + c.w / 2.0
        feet = c.y + foot
        sb = self._screen_bottom_at(ccx)
        surface = geom.support_surface_under(ccx, self._wins, sb, feet)
        if surface >= sb:
            floor = follow_nav.floor_feet(sb, box) - foot
        else:
            floor = surface - foot           # perch: drawn feet flush on the top
        return left, right, top, floor

    def _drive_companion(self, c, intent, left, right, floor, lead_feet, foot,
                         lead_contain):
        """Apply one follow_nav intent to a companion (the companion's analogue
        of Pet._apply_follow_intent) and run the give-up teleport. A WALK keeps
        a trailing gap (duckling hysteresis via Companion.advance); every
        surface-changing intent runs immediately, so the companion follows the
        pet INTO a window, DOWN a ledge, or ACROSS to another window. It only
        teleports beside the pet after staying a level apart it can't bridge
        (strained overhead / stuck) for COMPANION_REUNITE_TICKS."""
        rest = self.engine.agent_state()
        kind = intent[0]
        # vertical gap to the leader's feet line = the "can't reach" signal.
        separated = abs(lead_feet - (c.y + foot)) > COMPANION_BLINK_DY
        if self._companion_reunite(c, kind, separated, rest):
            c.frame = (c.frame + 1) % 100000
            c.move(int(c.x), int(c.y))
            c.update()
            return
        if kind == "walk":
            # A walk on the leader's OWN surface is the final approach: keep a
            # trailing duckling gap (Companion.advance's FOLLOW_START/STOP
            # hysteresis). A walk anywhere else is a ROUTING leg (walk to a ledge
            # to leap, or close a gap before a jump across windows) and must
            # arrive EXACTLY, or the gap strands it short of the edge and it
            # never jumps. Same surface = same window (or both on floor/perch)
            # AND at the same feet line.
            same_surface = _same_win(c._contain, lead_contain) and not separated
            if same_surface:
                c.advance(intent[1], floor, rest)        # trailing-gap follow
            else:
                self._companion_route_walk(c, intent[1], left, right, floor)
            return
        if kind == "jump":
            c._contain = None
            c.vx, c.vy = intent[1], intent[2]
            if intent[1]:
                c.facing = 1 if intent[1] > 0 else -1
            c._air = True
            c._follow_jump = True
            c.target_x = None
            c._state = "leap"
        elif kind == "enter":
            c._contain = intent[1]            # interior bounds finish the drop
            c._state = "climbdown"
        elif kind == "climbdown":
            c._contain = None                 # exit/descend out the bottom
            c._state = "climbdown"
            c.y += 6                          # fall guard finishes the descent
        elif kind == "strain":
            c._state = "strain"
            c.y = floor
        else:                                 # arrived
            c._state = rest or "idle"
            c.y = floor
        c.frame = (c.frame + 1) % 100000
        c.move(int(c.x), int(c.y))
        c.update()

    def _companion_reunite(self, c, kind, separated, rest):
        """Give-up teleport: only a companion that STAYS a level apart with no
        route (strained overhead, or arrived-stuck on the wrong level) burns the
        budget; any reachable move resets it. On expiry it blinks beside the pet
        and adopts the pet's window. Returns True if it teleported this tick."""
        if separated and kind in ("strain", "arrived", "walk"):
            c._reunite_ticks += 1
            if c._reunite_ticks >= COMPANION_REUNITE_TICKS:
                c.x = self.x + (self.w - c.w) / 2.0
                c.y = float(self.y)               # land beside the pet, not below
                c._contain = self._contain        # and share its window, if any
                c._air = False
                c._follow_jump = False
                c._reunite_ticks = 0
                c._state = rest or "idle"
                return True
        else:
            c._reunite_ticks = 0
        return False

    def _companion_route_walk(self, c, want_cx, left, right, floor):
        """Walk toward column want_cx and ARRIVE exactly -- a routing leg to a
        ledge or into a jump. No trailing gap (that would strand it short of the
        edge). Speeds up when far, like Companion.advance."""
        cx = c.x + c.w / 2.0
        dx = want_cx - cx
        speed = min(COMPANION_SPEED * (1.0 + abs(dx) / COMPANION_RUN_FACTOR),
                    COMPANION_SPEED * COMPANION_RUN_CAP)
        if abs(dx) <= speed:
            c.x = min(max(want_cx - c.w / 2.0, left), right)
        else:
            c.facing = 1 if dx > 0 else -1
            c.x = min(max(c.x + (speed if dx > 0 else -speed), left), right)
        c._state = "walk"
        c.y = floor
        c.frame = (c.frame + 1) % 100000
        c.move(int(c.x), int(c.y))
        c.update()

    def _occlude_companion(self, c):
        """Clip the companion the way the pet clips itself: when it lives INSIDE
        a window, windows stacked above THAT window (its own, which may differ
        from the pet's) cover it too. On the desktop (or without a geom feed) it
        stays fully visible."""
        if not getattr(self, "_geom_active", False) or c._contain is None:
            c.apply_mask(QRegion(QRect(0, 0, c.w, c.h)))
            return
        cur = next((w for w in self._wins if w.wid == c._contain.wid), None)
        if cur is None:                        # ridden window minimized/closed
            c.apply_mask(QRegion())
            return
        try:
            i = self._wins.index(cur)
        except ValueError:
            i = len(self._wins)
        shown = QRegion(QRect(int(c.x), int(c.y), c.w, c.h))
        for w in self._wins[i + 1:]:
            shown = shown.subtracted(QRegion(QRect(w.x, w.y, w.w, w.h)))
        shown.translate(-int(c.x), -int(c.y))
        c.apply_mask(shown)

    def _roam(self):
        left, right, top, floor = self._bounds()
        # bounds can shift under us (a window we're in/on moved or resized): pull
        # the pet back inside every tick so it never gets stranded through a wall.
        self.x = min(max(self.x, left), right)
        self.x = roambounds.push_out_x(self.x, self.w, self.y + FOOT_Y, self._no_go, left, right)
        self.x = min(max(self.x, left), right)
        # surface under us dropped away (window closed/moved, or we walked off a
        # ledge) -> fall to it instead of snapping/teleporting.
        if self.y < floor - 2:
            self.vx = 0.0
            self.vy = 0.0
            self.mode = "thrown"
            self.target_x = None
            return
        # choose a new idle behavior when the current one's timer elapses
        if self._behavior_timer <= 0:
            on_window = self._contain is not None
            allow_rest = self.claude_state in ("idle", "sleeping")
            self._idle_behavior = idle_engine.pick_behavior(
                self.idle_energy.level(), random,
                on_window=on_window, allow_rest=allow_rest)
            self._behavior_timer = random.randint(60, 200)
            self.target_x = None
            self._explore_target = None
        self._behavior_timer -= 1

        b = self._idle_behavior
        if b in (idle_engine.OBSERVE, idle_engine.TIC,
                 idle_engine.SETTLE, idle_engine.DOZE):
            # resting in place: show the pose, occasional glance while observing
            if b == idle_engine.OBSERVE and random.random() < 0.01:
                self.facing = -self.facing
            self.y = floor
            self._render_state = b
            return

        if b in (idle_engine.EXPLORE, idle_engine.HOP):
            # travel to another window, reusing the whole follow_nav pipeline
            # (walk/jump/enter/climbdown) with a window point standing in for
            # the cursor. No window feed at all -> degrade to a plain walk leg.
            if self._explore_target is None:
                self._explore_target = self._explore_point()
            if self._explore_target is None:
                b = idle_engine.WALK        # no windows -> fall through below
            else:
                tx, ty = self._explore_target
                intent = follow_nav.plan_move(
                    self.x, self.y, self._nav_box(), self._contain,
                    self._wins, self.screen_rect.left(), self.screen_rect.right(),
                    self._screen_bottom_at(self.x + self.w / 2.0), tx, ty)
                self.idle_energy.note_roam(time.monotonic())
                if self._apply_follow_intent(intent, left, right, floor):
                    self._explore_target = None
                    self._behavior_timer = 0     # arrived -> pick next behavior
                return

        # WALK (or EXPLORE/HOP degraded for lack of a window feed): a plain
        # horizontal walk leg on the current surface.
        if self.target_x is None:
            reach = (random.uniform(120, 320) if random.random() < 0.8
                     else random.uniform(320, 900))
            direction = 1 if random.random() < 0.5 else -1
            self.target_x = min(max(self.x + direction * reach, left), right)
            self._walk_speed = random.uniform(1.8, 2.8)
        speed = self._walk_speed
        dx = self.target_x - self.x
        if abs(dx) <= speed:
            self.x = self.target_x
            self.target_x = None
            self._behavior_timer = 0        # arrived -> pick next behavior
            self._render_state = self.claude_state
        else:
            self.facing = 1 if dx > 0 else -1
            self.x += speed * self.facing
            self.idle_energy.note_roam(time.monotonic())
            self._render_state = self._walk_render()
        self.y = floor

    def _walk_render(self):
        """Render state while walking a roam leg: an auto_* variant walks with its
        visor + prop on; plain idle/waiting roaming shows the generic walk."""
        return self.claude_state if self.claude_state in AUTO_ROAM else "walk"

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

    def _aim_point(self):
        """The point the current airborne follow-jump is aimed at. Follow mode
        tracks the LIVE cursor (so a moving cursor steers the arc mid-flight);
        idle exploration aims at the fixed window point it chose. Used by
        _physics to decide mid-flight/landing window entry for BOTH."""
        if self._follow:
            return self._cursor_pos()
        if self._explore_target is not None:
            return self._explore_target
        return self._cursor_pos()

    def _nav_box(self):
        return follow_nav.Box(self.w, self.h, FOOT_Y)

    def _explore_point(self):
        """A window point to go visit while idling, or None if no feed/windows."""
        wins = getattr(self, "_wins", None) or []
        cur = self._contain.wid if self._contain is not None else None
        return idle_engine.pick_explore_point(wins, random, current_wid=cur)

    def _apply_follow_intent(self, intent, left, right, floor):
        """Apply one follow_nav.plan_move intent (walk/jump/enter/strain/
        climbdown/arrived) to the pet's position, mode and render state.
        Shared by grounded follow-the-cursor (the `following` branch of
        `_tick`) and idle window exploration (`_roam`'s EXPLORE/HOP), which
        feeds a window point into the same planner instead of the cursor.
        `left`/`right`/`floor` are the caller's current `_bounds()` (already
        window-interior-aware when contained); the planner's own
        screen_left/right/bottom are computed by the caller and baked into
        `intent`. Returns True once the intent resolves to "arrived" --
        either a walk leg landing on its target this tick, or a plain
        arrived (already there)."""
        kind = intent[0]
        if kind == "walk":
            tx = min(max(intent[1] - self.w / 2.0, left), right)
            self.target_x = tx
            dx = tx - self.x
            speed = 10.0            # constant pace (no far speed-up)
            if abs(dx) <= speed:
                self.x = tx
                self._render_state = self.claude_state  # arrived: normal animation
                self.y = floor
                return True
            self.facing = 1 if dx > 0 else -1
            self.x += speed * self.facing
            self._render_state = "walk"
            self.y = floor
            return False
        if kind == "jump":
            self._contain = None    # jumps always leave the window
            self.vx, self.vy = intent[1], intent[2]
            if intent[1]:
                self.facing = 1 if intent[1] > 0 else -1
            self.mode = "thrown"
            self._follow_jump = True    # _physics resolves the landing
            return False
        if kind == "enter":
            self._contain = intent[1]   # fall guard / contained
            self._render_state = "climbdown"   # bounds finish the move
            return False
        if kind == "strain":
            self._render_state = "strain"
            self.y = floor
            return False
        if kind == "climbdown":
            self._render_state = "climbdown"
            self._contain = None    # contained: exit out the bottom
            self.y += 6             # fall guard finishes the descent
            return False
        # arrived
        self._render_state = self.claude_state
        self.y = floor
        return True

    def _physics(self):
        # a follow-aimed jump/descent may become CONTAINED mid-flight: an arc
        # aimed into the cursor's window converts the moment the feet pierce
        # its body, so the interior floor catches it (walls don't block
        # flight, but nothing else inside would stop the arc).
        if self._follow_jump and self._contain is None:
            curx, cury = self._aim_point()
            win = follow_nav.midflight_enter(
                self.x, self.y, self._nav_box(), self._wins, curx, cury)
            if win is not None:
                self._contain = win
        left, right, top, floor = self._bounds()
        if self._follow_jump and self._contain is None and self.vy < 0:
            # one-way platforms: an ascending follow-jump sails PAST window
            # tops (no lip-catch chopping the arc into a dead stop at the
            # edge); support only catches on the way down.
            floor = self._screen_bottom_at(self.x + self.w / 2.0) - self.h
        # deliberate follow moves land DEAD (no restitution flapping); only
        # user flings keep the bounce.
        rest = 0.0 if self._follow_jump else physics.FLOOR_RESTITUTION
        self.x, self.y, self.vx, self.vy, settled = physics.advance(
            self.x, self.y, self.vx, self.vy, left, right, top, floor,
            floor_restitution=rest)
        if settled:
            self.mode = "roam"
            self._render_state = self.claude_state
            if self._follow_jump:
                self._follow_jump = False
                if self._follow or self._explore_target is not None:
                    curx, cury = self._aim_point()
                    # skid-snap: discrete flight steps land up to ~2 ticks
                    # past the aim; walking the overshoot back flickered
                    # land->walk->stand after every hop. Landed near the
                    # aim column -> settle ON it.
                    want = min(max(curx - self.w / 2.0, left), right)
                    if abs(want - self.x) <= 30:
                        self.x = want
                    # a follow-aimed jump just landed: entering the window the
                    # aim point is in is the landing's MEANING (perch/floor need
                    # no action -- support already provides them). Applies to
                    # both cursor-follow and idle window-exploration jumps.
                    scr = self.screen_rect
                    r = follow_nav.resolve_landing(
                        self.x, self.y, self._nav_box(), self._wins,
                        self._screen_bottom_at(self.x + self.w / 2.0),
                        scr.left(), scr.right(), curx, cury)
                    if r[0] == "enter":
                        self._contain = r[1]
        elif self._follow_jump and (self.x <= left or self.x >= right):
            # an aim clipped by the screen wall: don't ping-pong off it --
            # drop straight down from the wall and replan from the ground.
            self.vx = 0.0
            self._render_state = "climbdown" if self.vy >= 0 else "leap"
        elif self._follow_jump:
            # straight-down follow descents READ as climbing down; real arcs
            # show the STEADY leap pose -- the in-place "jump" motion bobs on
            # its own and fights the ballistic movement (reads as stutter).
            # Never the tumbling "falling".
            self._render_state = ("climbdown"
                                  if abs(self.vx) < 0.5 and self.vy >= 0
                                  else "leap")
        else:
            self._render_state = "falling"   # user flings tumble

    def _setup_geom_feed(self):
        """Feed self._wins with other windows' geometry so the pet can perch on
        and be contained by them. KDE: register a D-Bus service and start a
        persistent KWin script that pushes on change. Windows: no equivalent
        push API, so poll Win32's window list on a timer instead. macOS: same
        polled shape via Quartz (SPECULATIVE, unverified on real hardware —
        see geom/macos.py). Either way, any failure -> feature just off
        (self._wins stays empty, pre-perch behaviour). self._geom_active is
        the generic (backend-agnostic) flag; self._dbus_name stays
        KDE-specific, used only by the KDE code paths."""
        self._geom_active = False
        if os.name == "nt":
            self._setup_geom_feed_win32()
            return
        if sys.platform == "darwin":
            self._setup_geom_feed_macos()
            return
        from claudlet.platform.geom import kde
        self._dbus_name = None
        if not kde.available():              # not KDE / no reachable KWin scripting
            return
        # kde.start registers the shared D-Bus object and loads the geometry
        # script; the pushed dumps land in self._on_geom. The cursor feed below
        # reuses the same D-Bus service (self._dbus_name) and object (its
        # `cursor` slot -> self._on_cursor), so thread both callbacks through.
        self._geom_kde = kde.start(self._on_geom, self.session_id, self._on_cursor)
        if self._geom_kde is None:
            return
        self._dbus_name = self._geom_kde.dbus_name
        self._geom_active = True

    def _setup_geom_feed_win32(self):
        try:
            from claudlet.platform.geom import win32
        except Exception:
            return
        self._win32_geom = win32
        self._win32_timer = QTimer(self)
        self._win32_timer.timeout.connect(self._poll_win32_geom)
        self._win32_timer.start(220)   # measured ~0.4ms/poll; plenty of headroom
        self._geom_active = True
        self._poll_win32_geom()

    def _poll_win32_geom(self):
        try:
            dump = self._win32_geom.dump(exclude_hwnd=int(self.winId()))
        except Exception:
            return
        self._on_geom(dump)

    def _setup_geom_feed_macos(self):
        """macOS perch/occlusion feed via Quartz window services, polled like
        the Win32 one (no usable push-on-change API there either).

        SPECULATIVE — written without macOS hardware, never executed on a Mac;
        see geom/macos.py's module docstring for the assumptions to verify
        (Screen Recording permission, coordinate space, z-order)."""
        try:
            from claudlet.platform.geom import macos
        except Exception:
            return
        if not macos.available():       # not macOS, or pyobjc missing
            return
        self._windows_macos = macos
        self._macos_timer = QTimer(self)
        self._macos_timer.timeout.connect(self._poll_windows_macos)
        # 220ms copied from the Win32 branch — an arbitrary guess here, pending
        # real profiling on a Mac (CGWindowListCopyWindowInfo is documented as
        # "relatively expensive"; bump this up if it burns CPU).
        self._macos_timer.start(220)
        self._geom_active = True
        self._poll_windows_macos()

    def _poll_windows_macos(self):
        # exclude by pid, not window id: Qt's winId() on macOS is an NSView
        # pointer, not a CGWindowID — see geom/macos.py's docstring.
        try:
            # ref = our own window as Qt knows it (logical points). dump() finds
            # that same window in CoreGraphics and self-calibrates the CG->Qt
            # coordinate scale from it, so perch lines up regardless of Retina
            # point-vs-pixel differences. exclude_pid drops our window from the feed.
            dump = self._windows_macos.dump(
                exclude_pid=os.getpid(), ref=(self.w, self.h, self.x, self.y))
        except Exception:
            return
        self._on_geom(dump)
        self._debug_geom_log(dump)

    def _debug_geom_log(self, dump):
        # Opt-in coordinate dump (CLAUDLET_DEBUG_GEOM=1) to diagnose perch/
        # occlusion alignment on untested platforms: prints the parsed window
        # rects alongside the pet's feet and the screen geometry + devicePixelRatio
        # so a Retina/point-vs-pixel or y-offset mismatch is visible. Logs only
        # when the feed changes (anti-spam). Wrapped: debug output must never
        # break the pet.
        if not os.environ.get("CLAUDLET_DEBUG_GEOM"):
            return
        if dump == getattr(self, "_dbg_last", None):
            return
        self._dbg_last = dump
        try:
            scr = self.screen() or QApplication.primaryScreen()
            g = scr.geometry()
            cal = getattr(self._windows_macos, "LAST_CAL", (1.0, 0.0, 0.0))
            sys.stderr.write(
                "[claudlet geom] dpr=%.2f cal_scale=%.3f cal_off=(%.1f,%.1f) "
                "screen=%d,%d,%dx%d pet=(%d,%d) feet_y=%d\n" % (
                    scr.devicePixelRatio(), cal[0], cal[1], cal[2],
                    g.x(), g.y(), g.width(), g.height(),
                    int(self.x), int(self.y), int(self.y) + FOOT_Y))
            for w in self._wins:
                sys.stderr.write("[claudlet geom]   win %s cls=%s  %d,%d %dx%d "
                                 "top=%d pid=%s\n" % (
                                     w.wid, w.title, w.x, w.y, w.w, w.h, w.y, w.pid))
            sys.stderr.flush()
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
        self._cursor_plugin = "claudlet_cursor_" + re.sub(
            r"[^A-Za-z0-9_]", "_", str(self.session_id))
        qdbus = qdbus_bin()
        path = None
        try:
            subprocess.run([qdbus, "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.unloadScript", self._cursor_plugin],
                           timeout=3, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
                path = f.name
            subprocess.check_output(
                [qdbus, "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.loadScript", path, self._cursor_plugin],
                text=True, timeout=3)
            subprocess.run([qdbus, "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.start"], timeout=3)
        except Exception:
            pass
        finally:
            if path:                              # always remove the temp .js
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def _stop_cursor_feed(self):
        plugin = getattr(self, "_cursor_plugin", None)
        if plugin:
            try:
                subprocess.run([qdbus_bin(), "org.kde.KWin", "/Scripting",
                                "org.kde.kwin.Scripting.unloadScript", plugin],
                               timeout=3, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            except Exception:
                pass
            self._cursor_plugin = None
        self._cursor = None                     # drop stale pos -> QCursor fallback

    @staticmethod
    def _proc_ancestors(pid, max_hops=40):
        """Set of pids from `pid` up to the top: via /proc/<pid>/stat on Linux,
        a Toolhelp process snapshot on Windows, or a `ps` snapshot on macOS. The
        terminal/IDE window's owning pid is one of these, so matching it to a
        window pid finds our host window. Empty on pid<=0 (tracking then off)."""
        try:
            cur = int(pid)
        except (TypeError, ValueError):
            return set()
        if os.name == "nt":
            try:
                from claudlet.platform.geom import win32
                return win32.proc_ancestors(cur, max_hops)
            except Exception:
                return set()
        if sys.platform == "darwin":
            try:
                from claudlet.platform.geom import macos
                return macos.proc_ancestors(cur, max_hops)
            except Exception:
                return set()
        acc = set()
        while cur > 1 and cur not in acc and len(acc) < max_hops:
            acc.add(cur)
            try:
                with open("/proc/%d/stat" % cur) as f:
                    data = f.read()
                ppid = int(data[data.rindex(")") + 2:].split()[1])
            except (OSError, ValueError, IndexError):
                break
            cur = ppid
        return acc

    def _update_host_wid(self):
        """Remember this session's host window (matched by pid) for click-to-focus.
        Independent of visibility — focus targets the console/IDE, not the perch."""
        if self._ancestor_pids:
            h = geom.find_host(self._wins, self._ancestor_pids)
            if h is not None:
                self._host_wid = h.wid

    def _update_visibility(self):
        """Clip the pet to the still-exposed part of the window it's RIDING
        (perched on / contained in): fully covered or window gone -> hidden;
        partially covered -> shown only over the uncovered sliver; on the bare
        desktop -> fully visible (a maximized window in front never hides a pet
        wandering the wallpaper). No-op without an active geometry feed."""
        if not getattr(self, "_geom_active", False) or self.mode == "held":
            self._show_full()
            return
        if self._contain is not None:
            cur = next((w for w in self._wins if w.wid == self._contain.wid), None)
            if cur is None:              # contained window minimized/closed
                self._hide_fully()
                return
        else:
            cx = self.x + self.w / 2.0
            feet = self.y + FOOT_Y
            cur = geom.window_under_feet(cx, feet, self._wins)
            if cur is None:              # on the desktop -> always visible
                self._show_full()
                return
        # The pet is occluded only by windows stacked ABOVE the one it rides.
        # (Don't intersect with the ridden window's rect: a PERCHED pet stands on
        # the window's top edge with its body reaching ABOVE the window, so that
        # would wrongly clip the body. A contained pet sits inside the window, so
        # subtracting just the higher windows is right for it too.)
        try:
            i = self._wins.index(cur)
        except ValueError:
            i = len(self._wins)
        shown = QRegion(QRect(int(self.x), int(self.y), self.w, self.h))
        for w in self._wins[i + 1:]:
            shown = shown.subtracted(QRegion(QRect(w.x, w.y, w.w, w.h)))
        shown.translate(-int(self.x), -int(self.y))
        self._apply_mask(shown)

    def _apply_mask(self, region):
        # Mask-only visibility: we never hide()/show() the window, because show()
        # re-adds it to the taskbar (undoing _skip_taskbar) and races cause flicker.
        if region == QRegion(QRect(0, 0, self.w, self.h)):
            self._show_full()            # fully exposed -> drop any clip
            return
        self._hidden_for_win = region.isEmpty()
        if self._hidden_for_win:
            # setMask(<empty>) is treated as "no mask" (shows everything!), so to
            # hide fully we mask to a 1px region OUTSIDE the widget instead.
            region = QRegion(QRect(-1, -1, 1, 1))
        if not self._masked or region != self._last_mask:
            self.setMask(region)
            self._masked = True
            self._last_mask = region

    def _hide_fully(self):
        self._apply_mask(QRegion())      # empty mask -> invisible, still mapped

    def _show_full(self):
        if self._masked:
            self.clearMask()
            self._masked = False
            self._last_mask = None
        self._hidden_for_win = False

    def _on_geom(self, dump):
        if dump == getattr(self, "_last_dump", None):
            return                       # coalesce identical pushes (cheap anti-spam)
        self._last_dump = dump
        self._wins = geom.parse_dump(dump)
        self._update_host_wid()
        if self._contain is not None:
            prev = self._contain
            cur = next((w for w in self._wins if w.wid == prev.wid), None)
            if cur is not None:
                # the window we live in moved -> ride along with it so we don't get
                # left behind outside its edges.
                dx, dy = cur.x - prev.x, cur.y - prev.y
                if dx or dy:
                    self.x += dx
                    self.y += dy
                    if self.target_x is not None:
                        self.target_x += dx
                    self.move(int(self.x), int(self.y))
            self._contain = cur

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
        surface = geom.support_surface_under(cx, self._wins, screen_bottom, feet)
        if surface >= screen_bottom:
            floor = surface - self.h        # screen floor: keep window fully on-screen
        else:
            floor = surface - FOOT_Y        # window perch: feet on the top edge
        left, right = roambounds.restrict_span(left, right, self._roam_area, self.w)
        top, floor = roambounds.restrict_floor(top, floor, self._roam_area, self.h)
        return left, right, top, floor

    def _screen_bottom_at(self, cx):
        """Bottom (floor) of the monitor whose column covers cx, so a pet on a
        taller/shorter/offset monitor rests on that monitor's floor rather than a
        single global bottom. Falls back to the union bottom for dead columns."""
        for g in self._screens:
            if g.left() <= cx <= g.right():
                return g.bottom()
        return self.screen_rect.bottom()

    def _vacate_if_trapped(self, floor):
        """No-go backstop: if our feet are STILL inside a zone after the
        horizontal push-out (the whole reachable surface here is forbidden),
        abandon this surface -- leave the window / drop off the perch and fall
        to whatever is below, re-evaluating next tick. On the true screen floor
        there's nowhere lower to go, so leave it (a full-width floor zone is a
        config mistake)."""
        if not self._no_go:
            return
        if not roambounds.blocks_target(self.x, self.w, self.y + FOOT_Y, self._no_go):
            return
        screen_bottom = self._screen_bottom_at(self.x + self.w / 2.0)
        perched = floor < screen_bottom - self.h    # floor is a window top, not the screen floor
        if self._contain is not None or perched:
            self._contain = None
            self.vx = self.vy = 0.0
            # drop below the current surface so support_surface_under (tol 6px)
            # skips it next tick; without this a PERCHED pet re-matches the same
            # window top every tick and oscillates thrown<->roam without falling.
            self.y += 8.0
            self.mode = "thrown"        # physics drops us to the surface below

    def showEvent(self, e):
        super().showEvent(e)
        _macos_keep_visible(self)      # stop AppKit hiding it on app deactivate

    # ---------- painting ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        state = getattr(self, "_render_state", self.claude_state)
        # in an auto mode the visor stays on: worn by the auto_* states,
        # pushed up onto the head for every other state.
        vis = "up" if getattr(self, "_auto", False) and \
            state not in AUTO_STATES else None
        now = time.monotonic()
        petted = now < self._pet_react_until
        pocket = self._floating and self.mode not in ("held", "thrown")
        # facing handled inside draw_creature (body mirrors, text upright)
        C.draw_creature(p, PAD_X * U, PAD_Y * U, U, state, self.frame,
                        facing=self.facing, visor=vis, energy=self.idle_energy.value,
                        palette=self._palette, happy=petted, pocket=pocket)
        if petted:
            self._draw_hearts(p, 1.0 - (self._pet_react_until - now) / PET_REACT_SEC)
        p.end()

    def _draw_hearts(self, p, age):
        # 쓰다듬기 반응 하트. 창이 캐릭터에 꽉 차서 위 여백이 거의 없으므로 머리 양옆
        # (창 안)에서 살짝 떠오르며 페이드. age 0..1. 크고 뚜렷하게.
        p.setPen(Qt.PenStyle.NoPen)
        cx = self.w // 2
        for i, off in enumerate((-4.5 * U, 4.5 * U, 0)):
            phase = age + i * 0.18
            if phase >= 1.0:
                continue
            rise = phase * 3.5 * U
            alpha = max(0, int(235 * (1.0 - phase)))
            col = QColor(233, 70, 96, alpha)
            s = (1.6 if i < 2 else 1.1) * U          # 옆 큰 하트 2 + 중앙 작은 것
            hx = cx + off
            hy = (PAD_Y + 3) * U - rise              # 머리 옆 높이에서 시작
            self._heart(p, hx, hy, s, col)

    @staticmethod
    def _heart(p, cx, cy, s, col):
        # 픽셀 하트: 위 두 돌기(원) + 아래 삼각형
        p.setBrush(col)
        r = s * 0.55
        p.drawEllipse(QRectF(cx - r, cy - r, r * 1.15, r * 1.15))
        p.drawEllipse(QRectF(cx + r * 0.0 - 0.15 * s, cy - r, r * 1.15, r * 1.15))
        path = QPainterPath()
        path.moveTo(cx - r, cy - r * 0.15)
        path.lineTo(cx + r, cy - r * 0.15)
        path.lineTo(cx, cy + s * 0.7)
        path.closeSubpath()
        p.fillPath(path, col)

    # ---------- interaction ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_global = e.globalPosition().toPoint()
            # Anchor the drag to our OWN tracked position, not frameGeometry():
            # on XWayland a frameless window's frameGeometry can report ~(0,0)
            # instead of where we moved it, which flung the pet to the top-left
            # corner on grab. self.x/self.y is the source of truth move() uses.
            self._press_winpos = QPoint(int(self.x), int(self.y))
            self._moved = False
            self._vel_samples = [(time.monotonic(), self._press_global)]
            self.mode = "held"
            self._follow_jump = False      # a grab cancels any follow-jump
        elif e.button() == Qt.MouseButton.RightButton:
            self._menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.NoButton:
            self._maybe_pet(e.position().x(), time.monotonic())   # 호버 = 쓰다듬기
            return
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
            win = geom.window_at(cxp, cyp, self._wins)
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

    def _maybe_pet(self, x, now):
        # 버튼 없는 호버 x를 링버퍼에 넣고, 왕복이면 하트 반응 발동. 어느 상태에서든
        # (자는 중이어도 쓰다듬으면 하트 뜨며 방긋 — happy 눈이 감은 눈을 덮음).
        # 시간창(STROKE_WINDOW)이 실제 필터. 호버 이벤트가 초당 수백 개 쏟아져서
        # 샘플수로 자르면 시간창이 너무 짧아져(반전 3회가 안 채워짐) -> 넉넉히 둔다.
        self._hover_samples = [(t, hx) for (t, hx) in self._hover_samples
                               if now - t <= petting.STROKE_WINDOW][-400:]
        self._hover_samples.append((now, float(x)))
        fired = petting.detect_stroke(self._hover_samples, now,
                                      last_fire=self._last_pet_fire)
        if fired:
            self._last_pet_fire = now
            self._pet_react_until = now + PET_REACT_SEC
            self._hover_samples = []          # 소진(연속 오발동 방지)

    def _menu(self, gpos):
        m = QMenu()
        a_follow = QAction(self.ui["follow"], m, checkable=True)
        a_follow.setChecked(self._follow)
        m.addAction(a_follow)

        sub = m.addMenu(self.ui["motions"])
        motion_acts = {}
        for name, dur, label in MOTION_MENU:
            act = QAction(label[self.lang], sub)
            sub.addAction(act)
            motion_acts[act] = (name, dur)

        a_float = QAction(self.ui["float"], m, checkable=True)
        a_float.setChecked(self._floating)
        m.addAction(a_float)

        a_dnd = QAction(self.ui["quiet"], m, checkable=True)
        a_dnd.setChecked(self.dnd)
        m.addAction(a_dnd)
        a_release = None
        if self._contain is not None:
            a_release = QAction(self.ui["release"], m)
            m.addAction(a_release)
        m.addSeparator()
        a_comp_add = QAction(self.ui["comp_add"], m)
        m.addAction(a_comp_add)
        a_comp_del = None
        if self._debug_companions > 0:
            a_comp_del = QAction(self.ui["comp_del"], m)
            m.addAction(a_comp_del)
        m.addSeparator()
        a_zone_edit = QAction(self.ui["zone_edit"], m)
        m.addAction(a_zone_edit)
        a_zone_clear = None
        if self._no_go:
            a_zone_clear = QAction(self.ui["zone_clear"], m)
            m.addAction(a_zone_clear)
        m.addSeparator()
        a_quit = QAction(self.ui["quit"], m)
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
        elif chosen == a_comp_add:
            self._spawn_test_companion(+1)
        elif a_comp_del is not None and chosen == a_comp_del:
            self._spawn_test_companion(-1)
        elif chosen == a_zone_edit:
            self._enter_zone_edit()
        elif a_zone_clear is not None and chosen == a_zone_clear:
            self._clear_zones()
        elif chosen == a_quit:
            self._quit()

    # ---------- shared menu actions (used by both the pet and the tray) ----------
    def _toggle_follow(self):
        self._follow_jump = False
        self._follow = not self._follow
        if self._follow:
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

    def _spawn_test_companion(self, delta):
        """Test helper (right-click menu): make a companion appear/disappear
        WITHOUT a real subagent by nudging the count override, applied at once.
        Clamped to [0, COMPANION_MAX]; real running agents still add on top."""
        self._debug_companions = max(0, min(self._debug_companions + delta,
                                            COMPANION_MAX))
        self._sync_companion()

    def _play_motion(self, name, dur=2.5):
        # reuse the same path as a socket motion command (menu is in-process)
        self._handle_event({"cmd": "motion", "motion": name, "dur": dur})

    def _enter_zone_edit(self):
        if self._zone_overlays:
            return
        def _add(rect):
            self._no_go.append(rect)
        def _done():
            # finishing on ANY monitor's overlay tears down the whole session;
            # null each _on_done first so their closeEvent doesn't re-enter here.
            overlays, self._zone_overlays = self._zone_overlays, []
            self._zone_overlay = None
            for ov in overlays:
                ov._on_done = None
                ov.close()
        # One un-clampable overlay per monitor (a single union-sized window gets
        # clamped to one screen by the WM, landing zones on the wrong monitor).
        self._zone_overlays = [ZoneOverlay(g, self._no_go, _add, _done)
                               for g in self._screens]
        self._zone_overlay = self._zone_overlays[0]   # back-compat handle
        for ov in self._zone_overlays:
            ov.show()
            ov.raise_()
            ov.activateWindow()

    def _clear_zones(self):
        self._no_go = []
        for ov in self._zone_overlays:
            ov._zones = []
            ov.update()

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
        # macOS: DON'T give the native NSStatusItem a context menu. On macOS 26+
        # the scene-backed status item re-runs its scene setup on every Space
        # (desktop) switch, which calls popUpStatusItemMenu -> begins a menu
        # tracking session with no mouse event behind it. Qt's cocoa menu-tracking
        # observer then reads -[NSEvent clickCount] on that non-mouse event, which
        # raises NSInternalInconsistencyException; the exception crosses the C++
        # boundary uncaught and aborts the process. The identical menu is always
        # available by right-clicking the pet itself (see _menu), which opens from
        # a real mouse event and is unaffected. The persistent _act_* checkboxes
        # (used only to mirror state INTO the tray menu) stay None here; _menu
        # reads live state each time it opens, and _toggle_* guard on them.
        if sys.platform != "darwin":
            m = QMenu()
            self._act_follow = QAction(self.ui["follow"], m, checkable=True)
            m.addAction(self._act_follow)
            self._act_follow.triggered.connect(self._toggle_follow)

            sub = m.addMenu(self.ui["motions"])
            for name, dur, label in MOTION_MENU:
                act = QAction(label[self.lang], sub)
                sub.addAction(act)
                act.triggered.connect(
                    lambda _checked=False, n=name, d=dur: self._play_motion(n, d))

            self._act_float = QAction(self.ui["float"], m, checkable=True)
            m.addAction(self._act_float)
            self._act_float.triggered.connect(self._toggle_float)

            self._act_dnd = QAction(self.ui["quiet"], m, checkable=True)
            m.addAction(self._act_dnd)
            act_quit = QAction(self.ui["quit"], m)
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
        tray.setToolTip("claudlet — " + self.labels.get(st, st))

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
        plugin = "claudlet_act_" + re.sub(r"[^A-Za-z0-9_]", "_", str(self.session_id))
        qdbus = qdbus_bin()
        path = None
        try:
            subprocess.run([qdbus, "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.unloadScript", plugin],
                           timeout=3, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
                path = f.name
            subprocess.check_output(
                [qdbus, "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.loadScript", path, plugin],
                text=True, timeout=3)
            subprocess.run([qdbus, "org.kde.KWin", "/Scripting",
                            "org.kde.kwin.Scripting.start"], timeout=3)
            self._activate_plugin = plugin
        except Exception:
            pass
        finally:
            if path:                              # always remove the temp .js
                try:
                    os.unlink(path)
                except OSError:
                    pass

    # ---------- bring the Claude Code terminal forward ----------
    def _konsole_focus_tab(self):
        """Best-effort: select THIS session's Konsole tab over Konsole's D-Bus.
        Konsole shares one process across all tabs/windows, so pid->window (the
        KWin raise) can't distinguish two sessions in two tabs; the session's
        shell pid, which is in our ancestor set, can. No-op off KDE/Konsole."""
        if not sys.platform.startswith("linux") or not self._ancestor_pids:
            return

        qdbus = qdbus_bin()

        def run(*args):
            return subprocess.check_output(
                [qdbus, *args], text=True, timeout=3,
                stderr=subprocess.DEVNULL)

        try:
            konsole.focus(self._ancestor_pids, run)
        except Exception:
            pass

    def _activate_claude(self):
        if sys.platform == "darwin":
            self._activate_claude_macos()
            return
        if os.name == "nt":
            self._activate_claude_windows()
            return
        if not sys.platform.startswith("linux"):
            return                           # unknown platform: not implemented (no-op)
        # Linux/KDE: Konsole runs every tab/window in ONE process, so two Claude
        # sessions living in two tabs share the window pid — raising the window
        # (below) can't pick the right TAB. Select our tab over Konsole's D-Bus
        # first (best-effort); then raise the window so it comes forward.
        self._konsole_focus_tab()
        # prefer THIS session's own host window (matched by pid -> internalId) so
        # with two consoles the click focuses the right one; fall back to the
        # first window of the host class when we haven't identified it.
        classes = self.host_classes or ["konsole"]
        want = "[" + ",".join('"%s"' % c for c in classes) + "]"
        hostid = self._host_wid or ""
        self._run_kwin_script(
            'var HOSTID = "' + hostid + '";'
            'var want = ' + want + ';'
            'var cs = (typeof workspace.windowList === "function") '
            '? workspace.windowList() : workspace.clientList();'
            'var target = null;'
            'if (HOSTID) {'
            '  for (var i = 0; i < cs.length; i++) {'
            '    if (("" + cs[i].internalId) === HOSTID) { target = cs[i]; break; }'
            '  }'
            '}'
            'if (!target) {'
            '  for (var i = 0; i < cs.length && !target; i++) {'
            '    var rc = (cs[i].resourceClass || "").toString().toLowerCase();'
            '    for (var j = 0; j < want.length; j++) {'
            '      if (rc.indexOf(want[j]) >= 0) { target = cs[i]; break; }'
            '    }'
            '  }'
            '}'
            'if (target) {'
            '  try { workspace.activeWindow = target; } catch (e) { workspace.activeClient = target; }'
            '  target.minimized = false;'
            '}'
        )

    def _activate_claude_windows(self):
        """Bring this session's host terminal/IDE window to the foreground
        (Win32), restoring it if minimized.

        Uses a MINIMIZED-INCLUSIVE lookup (find_focus_target) rather than the
        perch feed's `_host_wid`: the perch/occlusion feed drops minimized
        windows (you can't perch on them), so relying on it left a minimized
        host un-findable — click focused nothing. find_focus_target enumerates
        minimized windows too and picks by pid-ancestry (skipping shell chrome
        like explorer's File Explorer) then native-terminal class; activate_hwnd
        then SW_RESTOREs it. `win_classes` returns [] for Electron IDEs (their
        class is shared with every Electron app), so those fall through to the
        pid match or safely no-op rather than raising the wrong window."""
        geom = getattr(self, "_win32_geom", None)
        if geom is None:
            return
        target = geom.find_focus_target(self._ancestor_pids,
                                        hostinfo.win_classes(self.host))
        if target:
            geom.activate_hwnd(target)

    def _activate_claude_macos(self):
        """Bring the host terminal/IDE app to the front via AppleScript.
        Best-effort; UNTESTED on macOS. Can't target a specific window (no KWin),
        so it activates the whole app."""
        app = hostinfo.mac_app(self.host)
        if not app or not shutil.which("osascript"):
            return
        # hostinfo.MAC_APP values are a fixed, quote-free dict today, but this
        # is spliced into AppleScript source — escape defensively so a future
        # entry containing `"` or `\` can't break/inject the script.
        app = app.replace("\\", "\\\\").replace('"', '\\"')
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "%s" to activate' % app],
                timeout=3, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        except Exception:
            pass

    # ---------- drop our own taskbar/pager entry (KDE Wayland) ----------
    def _skip_taskbar(self):
        # EWMH via wmctrl is the reliable path on X11/XWayland. (KWin scripting
        # sets skipPager/skipSwitcher but NOT skipTaskbar — verified 2026-07-09.)
        # Match the window by its exact title so we don't hit other windows
        # (e.g. an editor whose title merely contains "claudlet").
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
            '  if (cap.indexOf("claudlet") >= 0 || rc.indexOf("claudlet") >= 0) {'
            '    c.skipTaskbar = true; c.skipPager = true; c.skipSwitcher = true;'
            '    c.onAllDesktops = true;'
            '  }'
            '}'
        )

    def _cleanup(self):
        # A visible QSystemTrayIcon can keep the app (and the process) alive
        # past QApplication.quit() on Windows; hiding it is a no-op elsewhere.
        if getattr(self, "tray", None) is not None:
            self.tray.hide()
        for c in getattr(self, "_companions", []) + getattr(self, "_departing", []):
            c.close()
        self._companions = []
        self._departing = []
        for ov in getattr(self, "_zone_overlays", []):
            ov._on_done = None
            ov.close()
        self._zone_overlays = []
        self._zone_overlay = None
        self._stop_cursor_feed()
        for plugin in (getattr(self, "_activate_plugin", None),):
            if plugin:
                try:
                    subprocess.run([qdbus_bin(), "org.kde.KWin", "/Scripting",
                                    "org.kde.kwin.Scripting.unloadScript", plugin],
                                   timeout=3, stderr=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL)
                except Exception:
                    pass
        geom_kde = getattr(self, "_geom_kde", None)
        if geom_kde is not None:
            from claudlet.platform.geom import kde
            kde.stop(geom_kde)
        try:
            os.unlink(self.port_file)
        except OSError:
            pass


def _pid_alive(pid):
    """Is process `pid` still running? Cross-OS; used by the orphan reaper.

    NOT os.kill(pid, 0) on Windows: there signal 0 == CTRL_C_EVENT, so CPython
    routes it to GenerateConsoleCtrlEvent and it would fire Ctrl+C at the target
    instead of probing it. Use a process snapshot on Windows and the real
    signal-0 probe only on POSIX (Linux/macOS). Unknown -> assume alive, so the
    reaper never kills the pet on a merely-undetectable parent."""
    if os.name == "nt":
        try:
            from claudlet.platform.geom import win32
            table = win32.proc_table()
            return (not table) or (pid in table)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True                       # EPERM etc. -> alive but not ours


def _lock_exclusive_nonblocking(fd):
    """Cross-platform advisory lock: fcntl.flock on POSIX, msvcrt on Windows."""
    if os.name == "posix":
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        import msvcrt
        os.write(fd, b"\0")           # msvcrt.locking needs a byte to lock
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


def main():
    import argparse
    import signal
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="default")
    ap.add_argument("--host", default="unknown")
    ap.add_argument("--claude-pid", type=int, default=0)
    args, _ = ap.parse_known_args()

    # One pet per session: hold an exclusive lock. If another pet already holds
    # it (e.g. two SessionStart hooks racing), exit BEFORE touching the shared
    # socket — otherwise the second pet would overwrite the first's port file.
    lock_fd = os.open(hostinfo.session_port_file(args.session) + ".lock",
                      os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _lock_exclusive_nonblocking(lock_fd)
    except OSError:
        os.close(lock_fd)
        return                                # another pet for this session lives

    app = QApplication(sys.argv[:1])          # keep our flags away from Qt
    app.setApplicationName("claudlet")
    app.setDesktopFileName("claudlet")
    app.setQuitOnLastWindowClosed(False)
    if sys.platform == "darwin":
        # No Dock icon / Cmd-Tab entry: on macOS that's an activation-policy
        # thing, not a window-flag thing, so Qt.Tool can't do it. Do it here,
        # after NSApplication exists but before any window shows. See
        # geom/macos.py's set_accessory_policy.
        try:
            from claudlet.platform.geom import macos
            macos.set_accessory_policy()
        except Exception:
            pass                              # never block startup over cosmetics
    pet = Pet(session_id=args.session, host=args.host, claude_pid=args.claude_pid)
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
            if not _pid_alive(args.claude_pid):
                app.quit()
        _reaper = QTimer()
        _reaper.timeout.connect(_check_parent)
        _reaper.start(3000)
    pet.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
