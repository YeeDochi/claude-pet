import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import physics


def test_falls_and_settles_on_floor():
    x, y, vx, vy = 100.0, 0.0, 0.0, 0.0
    floor, settled = 200.0, False
    for _ in range(2000):
        x, y, vx, vy, settled = physics.advance(x, y, vx, vy, 0.0, 500.0, floor)
        if settled:
            break
    assert settled
    assert y == floor
    assert vx == 0.0 and vy == 0.0


def test_rebounds_lose_energy():
    x, y, vx, vy = 100.0, 0.0, 0.0, 0.0
    floor, rebounds = 200.0, []
    for _ in range(3000):
        py = y
        x, y, vx, vy, settled = physics.advance(x, y, vx, vy, 0.0, 500.0, floor)
        if py < floor and y >= floor and vy < 0:   # bounced up this step
            rebounds.append(-vy)
        if settled:
            break
    assert len(rebounds) >= 2
    assert rebounds[0] > rebounds[-1]               # energy lost across bounces


def test_stays_within_horizontal_bounds():
    x, y, vx, vy = 250.0, 0.0, 80.0, -30.0
    L, R, floor = 0.0, 500.0, 200.0
    for _ in range(500):
        x, y, vx, vy, _ = physics.advance(x, y, vx, vy, L, R, floor)
        assert L <= x <= R
        assert y <= floor


def test_velocity_is_capped():
    x, y, vx, vy, _ = physics.advance(0.0, 0.0, 9999.0, 9999.0, -1e9, 1e9, 1e9)
    assert abs(vx) <= physics.V_MAX
    assert abs(vy) <= physics.V_MAX
