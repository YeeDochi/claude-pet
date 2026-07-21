from claudlet.core import petting


def test_back_and_forth_triggers():
    # 0.1s 간격 좌우 왕복(폭 40px)이 3회 이상 반전 -> 발동
    xs = [0, 40, 0, 40, 0, 40, 0]
    samples = [(i * 0.1, x) for i, x in enumerate(xs)]
    now = samples[-1][0]
    assert petting.detect_stroke(samples, now) is True


def test_small_jitter_does_not_trigger():
    # 폭 3px 미세 지터는 스윙으로 안 침 -> 미발동
    xs = [0, 3, 0, 3, 0, 3, 0, 3]
    samples = [(i * 0.1, x) for i, x in enumerate(xs)]
    now = samples[-1][0]
    assert petting.detect_stroke(samples, now) is False


def test_single_sweep_does_not_trigger():
    # 한 방향 쭉(반전 없음) -> 미발동
    xs = [0, 20, 40, 60, 80, 100]
    samples = [(i * 0.1, x) for i, x in enumerate(xs)]
    now = samples[-1][0]
    assert petting.detect_stroke(samples, now) is False


def test_cooldown_suppresses_refire():
    xs = [0, 40, 0, 40, 0, 40, 0]
    samples = [(i * 0.1, x) for i, x in enumerate(xs)]
    now = samples[-1][0]
    assert petting.detect_stroke(samples, now, last_fire=now - 0.5) is False
    assert petting.detect_stroke(samples, now, last_fire=now - 2.0) is True


def test_old_samples_outside_window_ignored():
    xs = [0, 40, 0, 40, 0, 40, 0]
    samples = [(i * 0.1, x) for i, x in enumerate(xs)]
    now = samples[-1][0] + 5.0
    assert petting.detect_stroke(samples, now) is False
