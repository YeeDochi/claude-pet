"""쓰다듬기(호버 왕복) 제스처 판정 — 순수 함수.

pet.py가 버튼 없는 호버의 (t, cursor_x) 표본을 모아 넘기면, 최근 window(초)
안에서 좌우 방향 반전이 충분히(각 스윙이 min_swing 이상, min_reversals회 이상)
일어났는지 판정한다. GUI/입력에 의존하지 않아 데이터로 테스트된다.
"""

STROKE_WINDOW = 1.2          # 판정에 쓰는 최근 표본 시간창 (초)
STROKE_MIN_REVERSALS = 3     # 필요한 방향 반전 횟수
STROKE_MIN_SWING = 15.0      # 반전으로 인정할 최소 스윙 이동폭 (px)
STROKE_COOLDOWN = 1.5        # 연속 재발동 억제 (초)
_MIN_STEP = 1.0              # 이보다 작은 이동은 노이즈로 무시 (px)


def detect_stroke(samples, now, *, window=STROKE_WINDOW,
                  min_reversals=STROKE_MIN_REVERSALS,
                  min_swing=STROKE_MIN_SWING, cooldown=STROKE_COOLDOWN,
                  last_fire=None):
    """samples: [(t, x), …] 최근 호버. 쓰다듬기면 True."""
    if last_fire is not None and now - last_fire < cooldown:
        return False
    recent = [x for (t, x) in samples if now - t <= window]
    if len(recent) < 3:
        return False

    reversals = 0
    direction = 0        # -1 왼쪽, +1 오른쪽, 0 미정
    swing = 0.0
    prev_x = recent[0]
    for x in recent[1:]:
        dx = x - prev_x
        prev_x = x
        if abs(dx) < _MIN_STEP:
            continue
        d = 1 if dx > 0 else -1
        if direction == 0:
            direction = d
            swing = abs(dx)
        elif d == direction:
            swing += abs(dx)
        else:
            if swing >= min_swing:      # 직전 스윙이 충분했을 때만 반전 카운트
                reversals += 1
            direction = d
            swing = abs(dx)
    return reversals >= min_reversals
