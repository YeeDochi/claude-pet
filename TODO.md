# claude-pet TODO

> 프로토타입. 아래는 완료/남은 작업. 리뷰 대기·머지 이력은 `FEATURES_FOR_REVIEW.md`.

## ✅ 완료 (2026-07-09~10)

**상태/반응 (state_engine)**
- 훅→상태 정책 전면 재설계 (`src/state_engine.py`, 순수·유닛테스트). tool_name별 working
  세분화(편집/탐색/웹·전화/서브에이전트/스킬), 우선순위, 디바운스 0.8s, idle→sleeping 60s,
  work/thinking liveness 타임아웃(ESC 중단 대비).
- thinking=전구 → "골똘히 고민" 포즈. celebrate = Stop+비포커스일 때만(매턴 방방 해결).
- 에러 상태 `StopFailure`→`error` 연결. 권한요청/유휴 `Notification` 구분(attention/sleeping).
- 상태별 **타이핑 말풍선** (고민중…/이거 맞아?/다 됐다!/으악!).

**세션/실행 (session-bound)**
- 세션당 펫 1마리. `SessionStart` 훅이 세션 안에서 detached 실행 → **호스트 자동 감지**
  (VS Code/JetBrains/Konsole), 세션별 소켓, `SessionEnd` 종료(취소가능), 시작 위치 분산.
- 호스트 창 기준 좌클릭 활성화 + 포커스 판정(`focus.py`, xprop/kdotool). SIGTERM 클린업.
- `/claude-pet` 스킬 — 기본 **현재 세션에 attach** + `standalone` 옵션.

**상호작용/물리/창**
- 드래그-던지기 **물리** (`src/physics.py`): 중력·공기저항·벽/바닥/천장 반발·속도상한. 모든
  상태에서 중력 적용(공중이면 낙하).
- **창 올라타기/담기** (`src/windows.py`, KDE 전용·게이팅): KWin+DBus 지오메트리 피드(Wayland
  창까지 봄). 자동등정 없음(착지/드롭으로만), minimized 제외, 발 정렬, sticky(전 데스크톱).
- **held**(잡히면 웃으며 대롱), **falling**(떨어지면 쭉) 애니.
- 좌우반전 시 몸만 반전(텍스트/말풍선 정상). 트레이 아이콘(상태 반영) + 작업표시줄 숨김.

## 🐞 남은 버그 / 다듬기
- [ ] **우클릭 메뉴 동작 불안정** — 여전히 미검증. (트레이 우클릭 메뉴는 대안으로 있음)
- [ ] `_activate_claude` 일회성 KWin 스크립트 — 로드/stop만, unload 안 함(누적 경미). geom 피드는
      고정 이름 unload로 해결됨.
- [ ] perching 리뷰 이월 마이너: 작은 창에 펫이 살짝 삐져나옴, windowList 스택순서 비보장,
      담긴 창이 다른 데스크톱일 때 처리.
- [ ] session-bound 이월 마이너: SIGKILL(강제종료) 시 orphan 가능(리퍼 없음), 동시 SessionStart
      TOCTOU 이중실행(이론상).

## 📋 다음 계획 (미착수)
- [x] **멀티모니터** — 배회/바닥 계산 전체 모니터 기준 (3모니터). (2026-07-10 완료, `b08c46e`)
- [ ] **모션 강제 실행 커맨드** `/claude-pet <motion>` — jump/wave/sing/juggle/float +
      기존 상태 노출. 스펙: `docs/superpowers/specs/2026-07-10-pet-motion-command-design.md`. (구현 예정)
- [ ] **이벤트→모션 매핑 커스텀** — `EVENT_STATE` 매핑을 사용자가 바꿀 수 있게
      (설정/커맨드로 훅 이벤트에 원하는 모션 지정). 모션 커맨드 이후 착수.
- [ ] **오토 진행 중 전용 상태/애니** — auto/plan "혼자 쭉 작업".
- [ ] **걷기 폴리시** — 걷기 사이클 자연스럽게.
- [ ] **새 상태 아트 튜닝** — work_search/web 등 prop 아이콘 작은 스케일에서 밋밋.
- [ ] plan 승인/AskUserQuestion 등 "답 기다림" 세분화 (attention보다 잘게).
- [ ] 진짜 도트 스프라이트 / GIF override(`assets/<state>.gif`).

## 🌍 플랫폼 (나중)
- [ ] Mac / Windows 이식 — 코어(state_engine/creature/hook)는 이식가능. 창 활성화·포커스·
      perching만 OS별(Win32/AppleScript). GNOME 제외. perching은 KDE 전용 유지.

## 🧰 배포/운영
- [ ] GitHub 공개 전 점검(README 경로, 라이선스 홀더). 설치 스크립트 의존성 체크(PyQt6, wmctrl).
- [ ] 비-KDE/X11 순정 폴백 동작 확인.

---
_검증된 것_: 유닛테스트 53개 통과. session-bound 펫 2마리 독립 반응·SessionEnd 퇴장(라이브),
perching(창 담기/착지/minimized 제외/sticky, 라이브), 물리(던지기·천장·전상태 중력, 라이브),
말풍선·잡기/낙하 애니(라이브), `/claude-pet` attach, 트레이·하단바숨김, 훅 자동실행.
_미검증_: Mac/Windows, 우클릭 펫메뉴 안정성.
