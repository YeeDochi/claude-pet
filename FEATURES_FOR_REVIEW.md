# claude-pet — 리뷰 대기 기능 목록

> Claude가 TODO 기반으로 자율 개발한 피처들. 각 피처는 전용 브랜치에 있고,
> 네가 "이 피처 보자" 하면 같이 훑고 `main`(현재 `master`)에 머지한다.
> ✅ = 브랜치에서 완성·테스트 통과, 리뷰 대기 | 🚧 = 작업 중 | 📋 = 계획(아직 안 만듦)

## 리뷰 대기 (완성됨)

### 🟢 `feat/session-bound-pets` — 세션당 펫 재설계 — **MERGED (2026-07-09)**
- 실동작 확인(펫 2마리 독립 반응 / SessionEnd 시 해당 펫만 퇴장) 후 master 머지. 훅도 실제 설치됨 → 새 세션 열면 펫 자동 등장. 브랜치 삭제됨.
- **테스트**: 38/38 통과. 전체-브랜치 리뷰(opus) 통과.
- **한 것**:
  - `src/hostinfo.py` 신설 — 호스트 감지(vscode/jetbrains/konsole/unknown) + 세션별 소켓 경로 (훅·펫 공유)
  - `src/focus.py` — `terminal_focused(classes)` 호스트-인식 + `xprop`/kdotool로 활성창 읽기 (이 머신에서도 포커스 판정 가능해짐)
  - `bin/claude-pet-hook` — 세션별 소켓, `SessionStart` 시 그 세션 펫을 detached 실행(중복실행 가드), exit-0 불변식 유지
  - `src/pet.py` — `--session/--host` 인자, 세션별 소켓, 호스트 창으로 activate/focus, `SessionEnd`(취소가능) 종료, 시작 위치 분산, 세션별 창제목
- **리뷰가 검증함**: launch race·stale socket 올바르게 처리, 훅 non-blocking, celebrate 안전 축소.
- **직접 봐야 할 것 (리뷰 시)**: 세션 2개(Konsole 1 + VS Code 1) 띄워서 펫 2마리 각자 반응 / 각 좌클릭이 제 호스트 창 띄우는지 / SessionEnd 시 해당 펫만 사라지는지.
- **이월된 마이너**(머지 전 선택): SIGKILL로 죽은 세션은 SessionEnd 안 와서 펫 orphan 잔존(리퍼 없음); 동시 SessionStart TOCTOU 이중실행(이론상); 훅 심볼릭링크 경로. → 후속 `/claude-pet` 정지 스킬로 커버 가능.
- **스펙 편차**(무해): 계획의 `bin/claude-pet-session` 대신 기존 `bin/claude-pet --session/--host` 재사용.

### 🟢 `feat/bubble-text` — 상태별 타이핑 말풍선 — **MERGED (2026-07-09)**
- master 머지 완료(3-way, session-bound와 무충돌). 브랜치 삭제됨. 전체 39테스트 통과.
- **한 것**: `creature.py`에 `SPEECH` 추가 — thinking="고민중…", attention="이거 맞아?", celebrate="다 됐다!", error="으악!". 머리 위 말풍선에 한 글자씩 타이핑되고 잠깐 유지 후 반복. 해당 4상태의 아이콘 프롭(?, !, ✦)을 말풍선으로 대체.
- **직접 봐야 할 것 (리뷰 시)**: 문구·위치·타이핑 속도가 취향에 맞는지 (아트 튜닝 여지). attention이 `!` 대신 "이거 맞아?" 텍스트로 바뀐 게 나은지 아니면 `!`도 같이 둘지.
- **주의**: `feat/session-bound-pets`와 독립 브랜치(둘 다 master에서 분기, 파일 겹침 없음) — 순서 상관없이 각각 머지 가능.

### ✅ `feat/claude-pet-skill` — `/claude-pet` 스킬 (그냥 펫 하나 띄우기)
- **브랜치**: `feat/claude-pet-skill`. 코드 변경 없음(스킬 파일 + README).
- **한 것**: `skills/claude-pet/SKILL.md` 신설 — `/claude-pet`(또는 "펫 띄워") 입력 시 펫 하나를 detached 실행. README에 활성화법(심볼릭 링크) 추가.
- **직접 봐야 할 것**: `ln -s ~/claude-pet/skills/claude-pet ~/.claude/skills/claude-pet` 후 `/claude-pet` 쳐서 펫 뜨는지.

### ✅ `feat/physics` — 제대로 된 드래그-던지기 물리
- **브랜치**: `feat/physics`. 테스트 43/43.
- **한 것**: 인라인 `_physics`를 순수 `src/physics.py`로 추출 + 개선(중력·**공기저항**·벽/바닥 반발·**속도 상한 V_MAX**·정착 판정). 유닛테스트로 낙하·정착, 반발 에너지 감소, 화면 밖 안 나감, 속도 클램프 검증.
- **직접 봐야 할 것 (리뷰 시)**: 실제로 드래그해서 던졌을 때 **느낌**(세기·바운스·마찰) — 상수(GRAVITY/AIR_DRAG/…RESTITUTION) 취향대로 튜닝 여지.

## 계획 — Claude 추천 우선순위

| 우선 | 브랜치 | 내용 | 왜 추천 |
|---|---|---|---|
| 1 | `feat/session-bound-pets` 🟢 | **MERGED — 훅 설치 완료, 새 세션에서 자동 실행.** | — |
| 2 | `feat/bubble-text` 🟢 | **MERGED.** | — |
| 3 | `feat/claude-pet-skill` ✅ | **완성 — 리뷰 대기.** `/claude-pet`로 펫 띄우기 | 사용자 요청 top-3 |
| 4 | `feat/physics` ✅ | **완성 — 리뷰 대기.** 드래그-던지기 물리 개선 | 사용자 요청 top-3 |
| 5 | `feat/window-perch` 📋 | **창 위 올라타기** (KDE 전용, 게이팅) — 3동작: 창 상단바 올라타기 / 창 안 갇히기 / 드래그해서 넣기. 큰 기능이라 스펙 먼저 | 사용자 요청 top-3. 제일 큼 |
| 6 | `feat/held-render` 📋 | 드래그 중(held) 렌더 상태 정리 | 작고 안전 |
| 7 | `feat/multimonitor` 📋 | 배회·바닥 계산 전체 모니터 기준 (3모니터) | 멀티모니터 실사용 |
| 8 | `feat/auto-run-state` 📋 | 오토/plan 전용 상태/애니 | 상태 표현 확장 |
| 9 | `feat/walk-polish` 📋 | 걷기 사이클 자연스럽게 (좌우반전 텍스트 버그는 이미 master서 픽스됨) | 아트, 후순위 |
