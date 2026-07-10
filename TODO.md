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
- [x] **우클릭 메뉴 동작** — 새 모션/float 메뉴 라이브 검증됨 (2026-07-10).
- [x] `_activate_claude` 일회성 KWin 스크립트 — 고정 플러그인명 + unload + _cleanup 정리로 누적 제거.
- [x] perching 마이너: 작은 창 삐져나옴 → 펫보다 작으면 가운데 정렬; windowList 스택순서 →
      `workspace.stackingOrder` 사용; 담긴 창이 다른 데스크톱 → geom 스크립트가 현재 데스크톱만 push.
- [x] session-bound 마이너: SIGKILL orphan → `--claude-pid` 리퍼(부모 죽으면 종료, 라이브 검증);
      동시 SessionStart 이중실행 → 세션별 flock(중복 실행 즉시 종료, 라이브 검증).
- [x] work_search 좌우 뛰기: 앵커 고정으로 로컬 양방향 (화면 가로지르기/한쪽 드리프트 제거).

## 📋 다음 계획 (미착수)
- [x] **멀티모니터** — 배회/바닥 계산 전체 모니터 기준 (3모니터). (2026-07-10 완료, `b08c46e`)
- [x] **모션 강제 실행 커맨드** `/claude-pet <motion>` — jump/wave/sing/juggle/float +
      기존 상태 노출. (2026-07-10 머지 `2b015c6`) + 우클릭/트레이 모션 메뉴, float 토글,
      커서 따라오기(KWin 커서 피드), 창 안 튕기기까지. 73 테스트 통과.
- [x] **이벤트→모션 매핑 커스텀** — `~/.config/claude-pet/config.json`의 `tools`/`events`로
      도구·이벤트→모션 오버라이드. `petconfig.py` 로더(검증), `StateEngine` 인자 주입(순수 유지).
      README 문서화. (2026-07-10)
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
