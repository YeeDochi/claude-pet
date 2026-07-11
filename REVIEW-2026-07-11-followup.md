# claude-pet — `fix/cross-os-review-2026-07-11` 후속 리뷰 & 수정 (2026-07-11)

> `fix/cross-os-review-2026-07-11` (커밋 `016b766`)에 대한 적대적(adversarial) 코드 리뷰와,
> 그중 실제로 고친 3건을 정리한 문서. 이 브랜치 자체가 이미 별도 크로스-OS 리뷰의 산출물이므로,
> 여기서는 "그 리뷰가 놓친 것"만 다룬다.

## 1. 리뷰 방법

`016b766` 하나의 diff(14개 파일, +525/-98)에 대해 6개의 독립 서브에이전트를 병렬로 돌림
(라인 스캔 / 삭제-행위 감사 / 크로스파일 추적 / 재사용·단순화 / 효율·고도 / CLAUDE.md 컨벤션).
후보 발견 ~25건을 중복 제거 후 직접 소스 확인·재현으로 검증하여 **10건**을 확정.

## 2. 확정 파인딩 10건 (심각도순)

| # | 위치 | 요약 | 상태 |
|---|------|------|------|
| 1 | `src/hostinfo.py:108` | `write_session_port()`의 `os.replace()`가 unguarded — Windows에서 리더가 파일을 열고 있으면 `PermissionError`로 막 뜬 펫이 크래시 (이 머신에서 직접 재현) | **수정함** |
| 2 | `src/pet.py:1169` | Windows 클릭포커스 fallback이 `"konsole"`/`host_classes`(KWin 클래스명)를 써서 Windows에서 항상 매칭 실패 (dead code) | **수정함** |
| 3 | `bin/claude-pet-hook:165` | `pet_alive()`의 timeout(살아있지만 바쁨)과 확정된 죽음을 구분 못 해서, 이미 살아있는 펫에 발생한 이벤트를 조용히 drop | **수정함** |
| 4 | `src/pet.py:1260` | `_pid_alive()` Windows 분기: `proc_table()`이 계속 빈 값이면(AV/EDR 정책 등) orphan reaper가 영원히 작동 안 함 | 미수정 (엣지케이스) |
| 5 | `src/hostinfo.py:105` | 원자적 쓰기의 `.tmp` sibling 파일이 크래시/replace 실패 시 청소 안 되고 영구 잔존 | **수정함 (`8677dcf`)** |
| 6 | `src/windows_win32.py:202` | `_to_logical()`이 모니터별 논리 원점 보정 없이 스케일로만 나눔 — mixed-DPI 멀티모니터에서 좌표 부정확 | 미수정 (`docs/platform.md`에 이미 known-limit로 명시됨) |
| 7 | `src/hostinfo.py:126` | `pet_alive()`의 connect+recv 타임아웃이 각각 적용되어 최악 ~0.6s 지연 | **수정함 (`8677dcf`)** |
| 8 | `docs/platform.ko.md` | 새 "Known limits" 섹션이 한국어 카운터파트에 반영 안 됨 (`.ko.md` 짝맞추기 — CLAUDE.md 명문 규칙은 아니고 사실상 관례) | **수정함 (`8677dcf`)** |
| 9 | `bin/claude-pet-install-hooks:39` | POSIX 분기가 `sys.executable` 없이 shebang에만 의존 (의도적 트레이드오프; CLAUDE.md에 "always re-exec" 규칙은 실제로 없음 — grep 확인) | 미수정 (의도적) |
| 10 | `bin/claude-pet-motion:70` | `_read_port()`의 fallback이 `hostinfo.read_port_file()`을 그대로 복붙 | 미수정 (경미, 정리성) |

## 3. 이번에 고친 3건

### ① `write_session_port()` 크래시 (#1)

**증상**: `os.replace(tmp, path)`가 unguarded. Windows에서 다른 프로세스가 `with open(path) as f: ...`로
그 파일을 여는 그 짧은 순간에 replace가 겹치면 `PermissionError`(WinError 5)로 예외가 `Pet.__init__`
밖으로 튀어나가 막 뜬 펫 프로세스가 크래시(stdout/stderr가 DEVNULL로 리다이렉트돼 조용히).

**수정**: `src/hostinfo.py`에 `_replace_retrying(src, dst, attempts=10, delay=0.02)` 추가. 리더는
컨텍스트 매니저로 마이크로초 단위만 파일을 열므로, 짧은 재시도 루프로 경쟁을 해소. 10회 재시도 후에도
실패하면 예외를 그대로 전파(지속적인 문제를 숨기지 않음).

**테스트**: `test_write_session_port_retries_through_transient_replace_failure`,
`test_write_session_port_raises_after_exhausting_retries` (`tests/test_hostinfo.py`).

### ② Windows 클릭포커스 fallback dead code (#2)

**증상**: `_activate_claude_windows()`이 pid로 못 찾으면 `self.host_classes or ["konsole"]`로 폴백하는데,
`host_classes`는 KWin resourceClass용 값(`"code"`, `"konsole"` 등)이라 Windows 실제 창 클래스명과
전혀 안 맞음. `detect_host()`도 cmd.exe/PowerShell/Windows Terminal을 전부 `"unknown"`으로 분류해서
Windows 네이티브 터미널은 처음부터 매칭 대상이 없었음.

**수정 (1차, `96dbf08`)**: `src/hostinfo.py`에 `WIN_CLASSES`/`win_classes(host)` 추가 — Windows Terminal
(`cascadia_hosting_window_class`), 클래식 콘솔(`consolewindowclass`), VS Code(`chrome_widgetwin_1`),
그리고 `"unknown"` 폴백이 위 두 터미널 클래스를 가리킴. `src/pet.py`의 `_activate_claude_windows()`가
`hostinfo.win_classes(self.host)`를 쓰도록 변경.

> **3차 리뷰(§6)에서 정정**: `"vscode" → ["chrome_widgetwin_1"]` 매핑 자체가 새로운 버그였음 —
> 이 클래스는 Discord/Slack/Teams 등 모든 Electron 앱이 공유해서, pid 못 찾은 standalone vscode 펫이
> 엉뚱한 창을 포커스할 위험이 있었음. `vscode` 매핑을 제거하고 `win_classes()`가 그 경우 `[]`를 반환하도록
> 변경(§6-A).

**테스트**: `test_win_classes_unknown_falls_back_to_generic_terminal_classes`,
`test_win_classes_vscode_has_no_safe_win32_guess`, `test_win_classes_unmapped_host_gets_no_fallback`
(`tests/test_hostinfo.py`), `test_activate_claude_windows_fallback_uses_win32_classes`,
`test_activate_claude_windows_no_guess_for_ambiguous_host` (`tests/test_pet_smoke.py`).

### ③ 훅의 이벤트 drop (#3)

**증상**: `bin/claude-pet-hook`의 `launched` 플래그가 "막 launch 시도함"과 "그래서 old 포트로 보내면
안 됨"을 항상 같이 취급. 그런데 `_launch_pet()` 호출은 `pet_alive()`가 `False`이기만 하면 일어나고,
`pet_alive()`는 timeout(=살아있지만 바쁨)도 확정된 죽음과 똑같이 `False`를 반환함. 그 결과 세션 재개 시
펫이 잠깐 바쁘면 그 SessionStart 이벤트가 재시도 없이 그냥 사라짐.

**수정**: `launched` → `launched_fresh`로 바꾸고, **세션에 원래 포트파일이 전혀 없던 경우(진짜 새
세션)에만** send를 스킵하도록 변경. 포트파일이 이미 있던 세션(재개)은 `pet_alive()`가 무엇을 반환하든
항상 전송을 시도 — 최악의 경우도 예전 pre-handshake 동작(항상 best-effort 전송)과 동일한 리스크
수준으로 회귀.

**테스트**: `test_session_start_still_sends_when_resumed_pet_times_out`,
`test_session_start_skips_send_for_brand_new_session`,
`test_session_start_sends_when_pet_confirmed_alive` (`tests/test_hook_payload.py`).

## 4. 테스트 결과

```
python -m pytest -q
173 passed, 2 failed (사전부터 존재하던 무관한 flaky 테스트, 이 수정 전에도 실패 확인함)
```

실패한 2건(`test_pet_alive_false_and_removes_stale_file_on_refused`,
`test_send_removes_stale_port_file`)은 Windows 루프백 소켓의 bind→close→connect 타이밍 특성 때문으로,
이번 수정과 무관 — 수정 전 브랜치에서도 동일하게 실패함(`git stash`로 확인).

## 5. 아직 남은 것 (표 4·6·9·10)

후속 커밋 `8677dcf`에서 #5·#7·#8을 처리함(+ 훅 hot-path의 불필요한 포트파일 읽기 제거,
Windows에서 비결정이던 refused-connect 테스트 2건을 결정화). 남은 항목:
- **#4** `_pid_alive` Windows 분기의 "빈 snapshot → 항상 alive" 로직을 좀 더 보수적으로.
  (엣지케이스: 신뢰할 Windows 생존 API가 없어 안전 기본값으로 둠.)
- **#6** `_to_logical` 혼합-DPI 멀티모니터 — 실기기 보정 필요(문서화된 한계).
- **#9** `install-hooks` POSIX shebang — CLAUDE.md에 상충 규칙이 없어 의도대로 둠.
- **#10** `bin/claude-pet-motion`의 `_read_port` fallback 중복 — hostinfo import 실패 대비
  의도적 방어라 유지.

## 6. 3차 리뷰 — 누적 4개 커밋(016b766/96dbf08/8677dcf/f04a80a)의 상호작용 점검

1·2차 리뷰가 각 커밋을 개별로 봤다면, 3차는 "네 커밋을 합쳤을 때만 보이는 문제"를 노림. 2개의
독립 서브에이전트(전체 diff 크로스체크 / 테스트 실효성 회의적 점검)를 돌려 아래 2건을 확정.

### A. `win_classes("vscode")`의 클래스 충돌 — **버그, 수정함**

**증상**: §3-②에서 추가한 `WIN_CLASSES["vscode"] = ["chrome_widgetwin_1"]`이 문제였음. 이 Win32
클래스는 VS Code만이 아니라 Discord/Slack/Teams/일반 Chrome·Edge 창, 심지어 다른 VS Code 창까지
전부 공유함. `find_window_by_class`는 topmost 첫 매치를 그냥 반환하므로, pid 못 찾은(예: `claude-pid`
없이 뜬 standalone) vscode 펫이 클릭포커스 폴백을 타면 위 앱들 중 아무거나를 엉뚱하게 포커스할 수
있었음. `test_find_window_by_class_matches_substring`는 클래스당 창 하나만 넣고 테스트해서 이 "여러
창이 같은 클래스를 공유하는" 충돌 경로는 커버 안 됨.

**수정**: `WIN_CLASSES`에서 `"vscode"` 항목을 완전히 제거. `win_classes()`가 매핑 없는 호스트엔 이제
`[]`를 반환(이전엔 `"unknown"`의 터미널 클래스로 폴백했는데, 그것도 무관한 창을 잘못 매칭할 수 있어서
동일하게 위험). `find_window_by_class([])`는 자체 가드로 안전하게 `None`을 반환 — "틀리게 추측"보다
"아무것도 안 함"을 선택. `"unknown"`(네이티브 터미널: cmd.exe/PowerShell/Windows Terminal)만 남김 —
이 두 클래스명은 터미널 앱 전용이라 충돌 위험이 낮음.

**테스트**: `test_win_classes_vscode_has_no_safe_win32_guess`, `test_activate_claude_windows_no_guess_for_ambiguous_host`.

### B. `had_port` + `pet_alive()`의 파일삭제 상호작용 — **버그 아님, 문서화되지 않은 한계였음**

**증상**: §3-③의 수정은 "포트파일이 있던 세션은 항상 전송 시도"였는데, 두 에이전트가 독립적으로 같은
경로를 추적: 진짜로 죽은 펫의 경우 `pet_alive()`가 `ConnectionRefusedError`에서 그 포트파일을
**지운다**(원래부터 있던 동작, `016b766`). `had_port`는 그 삭제 *전에* 캡처되므로 `True`로 남고,
`launched_fresh = not had_port = False`가 되어 훅은 "전송 시도" 분기로 빠짐 — 근데 그 시점에 다시
`read_session_port()`를 부르면 방금 지워진 파일이라 `None`이 나오고, `_send(None, ...)`은 즉시
실패해서 결국 이 이벤트는 그대로 drop됨.

**판단**: 이건 회귀가 아님 — "진짜로 죽은 펫"에겐 애초에 보낼 대상이 살아있는 순간이 존재하지 않음
(교체 펫이 아직 리슨을 시작 안 함). `launched_fresh` 플래그를 어떻게 짜도 이 순간엔 배달 불가능.
§3-③ 수정이 실제로 도움이 되는 건 "살아있지만 바쁜" 케이스뿐(그 경우 파일이 안 지워지므로 재전송이
성공함) — 그건 의도대로 동작 확인됨. 다만 이 상호작용이 테스트로 전혀 고정돼 있지 않아서(기존
3개 테스트는 `pet_alive`를 순수 함수 mock으로 대체해 파일삭제 부작용을 안 건드림), 향후 리팩터가
이 순서를 바꿔도 아무 테스트도 안 걸림.

**조치**: 코드 수정 없음(불가피한 한계라 판단). 실제 부작용 있는 `pet_alive`를 그대로 써서 이
end-to-end 동작을 고정하는 테스트만 추가 — `test_session_start_dead_pet_still_drops_this_event`
(`tests/test_hook_payload.py`). 다음 훅 이벤트(예: 곧이어 오는 `UserPromptSubmit`)는 새로 뜬 펫한테
정상 도달하므로 실사용 영향은 "리셋 애니메이션 한 프레임 누락" 정도.

**보너스로 채운 테스트 커버리지 갭**: `pet_alive()`의 "non-refused 에러는 파일 안 지움" 계약이
그 자체로 직접 테스트된 적이 없었음(motion의 `send()`만 있었음) — `test_pet_alive_false_but_keeps_port_file_on_timeout` 추가.

### 결과

```
python -m pytest -q
179 passed
```
