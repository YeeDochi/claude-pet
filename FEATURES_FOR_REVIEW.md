# claude-pet — 리뷰 대기 기능 목록

> Claude가 TODO 기반으로 자율 개발한 피처들. 각 피처는 전용 브랜치에 있고,
> 네가 "이 피처 보자" 하면 같이 훑고 `main`(현재 `master`)에 머지한다.
> ✅ = 브랜치에서 완성·테스트 통과, 리뷰 대기 | 🚧 = 작업 중 | 📋 = 계획(아직 안 만듦)

## 리뷰 대기 (완성됨)

### ✅ `feat/session-bound-pets` — 세션당 펫 재설계
- **브랜치**: `feat/session-bound-pets` (커밋 6a6d023→1673728, master 기준 5커밋)
- **테스트**: 38/38 통과. 전체-브랜치 리뷰(opus) 통과 — "리뷰 대기 OK".
- **한 것**:
  - `src/hostinfo.py` 신설 — 호스트 감지(vscode/jetbrains/konsole/unknown) + 세션별 소켓 경로 (훅·펫 공유)
  - `src/focus.py` — `terminal_focused(classes)` 호스트-인식 + `xprop`/kdotool로 활성창 읽기 (이 머신에서도 포커스 판정 가능해짐)
  - `bin/claude-pet-hook` — 세션별 소켓, `SessionStart` 시 그 세션 펫을 detached 실행(중복실행 가드), exit-0 불변식 유지
  - `src/pet.py` — `--session/--host` 인자, 세션별 소켓, 호스트 창으로 activate/focus, `SessionEnd`(취소가능) 종료, 시작 위치 분산, 세션별 창제목
- **리뷰가 검증함**: launch race·stale socket 올바르게 처리, 훅 non-blocking, celebrate 안전 축소.
- **직접 봐야 할 것 (리뷰 시)**: 세션 2개(Konsole 1 + VS Code 1) 띄워서 펫 2마리 각자 반응 / 각 좌클릭이 제 호스트 창 띄우는지 / SessionEnd 시 해당 펫만 사라지는지.
- **이월된 마이너**(머지 전 선택): SIGKILL로 죽은 세션은 SessionEnd 안 와서 펫 orphan 잔존(리퍼 없음); 동시 SessionStart TOCTOU 이중실행(이론상); 훅 심볼릭링크 경로. → 후속 `/claude-pet` 정지 스킬로 커버 가능.
- **스펙 편차**(무해): 계획의 `bin/claude-pet-session` 대신 기존 `bin/claude-pet --session/--host` 재사용.

## 계획 — Claude 추천 우선순위

| 우선 | 브랜치 | 내용 | 왜 추천 |
|---|---|---|---|
| 1 | `feat/session-bound-pets` ✅ | **완성 — 위 "리뷰 대기" 참고.** | — |
| 2 | `feat/bubble-text` 🚧 | 말풍선에 상태별 실제 텍스트("고민중...", "이거 맞아?", "다 됐다!") 한 글자씩 타이핑 | 체감 즐거움 큼, creature.py 내 자기완결 |
| 3 | `feat/held-render` | 드래그 중(held) 렌더 상태 정리 — 들려있을 때 팔다리 버둥/놀란 표정 | 지금 어정쩡한 렌더 개선, 작고 안전 |
| 4 | `feat/multimonitor` | 배회·바닥 계산을 전체 모니터 기준으로 (3모니터 대응) | 멀티모니터 실사용, 명확히 테스트 가능 |
| 5 | `feat/auto-run-state` | 오토/plan 등 "혼자 쭉 작업" 전용 상태/애니 | 상태 표현 확장 |
| 6 | `feat/walk-polish` | 걷기 사이클·좌우 반전 자연스럽게 (아트) | 아트라 네 눈 필요 → 후순위 |
| — | `/claude-pet` 스킬 | 세션 펫 수동 on/off 스킬 (session-bound의 follow-up) | v1 후 |
