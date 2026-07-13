"""claudlet original creature renderer.

Pure-code pixel-art creature (no image assets), animated by state.
Original artwork (CC0). Style: horizontal orange pixel loaf with 4 stubby legs,
dash eyes, and a two-notch "crown" on top echoing the Claude Code block logo.

Public API:
    draw_creature(painter, ox, oy, u, state, frame, facing=1)
        painter : QPainter
        ox, oy  : top-left of the creature's bounding box (device px)
        u       : pixel unit size (each art "pixel" is u x u device px)
        state   : one of STATES
        frame   : monotonic animation tick (int, ~20fps)
        facing  : +1 faces right, -1 faces left
    GRID_W, GRID_H : bounding size in art pixels (multiply by u for device px)
"""
import math
from PyQt6.QtGui import QColor
from PyQt6.QtCore import QRectF

# autonomous (auto/bypass mode) variants: the pet wears a visor and wanders while
# it works, each work type keeping its own prop. `autopilot` is the generic cruise.
AUTO_VARIANTS = ("auto_computer", "auto_search", "auto_web",
                 "auto_agent", "auto_skill")
# states that animate with a walking leg cycle: plain walk, the generic autopilot
# stroll, and the auto variants that actually roam (web/search). coding/agent/skill
# variants stay put, so their legs don't do a walk cycle.
_WALKERS = ("walk", "autopilot", "auto_web", "auto_search")

STATES = ("idle", "walk", "work_computer", "work_search", "work_web",
          "work_agent", "work_skill", "autopilot") + AUTO_VARIANTS + (
          "thinking", "attention", "asking",
          "error", "celebrate", "sleeping", "held", "falling",
          "jump", "wave", "sing", "juggle", "float", "climbdown", "strain")

# prop drawn beside each auto_* variant (auto_skill uses a visor glint instead)
_AUTO_PROP = {"auto_computer": "window", "auto_search": "magnify",
              "auto_web": "phone", "auto_agent": "clones_v"}

# short spoken line per communicative state (typed out in a bubble), per language
SPEECH = {                      # Korean (default; also drives the mockup sheet)
    "thinking": "고민중…",
    "attention": "이거 맞아?",
    "asking": "응?",
    "celebrate": "다 됐다!",
    "error": "으악!",
}
SPEECH_EN = {
    "thinking": "hmm…",
    "attention": "this ok?",
    "asking": "yeah?",
    "celebrate": "done!",
    "error": "argh!",
}
LANG = "ko"                     # set by pet.py via set_lang(); "ko" | "en"


def set_lang(lang):
    global LANG
    LANG = "en" if lang == "en" else "ko"


def _speech(state):
    return (SPEECH_EN if LANG == "en" else SPEECH).get(state, "")

ORANGE   = QColor("#D97757")
ORANGE_L = QColor("#ECA184")   # top bevel / highlight
ORANGE_D = QColor("#B0532F")   # legs / bottom shade
EYE      = QColor("#2A2018")
BULB     = QColor("#FFD86B")
BULB_L   = QColor("#FFF0B8")
WHITE    = QColor("#FFFFFF")
BANG     = QColor("#D0402E")
ZTXT     = QColor("#EFE7DF")
# VR-headset visor (auto mode): silver housing + dark glossy screen
VISOR      = QColor("#C2C8D2")   # silver housing
VISOR_HI   = QColor("#E9EDF3")   # top highlight
VISOR_D    = QColor("#8A90A0")   # bottom shade
VISOR_GLASS = QColor("#1E2230")  # dark screen inset
# hats worn by agent companions (marks them as sidekicks; picked at random)
CAP      = QColor("#F4C430")   # kindergarten yellow
CAP_HI   = QColor("#FFE07A")   # top highlight
CAP_D    = QColor("#C9960F")   # brim / shade
HARD     = QColor("#FF8C1A")   # construction hard hat
HARD_HI  = QColor("#FFD9A8")
BERET    = QColor("#B03A48")   # artist beret (wine red)
BERET_D  = QColor("#7E2833")
INK      = QColor("#26232B")   # top hat
INK_BAND = QColor("#C0392B")
PROP     = QColor("#3E7BD6")   # propeller beanie base (blue)
PROP_BLADE = QColor("#E14848")
BEANIE   = QColor("#2FA893")   # knitted beanie (teal)
BEANIE_D = QColor("#1F7A6A")
# every kind a companion can be assigned (random per companion)
HAT_KINDS = ("cap", "hardhat", "beret", "tophat", "propeller", "beanie")

GRID_W, GRID_H = 22, 17   # art-pixel bounding box (incl. room above for props/bounce)


def _sin(frame, period, amp, phase=0.0):
    return math.sin((frame / period + phase) * 2 * math.pi) * amp


def draw_creature(p, ox, oy, u, state, frame, facing=1, visor=None, cap=None):
    """Draw the creature. All coordinates are in art pixels * u.

    visor="up" pushes a VR-headset up onto the head (auto mode while not actively
    "looking"); the auto_* states draw the headset worn over the eyes themselves.
    """
    p.setPen(p.pen())  # no-op keep
    from PyQt6.QtCore import Qt
    p.setPen(Qt.PenStyle.NoPen)

    # ---- per-state rig parameters ----
    bob = 0.0          # whole-body vertical offset (art px)
    sx, sy = 1.0, 1.0  # squash/stretch
    tilt = 0.0         # degrees
    legphase = 0.0     # 0..1 walk cycle
    eyes = "open"
    prop = None
    front_tap = 0.0    # front legs tapping (working)
    baseline_lift = 0.0

    if state == "idle":
        bob = _sin(frame, 34, 0.5)
        if frame % 90 < 4:
            eyes = "blink"
    elif state == "walk":
        bob = abs(_sin(frame, 12, 0.9))
        legphase = (frame / 12.0) % 1.0
        tilt = _sin(frame, 12, 2.0)
    elif state == "work_computer":
        bob = _sin(frame, 30, 0.3)                # gentle head bob while typing
        eyes = "focus"
        prop = "laptop"
    elif state == "work_search":
        bob = abs(_sin(frame, 6, 0.7))            # busy little bounce
        legphase = (frame / 6.0) % 1.0            # fast legs
        tilt = _sin(frame, 6, 3.5)                # quick side-to-side lean
        eyes = "focus"
        prop = "magnify"
    elif state == "work_web":
        bob = _sin(frame, 40, 0.3)
        eyes = "up"
        prop = "phone"
    elif state == "work_agent":
        bob = _sin(frame, 34, 0.4)
        eyes = "open"
        prop = "clones"
    elif state == "work_skill":
        bob = _sin(frame, 28, 0.5)
        eyes = "happy"
        prop = "hat"
    elif state == "autopilot":
        # cruising on its own (auto / bypass mode) — relaxed and confident:
        # easy stroll, slight forward lean, cool shades, a gear ticking over
        # to signal "running by itself".
        bob = _sin(frame, 20, 0.5)
        legphase = (frame / 16.0) % 1.0
        tilt = 2.0
        eyes = "shades"
        prop = "gear"
    elif state in AUTO_VARIANTS:
        # visor on, wandering while it works: same relaxed stroll as autopilot,
        # but each work type carries its own prop (auto_skill: a red visor glint).
        bob = _sin(frame, 20, 0.5)
        legphase = (frame / 16.0) % 1.0
        tilt = 2.0
        eyes = "shades_glint" if state == "auto_skill" else "shades"
        prop = _AUTO_PROP.get(state)
    elif state == "thinking":
        bob = _sin(frame, 46, 0.35)
        tilt = _sin(frame, 92, 3.0)               # slow head cant, "hmm"
        eyes = "up"
        prop = "speech"
    elif state == "attention":
        t = (frame % 22) / 22.0
        j = max(0.0, math.sin(t * math.pi)) * 3.2
        bob = j
        sx = 1.0 + 0.10 * (j / 3.2)
        sy = 1.0 - 0.12 * (j / 3.2) + 0.12 * (1 - j / 3.2)
        eyes = "wide"
        prop = "speech"
    elif state == "asking":
        # calmly waiting on the user to answer (a question or plan approval):
        # patient bob, slow curious head cant, attentive eyes, "응?" bubble.
        # distinct from `attention` (a jumpy permission alert).
        bob = _sin(frame, 40, 0.4)
        tilt = _sin(frame, 70, 2.5)
        eyes = "wide"
        prop = "speech"
    elif state == "error":
        tilt = -16
        bob = 1.5
        baseline_lift = -1.0
        eyes = "x"
        prop = "speech"
    elif state == "celebrate":
        t = (frame % 18) / 18.0
        j = math.sin(t * math.pi) * 5.5
        bob = -j
        sy = 1.0 + 0.12 * (j / 5.5)
        sx = 1.0 - 0.08 * (j / 5.5)
        legphase = 0.5  # tucked
        eyes = "happy"
        prop = "speech"
    elif state == "sleeping":
        bob = _sin(frame, 50, 0.4)
        eyes = "sleep"
        prop = "zzz"
    elif state == "held":
        # dangling happily from the cursor's grab: hangs, sways, legs dangling
        bob = _sin(frame, 20, 0.6)
        tilt = _sin(frame, 26, 4.0)          # gentle swing
        sx, sy = 0.97, 1.06                  # slightly stretched (hanging)
        legphase = 0.5                       # legs together, dangling
        eyes = "happy"                       # enjoying the ride :)
    elif state == "falling":
        # the physics motion IS the animation — keep the body steady so it reads
        # clean, not jittery: stretched tall ("wheee"), legs tucked, wide eyes.
        bob = _sin(frame, 18, 0.4)
        sx, sy = 0.88, 1.14          # stretched vertical, like a motion streak
        legphase = 0.5               # legs together/tucked (no flailing)
        eyes = "wide"
    elif state == "jump":
        j = abs(_sin(frame, 16, 5.5))            # tall hop
        bob = -j
        sy = 1.0 + 0.14 * (j / 5.5)              # stretch at apex
        sx = 1.0 - 0.10 * (j / 5.5)
        legphase = 0.5
        eyes = "happy"
    elif state == "wave":
        bob = _sin(frame, 30, 0.4)
        tilt = _sin(frame, 20, 4.0)              # rock while waving
        eyes = "happy"
    elif state == "sing":
        bob = _sin(frame, 22, 0.6)
        tilt = _sin(frame, 22, 5.0)              # big sway to the beat
        eyes = "happy"
        prop = "note"
    elif state == "juggle":
        bob = _sin(frame, 18, 0.4)
        eyes = "wide"
        prop = "balls"
    elif state == "float":
        bob = _sin(frame, 60, 1.6)               # slow, wide hover
        tilt = _sin(frame, 120, 3.0)             # lazy drift
        sx, sy = 1.03, 1.03                      # faintly puffed
        legphase = 0.5
        eyes = "open"
    elif state == "climbdown":
        # getting down off a ledge: body leans back toward the ledge above,
        # arms reach up as if still gripping it, legs stretch down feeling
        # for footing below. focused, careful eyes.
        tilt = -11                               # lean back toward the ledge
        sy = 1.06                                # stretched, reaching down
        sx = 0.97
        bob = 0.6
        legphase = 0.5                           # legs lowered, not walking
        eyes = "focus"
    elif state == "strain":
        # the failed-reach hop: same rig as `jump`, but frustrated — narrowed,
        # strained eyes instead of the happy hop.
        j = abs(_sin(frame, 16, 5.5))            # tall hop
        bob = -j
        sy = 1.0 + 0.14 * (j / 5.5)              # stretch at apex
        sx = 1.0 - 0.10 * (j / 5.5)
        legphase = 0.5
        eyes = "squint"

    # arm pose derived from state (arms live on the LEFT/RIGHT sides)
    arm = {"work_computer": "none", "attention": "up", "celebrate": "up",
           "held": "up", "falling": "up", "juggle": "up", "wave": "wave",
           "climbdown": "up"}.get(state, "side")
    arm_swing = (_sin(frame, 12, 0.5) if state == "walk" else
                 _sin(frame, 16, 0.5) if state in _WALKERS else 0.0)

    # ---- geometry (art-pixel space), origin at ox,oy ----
    # body occupies cols 3..18, rows 5..12 ; legs rows 12..15 ; crown rows 3..5
    cx = GRID_W / 2.0

    def px(col, row, w, h, color):
        # apply squash/stretch about body center
        bcx, bcy = 10.5, 9.0
        X = bcx + (col - bcx) * sx
        Y = bcy + (row - bcy) * sy + bob + baseline_lift
        W = w * sx
        H = h * sy
        p.fillRect(QRectF(ox + X * u, oy + Y * u, W * u + 0.5, H * u + 0.5), color)

    p.save()
    # face direction of travel: mirror the BODY only. Props/text (drawn after the
    # matching p.restore below) stay upright, so speech bubbles and z's never
    # read backwards when the creature walks left.
    if facing < 0:
        p.translate(2 * (ox + cx * u), 0)
        p.scale(-1, 1)
    # tilt about creature center
    if tilt:
        p.translate(ox + cx * u, oy + 10 * u)
        p.rotate(tilt)
        p.translate(-(ox + cx * u), -(oy + 10 * u))

    # ---- legs (behind body) ----
    # 4 legs; walk cycle lifts diagonal pairs (symmetric about body center 10.5)
    leg_cols = [4.0, 7.5, 11.5, 15.0]
    for i, lc in enumerate(leg_cols):
        lift = 0.0
        if state in _WALKERS:
            ph = (legphase + (0.5 if i % 2 else 0.0)) % 1.0
            lift = max(0.0, math.sin(ph * math.pi)) * 1.3
        if state == "work_computer" and i >= 2:  # front two legs tap
            lift = front_tap
        if state == "celebrate":
            lift = 1.6
        px(lc, 12.4 - lift, 2.0, 3.4, ORANGE_D)

    # ---- arms: one block per side, body-shade color, drawn behind body ----
    if arm == "none":
        pass   # hands are drawn on the laptop (working state)
    elif arm == "up":
        # raised out to the sides, up near the shoulders
        px(1.6, 4.6, 2.1, 1.9, ORANGE_D)
        px(17.3, 4.6, 2.1, 1.9, ORANGE_D)
    elif arm == "wave":
        # left arm down at side, right arm raised and swinging (the wave)
        wv = _sin(frame, 16, 1.4)
        px(1.0, 7.9, 2.2, 1.9, ORANGE_D)                 # left arm at side
        px(17.3, 3.4 + wv, 2.1, 1.9, ORANGE_D)           # right arm up, waving
    elif arm == "tap":
        # dropped down-forward, gently tapping (typing), opposite phase
        px(2.2, 10.0 + front_tap, 2.1, 1.7, ORANGE_D)
        px(17.7, 10.0 + (0.8 - front_tap), 2.1, 1.7, ORANGE_D)
    else:
        # held straight out to the sides (default), gentle swing while walking
        px(1.0, 7.9 + arm_swing, 2.2, 1.9, ORANGE_D)
        px(17.8, 7.9 - arm_swing, 2.2, 1.9, ORANGE_D)

    # ---- body ---- clean square block, dark outline for crisp edges
    bx0, bx1 = 3.0, 18.0
    by0, by1 = 5.0, 12.5
    bw = bx1 - bx0
    px(bx0, by0, bw, by1 - by0, ORANGE)                # full rectangle
    px(bx0, by0, bw, 0.9, ORANGE_L)                    # top bevel highlight
    px(bx0, by1 - 1.0, bw, 1.0, ORANGE_D)              # bottom shade

    # ---- eyes ---- (front-biased; faces right by default)
    e1, e2 = 5.8, 13.8   # eye columns — wide-set (~2.5x the previous spacing)
    er = 7.4
    def eye(col, kind):
        if kind == "open":
            px(col, er, 1.4, 1.8, EYE)
        elif kind == "blink":
            px(col, er + 1.0, 1.4, 0.6, EYE)
        elif kind == "sleep":
            px(col - 0.6, er + 1.0, 2.6, 0.6, EYE)   # wider closed eyes when sleeping
        elif kind == "focus":
            px(col, er + 0.6, 1.6, 0.9, EYE)
        elif kind == "squint":
            # scrunched-shut straining eyes "><": each eye is two short strokes
            # meeting at a point on its INNER side, so the vertices point toward
            # the nose. Left eye ">" (point on its right), right eye "<" (point
            # on its left) — a MIRRORED per-eye shape, so key off which side the
            # eye is on (this style only; others stay identical L/R).
            left = col < 10.0
            c = col + (0.5 if left else -0.5)         # shift ½ cell inward (nose)
            vtx = c + 0.9 if left else c              # inner vertex block x
            outr = c if left else c + 0.9             # outer stroke ends x
            px(outr, er + 0.3, 1.1, 0.6, EYE)         # upper stroke (outer end)
            px(vtx, er + 0.85, 1.1, 0.6, EYE)         # inner vertex (mid)
            px(outr, er + 1.4, 1.1, 0.6, EYE)         # lower stroke (outer end)
        elif kind == "up":
            px(col, er - 0.4, 1.4, 1.6, EYE)
        elif kind == "wide":
            px(col - 0.2, er - 0.4, 1.9, 2.4, EYE)
        elif kind == "x":
            px(col, er, 1.7, 0.5, EYE); px(col + 0.6, er - 0.6, 0.5, 1.7, EYE)
        elif kind == "happy":
            px(col, er + 0.8, 0.6, 0.6, EYE); px(col + 0.55, er + 0.3, 0.6, 0.6, EYE); px(col + 1.1, er + 0.8, 0.6, 0.6, EYE)
    def headset(top, glint):
        # the SAME VR headset, drawn with its housing top at row `top`. Worn over
        # the eyes when down; the identical shape raised onto the head when up.
        px(3.9, top, 13.2, 2.7, VISOR)                       # silver housing
        px(3.5, top, 1.6, 3.1, VISOR)                        # left wrap (down)
        px(15.9, top, 1.6, 3.1, VISOR)                       # right wrap (down)
        px(3.9, top, 13.2, 0.5, VISOR_HI)                    # top highlight rim
        px(3.9, top + 2.1, 13.2, 0.6, VISOR_D)               # bottom shade
        px(5.0, top + 0.5, 11.0, 1.5, VISOR_GLASS)           # dark screen inset
        swp = frame % 96                                     # travelling reflection
        if swp < 12:
            px(5.4 + swp * 0.9, top + 0.55, 0.9, 1.4, QColor("#9FD3FF"))
        else:
            px(9.6, top + 0.75, 1.7, 0.45, QColor("#3A4256"))
        if glint and (frame % 24) < 12:
            px(12.8, top + 0.85, 1.1, 0.8, QColor("#FF3B3B"))  # red status LED

    if eyes in ("shades", "shades_glint"):
        headset(er - 0.5, glint=(eyes == "shades_glint"))   # worn over the eyes
    else:
        eye(e1, eyes); eye(e2, eyes)
        if visor == "up":
            headset(er - 4.5, glint=False)   # same headset, pushed up onto the head

    if cap:
        # a hat on the crown (agent companions) — drawn in head space so it
        # bobs/tilts/mirrors with the body. pieces are centred on the body
        # centre col 10.5 (an off-centre hat reads as tilted at small u).
        if cap in ("agent", "cap"):            # yellow kindergarten cap
            px(3.7, 3.6, 13.6, 1.0, CAP_D)     # brim across the head, front shade
            px(5.3, 2.0, 10.4, 2.0, CAP)       # rounded crown of the cap
            px(6.9, 1.1, 7.2, 1.2, CAP)        # dome top
            px(6.9, 1.1, 7.2, 0.4, CAP_HI)     # highlight rim
            px(9.7, 0.4, 1.6, 1.0, CAP_D)      # little top button
        elif cap == "hardhat":                 # construction helmet
            px(3.2, 3.7, 14.6, 1.0, HARD)      # wide brim
            px(5.3, 1.5, 10.4, 2.4, HARD)      # dome
            px(6.9, 0.8, 7.2, 1.0, HARD)       # dome top
            px(9.6, 0.5, 1.8, 3.2, HARD_HI)    # white centre ridge
        elif cap == "beret":                   # artist beret
            px(4.6, 2.9, 11.8, 1.5, BERET)     # flat blob
            px(6.0, 2.1, 9.0, 1.0, BERET)      # upper puff
            px(9.9, 1.2, 1.2, 1.1, BERET_D)    # stem
        elif cap == "tophat":                  # tiny top hat
            px(4.4, 3.9, 12.2, 0.8, INK)       # brim
            px(6.6, 0.3, 7.8, 3.8, INK)        # cylinder
            px(6.6, 2.9, 7.8, 0.9, INK_BAND)   # band
        elif cap == "propeller":               # propeller beanie (spinning!)
            px(5.6, 2.9, 9.8, 1.6, PROP)       # cap base
            px(7.2, 2.0, 6.6, 1.1, PROP)       # dome
            px(9.9, 1.0, 1.2, 1.2, PROP)       # stick
            if (frame // 4) % 2 == 0:          # blades: wide <-> narrow = spin
                px(6.6, 0.3, 7.8, 0.8, PROP_BLADE)
            else:
                px(8.9, 0.3, 3.2, 0.8, PROP_BLADE)
        elif cap == "beanie":                  # knitted beanie + pompom
            px(4.8, 3.3, 11.4, 1.2, BEANIE_D)  # folded band
            px(5.3, 1.6, 10.4, 2.0, BEANIE)    # knit dome
            px(6.9, 0.9, 7.2, 1.0, BEANIE)
            px(9.6, 0.0, 1.8, 1.2, WHITE)      # pompom

    p.restore()

    # ---- props (screen-ish space, not tilted) ----
    def rect(col, row, w, h, color):
        Y = row + bob + baseline_lift
        p.fillRect(QRectF(ox + col * u, oy + Y * u, w * u + 0.5, h * u + 0.5), color)

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont, QPen, QPainterPath
    if prop == "bulb":
        rect(17.5, 0.6, 3.0, 3.0, BULB)
        rect(18.2, 0.9, 1.2, 1.2, BULB_L)
        rect(18.3, 3.5, 1.6, 0.8, ORANGE_D)
    elif prop == "spark":
        rect(19.0, 6.0, 0.9, 0.9, BULB_L)
        rect(20.0, 7.2, 0.7, 0.7, BULB)
        rect(19.3, 8.2, 0.6, 0.6, BULB_L)
    elif prop == "laptop":
        # hands drawn FIRST so the screen covers them (they type behind the laptop),
        # peeking at the sides; bright body color so the motion is visible on the dark lid
        tapL = _sin(frame, 16, 0.5) + 0.5
        tapR = _sin(frame, 16, 0.5, 0.5) + 0.5
        rect(4.8, 10.4 + tapL, 2.0, 1.8, ORANGE_L)
        rect(14.2, 10.4 + tapR, 2.0, 1.8, ORANGE_L)
        # laptop lid (back), sitting a bit lower so more of the head shows above
        rect(6.0, 9.8, 9.0, 3.7, QColor("#4C4C57"))      # screen frame (back)
        rect(6.6, 10.2, 7.8, 3.0, QColor("#25252B"))     # screen back panel
        rect(6.2, 13.2, 8.6, 0.5, QColor("#1C1C20"))     # bottom edge on the desk
        # logo: warm white, slow blink
        if (frame % 72) < 46:
            rect(9.5, 11.1, 1.7, 1.2, BULB_L)
        # intermittent thought bubble that types out . .. ...
        cyc = frame % 150
        if 45 <= cyc < 120:
            n = 1 if cyc < 68 else (2 if cyc < 92 else 3)
            rect(6.3, 0.2, 7.4, 2.4, WHITE)              # bubble
            rect(11.6, 2.9, 1.0, 1.0, WHITE)             # trail puff
            rect(12.4, 4.0, 0.8, 0.8, WHITE)             # trail puff (small)
            for i in range(n):
                rect(7.5 + i * 1.7, 1.1, 0.9, 0.9, QColor("#3A3A42"))
    elif prop == "bang":
        bxx, byy = 17.5, -0.2
        rect(bxx, byy, 3.6, 3.2, WHITE)
        # tail
        p.fillRect(QRectF(ox + (bxx + 0.4) * u, oy + (byy + 3.0 + bob) * u,
                          1.0 * u, 1.0 * u), WHITE)
        # bold pixel "!" (stem + dot), centered in the bubble
        ex = bxx + 1.3
        rect(ex, byy + 0.6, 1.0, 1.5, BANG)     # stem
        rect(ex, byy + 2.35, 1.0, 0.75, BANG)   # dot
    elif prop in ("dizzy", "dizzy2"):
        yoff = 0.0 if prop == "dizzy" else 0.6
        p.setPen(QPen(ZTXT)); f = QFont("Sans"); f.setPointSizeF(1.4 * u); f.setBold(True); p.setFont(f)
        p.drawText(int(ox + 5 * u), int(oy + (3.0 + yoff) * u), "✦")
        p.drawText(int(ox + 8 * u), int(oy + (2.4 + yoff) * u), "✦")
        p.setPen(Qt.PenStyle.NoPen)
    elif prop == "zzz":
        p.setPen(QPen(ZTXT))
        f = QFont("Sans"); f.setPointSizeF(1.2 * u); f.setBold(True); p.setFont(f)
        p.drawText(int(ox + 18 * u), int(oy + (4.0 + bob) * u), "z")
        f2 = QFont("Sans"); f2.setPointSizeF(1.8 * u); f2.setBold(True); p.setFont(f2)
        p.drawText(int(ox + 19.4 * u), int(oy + (2.2 + bob) * u), "Z")
        p.setPen(Qt.PenStyle.NoPen)
    elif prop == "ponder":
        # slow "?" that fades in over the head
        if (frame % 90) > 20:
            p.setPen(QPen(ZTXT)); f = QFont("Sans"); f.setPointSizeF(1.8 * u)
            f.setBold(True); p.setFont(f)
            p.drawText(int(ox + 18 * u), int(oy + (3.2 + bob) * u), "?")
            p.setPen(Qt.PenStyle.NoPen)
    elif prop == "magnify":
        # a magnifying glass sweeping side to side out front — dark rim for
        # contrast against the body, bright glass with a travelling glint.
        mx = _sin(frame, 26, 0.7)                        # slow scanning sweep
        rect(17.2 + mx, 5.8, 3.2, 3.2, EYE)              # dark outline rim
        rect(17.5 + mx, 6.1, 2.6, 2.6, QColor("#D7DEE6"))  # metal ring
        rect(18.0 + mx, 6.6, 1.6, 1.6, QColor("#8FD0EA"))  # glass
        rect(18.2 + mx + _sin(frame, 26, 0.4, 0.25), 6.8, 0.6, 0.6, WHITE)  # glint
        rect(19.8 + mx, 8.6, 1.8, 1.5, EYE)              # handle (grip)
    elif prop == "phone":
        # a handset held to the ear — earpiece + mouthpiece so it reads as a
        # phone, a bright speaker slit, and expanding ring waves that pulse out.
        rect(1.7, 6.0, 1.7, 3.2, QColor("#33333B"))      # handset body
        rect(1.3, 5.6, 2.5, 1.0, QColor("#33333B"))      # earpiece
        rect(1.3, 8.7, 2.5, 1.0, QColor("#33333B"))      # mouthpiece
        rect(1.9, 5.8, 1.0, 0.5, QColor("#8FD0EA"))      # speaker slit
        rw = frame % 46                                  # ring waves radiate out
        if rw < 34:
            step = rw // 12                              # 0,1,2 -> up from the ear
            # radiate up-and-slightly-left but stay on-window (only col >= -1 shows)
            rect(0.3 - step * 0.5, 4.6 - step * 1.1, 0.8, 0.8, BULB_L)
    elif prop == "clones":
        # two mini creatures filing out to the right, bobbing in sequence,
        # each with a dark outline + shadow so they pop off the body.
        for k in range(2):
            mb = _sin(frame, 18, 0.6, phase=k * 0.5)
            bx = 18.5 + k * 2.4
            rect(bx - 0.2, 9.3 + mb, 2.2, 2.2, EYE)      # dark outline
            rect(bx, 9.5 + mb, 1.8, 1.8, ORANGE)         # tiny body
            rect(bx, 9.5 + mb, 1.8, 0.5, ORANGE_L)       # highlight
            rect(bx + 0.35, 10.1 + mb, 0.45, 0.55, EYE)  # eye
            rect(bx + 0.1, 11.4, 1.6, 0.4, QColor("#00000040"))  # ground shadow
    elif prop == "hat":
        # party/wizard cone hat + a sparkle
        rect(9.0, 2.0, 3.0, 0.7, QColor("#6C5CE7"))      # brim
        rect(9.7, 0.6, 1.6, 1.6, QColor("#8E7CFF"))      # cone
        rect(10.1, 0.1, 0.8, 0.8, BULB_L)                # pom
        if (frame % 30) < 15:
            rect(13.0, 1.4, 0.9, 0.9, BULB_L)            # sparkle
    elif prop == "gear":
        # a cog ticking over beside the head — teeth alternate N/S/E/W vs
        # diagonal each tick so it reads as turning ("running by itself").
        gx, gy = 18.3, 2.2
        cog, hole = QColor("#B8BEC8"), QColor("#25252B")
        rect(gx + 0.9, gy + 0.9, 1.7, 1.7, cog)          # hub
        if (frame // 5) % 2 == 0:
            rect(gx + 1.4, gy, 0.8, 0.9, cog)            # N
            rect(gx + 1.4, gy + 2.6, 0.8, 0.9, cog)      # S
            rect(gx, gy + 1.4, 0.9, 0.8, cog)            # W
            rect(gx + 2.6, gy + 1.4, 0.9, 0.8, cog)      # E
        else:
            rect(gx + 0.4, gy + 0.4, 0.85, 0.85, cog)    # NW
            rect(gx + 2.2, gy + 0.4, 0.85, 0.85, cog)    # NE
            rect(gx + 0.4, gy + 2.2, 0.85, 0.85, cog)    # SW
            rect(gx + 2.2, gy + 2.2, 0.85, 0.85, cog)    # SE
        rect(gx + 1.45, gy + 1.45, 0.6, 0.6, hole)       # center hole
    elif prop == "window":
        # a little blue code window floating beside the visor (auto_computer)
        wx, wy = 16.8, 1.2
        rect(wx, wy, 5.4, 4.4, QColor("#2A3550"))        # window body
        rect(wx, wy, 5.4, 1.0, QColor("#3E5488"))        # title bar
        rect(wx + 0.4, wy + 0.35, 0.4, 0.4, QColor("#E06C6C"))  # close dot
        rect(wx + 1.1, wy + 0.35, 0.4, 0.4, QColor("#E0B24C"))  # min dot
        rect(wx + 0.5, wy + 1.5, 3.4, 0.5, QColor("#6FC3E0"))   # code line
        rect(wx + 0.5, wy + 2.4, 2.4, 0.5, QColor("#8FD0EA"))   # code line
        if (frame % 30) < 18:
            rect(wx + 0.5, wy + 3.3, 1.6, 0.5, QColor("#6FC3E0"))  # typing line
    elif prop == "clones_v":
        # mini creatures like `clones`, but each wears a tiny visor too
        for k in range(2):
            mb = _sin(frame, 18, 0.6, phase=k * 0.5)
            bx = 18.5 + k * 2.2
            rect(bx, 9.5 + mb, 1.8, 1.8, ORANGE)         # tiny body
            rect(bx, 9.5 + mb, 1.8, 0.5, ORANGE_L)       # highlight
            rect(bx + 0.2, 10.15 + mb, 1.4, 0.5, EYE)    # tiny visor band
    elif prop == "note":
        # music notes bobbing up beside the head, cycling
        for k in range(2):
            nb = _sin(frame, 24, 0.8, phase=k * 0.5)
            nx = 17.6 + k * 1.9
            rect(nx, 2.4 + nb, 1.1, 1.1, EYE)            # note head
            rect(nx + 0.9, 1.2 + nb, 0.4, 2.3, EYE)      # stem
    elif prop == "balls":
        # three balls arcing overhead on staggered phases
        cols = [BULB, ORANGE_L, BULB_L]
        for k in range(3):
            t = ((frame + k * 12) % 36) / 36.0           # 0..1 around the arc
            bx = 6.0 + 9.0 * t                           # left -> right
            by = 2.6 + 3.2 * (1.0 - math.sin(t * math.pi))  # arc: high in the middle
            rect(bx, by, 1.2, 1.2, cols[k])
    elif prop == "speech":
        phrase = _speech(state)
        if phrase:
            n = len(phrase)
            cyc = frame % (n * 7 + 30)          # type ~1 char / 7 frames, then hold
            shown = min(n, 1 + cyc // 7)
            text = phrase[:shown]
            f = QFont("Sans"); f.setPointSizeF(1.4 * u); f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(phrase)   # size to the FULL phrase (stable bubble)
            th = fm.height()
            pad = 0.7 * u
            bx = ox + (GRID_W * u - tw) / 2.0
            by = oy + 0.2 * u
            path = QPainterPath()
            path.addRoundedRect(QRectF(bx - pad, by, tw + 2 * pad, th + pad), 5, 5)
            p.fillPath(path, WHITE)
            # little tail under the bubble
            p.fillRect(QRectF(bx + tw / 2.0, by + th + pad - 1, 1.1 * u, 1.0 * u), WHITE)
            p.setPen(QPen(QColor("#2A2A30")))
            p.drawText(QRectF(bx - pad, by, tw + 2 * pad, th + pad),
                       Qt.AlignmentFlag.AlignCenter, text)
            p.setPen(Qt.PenStyle.NoPen)


# ---------- standalone mockup renderer ----------
if __name__ == "__main__":
    import os, sys
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QImage, QPainter, QFont, QPen, QGuiApplication
    from PyQt6.QtCore import Qt, QRectF
    app = QGuiApplication(sys.argv)

    # sheet language: `python3 creature.py <out.png> [ko|en]` (default ko)
    sheet_lang = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] in ("ko", "en") else "ko"
    set_lang(sheet_lang)

    # caption = what triggers this animation (no parenthetical prop notes)
    LABELS = {
        "ko": {"idle": "대기", "walk": "배회",
               "work_computer": "편집·실행", "work_search": "읽기·검색",
               "work_web": "웹·MCP", "work_agent": "서브에이전트",
               "work_skill": "스킬 실행", "autopilot": "자동 진행",
               "auto_computer": "자동 편집", "auto_search": "자동 읽기·검색",
               "auto_web": "자동 웹", "auto_agent": "자동 서브에이전트",
               "auto_skill": "자동 스킬", "thinking": "프롬프트 받음",
               "attention": "권한 요청", "asking": "질문·플랜 대기",
               "celebrate": "완료", "error": "실패", "sleeping": "수면",
               "jump": "모션 · 점프", "wave": "모션 · 손 흔들기",
               "sing": "모션 · 노래", "juggle": "모션 · 저글링", "float": "모션 · 둥둥",
               "climbdown": "모션 · 내려오기", "strain": "모션 · 안간힘"},
        "en": {"idle": "idle", "walk": "roaming",
               "work_computer": "edit · run", "work_search": "read · search",
               "work_web": "web · MCP", "work_agent": "subagent",
               "work_skill": "skill", "autopilot": "autopilot",
               "auto_computer": "auto · edit", "auto_search": "auto · read/search",
               "auto_web": "auto · web", "auto_agent": "auto · subagent",
               "auto_skill": "auto · skill", "thinking": "prompt in",
               "attention": "permission", "asking": "question / plan",
               "celebrate": "done", "error": "failed", "sleeping": "asleep",
               "jump": "motion · jump", "wave": "motion · wave",
               "sing": "motion · sing", "juggle": "motion · juggle",
               "float": "motion · float",
               "climbdown": "motion · climb down", "strain": "motion · strain"},
    }
    labels = LABELS[sheet_lang]
    TITLE = {"ko": "claudlet — 오리지널 크리처 · 전부 코드 렌더 · CC0",
             "en": "claudlet — original creature · all code-rendered · CC0"}
    # NOTE: work_agent / auto_agent are omitted — subagents are now shown by the
    # follower companion, not a main-creature state, so they'd never appear here.
    order = ["idle", "walk", "work_computer", "work_search", "work_web",
             "work_skill", "autopilot",
             "auto_computer", "auto_search", "auto_web", "auto_skill",
             "thinking", "attention", "asking",
             "celebrate", "error", "sleeping",
             "jump", "wave", "sing", "juggle", "float", "climbdown", "strain"]
    # show two animation frames per state to convey motion
    u = 7
    cellw, cellh = 210, 190
    cols = 4
    rows = (len(order) + cols - 1) // cols
    W, H = cols * cellw, rows * cellh + 60
    img = QImage(W, H, QImage.Format.Format_ARGB32); img.fill(QColor("#141416"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.setPen(QPen(QColor("#ECA184"))); f = QFont("Sans", 15); f.setBold(True); p.setFont(f)
    p.drawText(QRectF(0, 14, W, 26), Qt.AlignmentFlag.AlignCenter, TITLE[sheet_lang])
    from PyQt6.QtGui import QPainterPath
    for i, st in enumerate(order):
        c = i % cols; r = i // cols
        x0 = c * cellw; y0 = 50 + r * cellh
        path = QPainterPath(); path.addRoundedRect(QRectF(x0 + 10, y0 + 10, cellw - 20, cellh - 20), 12, 12)
        p.fillPath(path, QColor("#26262B")); p.setPen(QPen(QColor("#3A3A42"), 1)); p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        # draw creature roughly centered
        gx = x0 + (cellw - GRID_W * u) / 2
        gy = y0 + (cellh - GRID_H * u) / 2 - 6
        if st in SPEECH:            # freeze where the bubble is fully typed & held
            frame = len(_speech(st)) * 7 + 5
        elif st == "work_computer":
            frame = 100
        elif st == "walk":
            frame = 6
        else:
            frame = 8
        draw_creature(p, gx, gy, u, st, frame)
        p.setPen(QPen(QColor("#D7D7DC"))); p.setFont(QFont("Sans", 12))
        p.drawText(QRectF(x0, y0 + cellh - 40, cellw, 24), Qt.AlignmentFlag.AlignCenter, labels[st])
        p.setPen(Qt.PenStyle.NoPen)
    p.end()
    import tempfile
    out = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(tempfile.gettempdir(), "creature_sheet.png")
    img.save(out); print("saved", out)
