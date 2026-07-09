"""Pure 2-D toss physics for the pet: gravity, air drag, wall/floor bounce.

No Qt, no wall-clock — the caller passes position/velocity and bounds and gets
the next step back, so it is deterministic and unit-testable.
"""

GRAVITY = 1.4            # downward accel per step
AIR_DRAG = 0.99          # horizontal damping per step while airborne
WALL_RESTITUTION = 0.5   # fraction of speed kept after a side-wall bounce
FLOOR_RESTITUTION = 0.45
FLOOR_FRICTION = 0.6     # horizontal damping on floor contact
SETTLE_VY = 2.0          # below this |vy| at the floor, stop bouncing
SETTLE_VX = 0.6
V_MAX = 60.0             # clamp so a hard fling can't teleport the pet


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def advance(x, y, vx, vy, left, right, floor_y):
    """Advance one physics step. Returns (x, y, vx, vy, settled)."""
    vy = _clamp(vy + GRAVITY, -V_MAX, V_MAX)
    vx = _clamp(vx, -V_MAX, V_MAX)
    x += vx
    y += vy
    vx *= AIR_DRAG
    if x < left:
        x = left; vx = -vx * WALL_RESTITUTION
    elif x > right:
        x = right; vx = -vx * WALL_RESTITUTION
    settled = False
    if y >= floor_y:
        y = floor_y
        vy = -vy * FLOOR_RESTITUTION
        vx *= FLOOR_FRICTION
        if abs(vy) < SETTLE_VY and abs(vx) < SETTLE_VX:
            vx = vy = 0.0
            settled = True
    return x, y, vx, vy, settled
