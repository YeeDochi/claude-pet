# 사용법 & 인터랙션

[← README](../README.ko.md) · [English](usage.md) | **한국어**

## 동작 원리

```
Claude Code ──훅──▶ claudlet-hook ──루프백 TCP──▶ 펫 (PyQt6 창)
```

- **`src/claudlet/pet.py`** — 펫: 테두리 없고 반투명한 항상-위 창. Linux에선 네이티브
  Wayland가 클라이언트의 자기 창 위치 지정을 막아서 XWayland(`QT_QPA_PLATFORM=xcb`)로
  실행하고, macOS/Windows에선 네이티브 Qt 플랫폼을 써요.
- **`src/claudlet/creature.py`** — 크리처 렌더러 (순수 `QPainter`, 상태 기반).
- **`bin/claudlet-hook`** — Claude Code 훅 이벤트를 세션별 루프백 TCP 소켓
  (포트는 `$XDG_RUNTIME_DIR/claudlet-<세션>.port`에 기록 — 기본 Windows Python
  빌드엔 유닉스 도메인 소켓이 없어서, 코드 경로를 하나로 유지하려고 전부 TCP를 써요)으로
  펫에 전달하고, `SessionStart` 때 펫을 띄워요. Claude를 절대 막지 않아요.

`bin/*` 도구는 전부 Python이라 Python 되는 곳이면 어디서든 실행돼요.

## 인터랙션

- **드래그** — 집어서 던지면 중력으로 떨어지고 튕겨요. 창 안으로 던지면 내부 벽에 튕기고,
  밖으로 끌면 나와요.
- **좌클릭** — Claude Code 터미널/IDE를 앞으로.
- **펫 위에서 커서를 좌우로 왕복** — 쓰다듬기! 하트가 뿅뿅 뜨고 방긋 웃어요. (잘 땐 안 깨워요.)
- **우클릭 / 트레이** — 메뉴: *커서 따라오기* · *모션* 서브메뉴(점프·손흔들기·노래·저글링·축하) ·
  *주머니 쏙*(화면에 틈을 내고 고개만 빼꼼 — 제자리에 머물며 작업 영역을 안 가려요) ·
  *조용히(음소거)* · *종료*.
- **CLI/스킬 모션** — `/claudlet <모션>` (또는 `bin/claudlet-motion <모션>`):
  `jump`, `wave`, `sing`, `juggle`, `float`, 그리고
  `celebrate` / `thinking` / `sleeping` / `error` / `attention`; `list`, `stop`.

## `/claudlet` 스킬

`claudlet-install`이 이 스킬을 `~/.claude/skills/`에 링크해줘요. 아무 세션에서
`/claudlet`(또는 "펫 띄워")로 원할 때 펫을 띄워요 — 설치 전부터 열려 있던 세션이나 닫힌
펫을 다시 부를 때 유용. 세션별 자동 실행은 훅이 담당해요.

훅만 설치했다면 수동 링크:

```bash
ln -s ~/claudlet/skills/claudlet ~/.claude/skills/claudlet
```

## 자동 시작

로그인 시 독립 펫이 실행되도록 데스크톱 엔트리 복사:

```bash
cp ~/claudlet/packaging/claudlet.desktop ~/.config/autostart/
```

끄려면 그 파일 삭제.

## 제거

```bash
claudlet-uninstall          # 펫 종료 + 훅/스킬 링크 제거 + 포트파일 정리
claudlet-uninstall --purge  # 위 전부 + ~/.config/claudlet 삭제
```

`claudlet-uninstall`은 실행 중인 펫을 종료하고, `settings.json`의 훅을 제거하고,
`/claudlet` 스킬 링크를 풀고, 남은 포트파일을 정리해요. `--purge`를 주면 설정
디렉터리까지 지워요. 패키지 본체는 지우지 **않고** 지우는 명령만 안내해요
(`pipx uninstall claudlet` 또는 `pip uninstall claudlet`).
`claudlet-install --remove`도 같은 동작이에요.

소스 체크아웃이면 shim 사용: `~/claudlet/bin/claudlet-uninstall`
(자동시작을 켰다면 `rm ~/.config/autostart/claudlet.desktop`, 체크아웃 폴더까지
지우려면 `rm -rf ~/claudlet`).
