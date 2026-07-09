# claude-pet TODO

> 프로토타입 단계. 아래는 알려진 버그 + 추가할 기능.

## 🐞 알려진 버그
- [ ] **우클릭 메뉴 정상 작동 안 함** — 메뉴는 뜨는데 항목(이리와/조용히/종료) 동작이 불안정.
      (원인 추정: Tool 윈도우 + XWayland에서 `QMenu.exec` 포커스/좌표 문제일 수 있음)
- [ ] **좌클릭→Konsole**: KWin 스크립트 배관은 검증됨(konsole 1개 활성화 확인)이나,
      실제 펫 좌클릭 end-to-end는 미확인. 여러 Konsole/여러 세션일 때 "올바른" 창을
      고르는 로직 없음(그냥 첫 konsole). 알림 온 세션의 창을 특정해야 함.
- [ ] `_activate_claude`가 클릭마다 KWin 스크립트를 새로 load → 스크립트 누적 가능.
      고정 이름으로 load/unload하거나 stop 확실히.
- [ ] 드래그 던지기 물리 미검증(속도 계산·바운스 튜닝 필요할 수 있음).
- [ ] 멀티모니터: 배회/바닥(floor) 계산이 primary 스크린 기준만. 3모니터 환경 대응 필요.
- [ ] 드래그 중(held) 렌더 상태가 어정쩡할 수 있음.

## 🎯 상태 매핑 전면 재설계 — ✅ 완료 (state_engine.py)
> 설계: `docs/superpowers/specs/2026-07-09-hook-state-policy-design.md`
> 계획: `docs/superpowers/plans/2026-07-09-hook-state-policy.md`
- [x] **훅/이벤트 인벤토리 → 상태 매핑 설계**: 순수 `state_engine.py`로 확정.
      tool_name별(편집/탐색/웹·전화/서브에이전트/스킬) working 세분화, 우선순위,
      디바운스(0.8s), idle→sleeping 타임아웃(60s) 정책 구현 + 유닛테스트.
- [x] **thinking=전구 어색함** — 전구 버리고 "골똘히 고민" 포즈(`ponder`)로 교체.
- [x] **celebrate 후 안정 안 됨** — Stop이 매 턴 발생하는 게 원인이었음. 이제
      Stop→포커스면 idle, 백그라운드면 celebrate 1.6s 후 idle로 감쇠. 전구/재진입 해결.

### ⚠️ 남은 이슈 (celebrate 관련)
- [ ] **포커스 판정이 이 머신에서 미작동** — `kdotool` 미설치라 `focus.terminal_focused()`가
      항상 True(보수적) → **celebrate가 절대 안 뜸**. "안 볼 때 완료 알림"을 켜려면
      `kdotool` 설치하거나 KWin 스크립트로 활성창 resourceClass를 읽어오는 fallback 구현 필요.
- [ ] **호스트 앱 하드코딩 = konsole 전용** — `focus.py`의 `TERMINAL_CLASSES=("konsole",)`와
      `pet.py._activate_claude`가 konsole 창만 찾음. Claude Code를 VS Code 통합터미널이나
      IntelliJ 터미널에서 돌리면 (1) 포커스 판정 오류로 celebrate 오발동, (2) 좌클릭해도
      IDE가 안 뜸. **해법**: `claude-pet-hook`이 프로세스 환경변수로 호스트를 감지해
      (Konsole=`KONSOLE_VERSION`, VS Code=`TERM_PROGRAM=vscode`/`VSCODE_PID`,
      JetBrains=`TERMINAL_EMULATOR=JetBrains-JediTerm`) 힌트를 펫에 전달 → 펫이 해당
      호스트 창 클래스(code / jetbrains-* / konsole ...)로 포커스·활성화를 맞춤.
      포커스 기능 실제로 켤 때 같이 설계. (플랫폼 이식과도 연결)

## ✨ 추가할 반응/기능
- [ ] **오토 진행 중 반응** — auto/plan 진행 등 "혼자 쭉 작업"할 때의 전용 상태/애니.
- [x] **사용자 의견 묻는 순간 반응** — `Notification{permission_prompt}`→attention,
      `idle_prompt`→sleeping으로 구분 완료. (plan 승인/AskUserQuestion 세분화는 여지 남음)
- [ ] **말풍선에 실제 텍스트** — 지금은 `...`만. 상태별 짧은 대사 한 글자씩 타이핑
      (예: "고민중...", "이거 맞아?", "다 됐다!").
- [ ] 완료(celebrate)→대기 전환 타이밍/연출 다듬기.
- [x] 에러 상태 실제 트리거 연결 — `StopFailure` 훅 → `error` 상태로 연결 완료.

## 🎨 아트/폴리시
- [ ] 걷기 사이클·방향전환(좌우 반전) 자연스럽게.
- [ ] **새 상태 아트 튜닝** — work_search/work_web 등 새 prop 아이콘이 작은 픽셀
      스케일에서 다소 밋밋. `python3 src/creature.py`로 스프라이트시트 보며 손보기.
- [ ] 진짜 도트 스프라이트 or GIF override(`assets/<state>.gif`) 렌더 지원(현재 미구현).
- [ ] 창 위 올라타기(window perching) — 다른 창 지오메트리 필요, Wayland 난이도 높음(v2).

## 🧰 배포/운영
- [ ] GitHub 공개 전 최종 점검(README 경로, 라이선스 홀더 이름).
- [ ] 설치 스크립트/의존성(PyQt6) 자동 체크.
- [ ] 여러 데스크톱 환경(비-KDE, X11 순정) 폴백 동작 확인.

---
_현재 검증된 것_: state_engine 정책 로직(유닛테스트 22개), 12상태 렌더(오프스크린),
훅 페이로드 전달, 데스크톱 상주·배회·좌클릭 KWin 배관.
_미검증(사람 확인 필요)_: 실 세션 GUI 반응 end-to-end, 포커스-게이트 celebrate(kdotool 필요),
드래그 던지기, 우클릭 동작.
