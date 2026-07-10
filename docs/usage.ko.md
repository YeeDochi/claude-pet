# 사용법 & 인터랙션

[← README](../README.ko.md) · [English](usage.md) | **한국어**

## 동작 원리

```
Claude Code ──훅──▶ claude-pet-hook ──루프백 TCP──▶ 펫 (PyQt6 창)
```

- **`src/pet.py`** — 펫: 테두리 없고 반투명한 항상-위 창. Linux에선 네이티브 Wayland가
  클라이언트의 자기 창 위치 지정을 막아서 XWayland(`QT_QPA_PLATFORM=xcb`)로 실행하고,
  macOS/Windows에선 네이티브 Qt 플랫폼을 써요.
- **`src/creature.py`** — 크리처 렌더러 (순수 `QPainter`, 상태 기반).
- **`bin/claude-pet-hook`** — Claude Code 훅 이벤트를 세션별 루프백 TCP 소켓
  (포트는 `$XDG_RUNTIME_DIR/claude-pet-<세션>.port`에 기록 — 기본 Windows Python
  빌드엔 유닉스 도메인 소켓이 없어서, 코드 경로를 하나로 유지하려고 전부 TCP를 써요)으로
  펫에 전달하고, `SessionStart` 때 펫을 띄워요. Claude를 절대 막지 않아요.

`bin/*` 도구는 전부 Python이라 Python 되는 곳이면 어디서든 실행돼요.

## 인터랙션

- **드래그** — 집어서 던지면 중력으로 떨어지고 튕겨요. 창 안으로 던지면 내부 벽에 튕기고,
  밖으로 끌면 나와요.
- **좌클릭** — Claude Code 터미널/IDE를 앞으로.
- **우클릭 / 트레이** — 메뉴: *커서 따라오기* · *모션* 서브메뉴(점프·손흔들기·노래·저글링·축하) ·
  *둥둥 띄우기*(무중력 토글) · *조용히(음소거)* · *종료*.
- **CLI/스킬 모션** — `/claude-pet <모션>` (또는 `bin/claude-pet-motion <모션>`):
  `jump`, `wave`, `sing`, `juggle`, `float`, 그리고
  `celebrate` / `thinking` / `sleeping` / `error` / `attention`; `list`, `stop`.

## `/claude-pet` 스킬

`claude-pet-install`이 이 스킬을 `~/.claude/skills/`에 링크해줘요. 아무 세션에서
`/claude-pet`(또는 "펫 띄워")로 원할 때 펫을 띄워요 — 설치 전부터 열려 있던 세션이나 닫힌
펫을 다시 부를 때 유용. 세션별 자동 실행은 훅이 담당해요.

훅만 설치했다면 수동 링크:

```bash
ln -s ~/claude-pet/skills/claude-pet ~/.claude/skills/claude-pet
```

## 자동 시작

로그인 시 독립 펫이 실행되도록 데스크톱 엔트리 복사:

```bash
cp ~/claude-pet/packaging/claude-pet.desktop ~/.config/autostart/
```

끄려면 그 파일 삭제.

## 제거

```bash
~/claude-pet/bin/claude-pet-install --remove    # 훅 + 스킬 링크 제거
rm ~/.config/autostart/claude-pet.desktop       # 자동시작 켰다면
rm -rf ~/claude-pet
```
