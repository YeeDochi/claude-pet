# 플랫폼 지원

[← README](../README.ko.md) · [English](platform.md) | **한국어**

반응 코어(상태·애니메이션·배회·드래그/던지기·트레이)는 이식 가능해요. 창 통합(올라타기/가림·
클릭-포커스)은 Windows에서도 폴링 기반 Win32 API로 동작하고, KDE 전용으로 남은 건
작업표시줄 숨김뿐이에요. 그 외 미구현 기능은 그냥 꺼져요 — 펫은 여전히 실행돼요.

| 플랫폼 | 실행 | 창 통합 |
|--------|------|---------|
| **KDE Plasma** (Wayland/X11) | ✅ | ✅ 전부 — 올라타기, 가림 클리핑/숨김, 클릭-포커스, 작업표시줄 숨김 |
| 기타 Linux (GNOME 등) | ✅ (XWayland) | ✖ KDE 전용 부분 no-op (배회/드래그/상태/트레이는 동작) |
| **Windows** | ✅ | ✅ 올라타기, 가림 클리핑/숨김, 클릭-포커스(`SetForegroundWindow`, 폴링 기반 `ctypes`/Win32); ✖ 작업표시줄 숨김 미구현 |
| **macOS** | 🅱️ 실행될 것 (네이티브 Qt) | ⚠️ `osascript` 기반 클릭-포커스(best-effort), 올라타기/가림은 미구현 |

CLI 도구(`bin/*`)는 전부 **Python** — bash 없음 — 이라 Python 되는 곳이면 어디서든 실행돼요.
KDE와 Windows는 실제로 테스트했어요. GNOME은 창 통합 범위 밖이고, macOS는 best-effort로
실기 미검증이에요. 창 통합이 미구현인 곳에선 바탕화면 바닥으로 폴백하고 해당 기능은 꺼져요.

## 요구사항

- Python 3 + PyQt6 — `pip install PyQt6`
- 전체 기능엔 **KDE Plasma**: `qdbus6`(창 통합/클릭-포커스), `wmctrl`(선택, 작업표시줄에서
  펫 숨김). Wayland면 XWayland.
- **Windows**: 추가 요구사항 없음 — 창 통합은 `src/windows_win32.py`에서 표준 라이브러리
  `ctypes`로 `user32`/`dwmapi`/`kernel32`를 직접 호출해요.

## 각자 OS에서 테스트 도와주세요

macOS는 best-effort고 **실기 미검증**이에요 — 리포트 환영. 돌려보면 확인 후 이슈로:

- **실행되나요?** `bin/claude-pet`로 크리처가 뜨고, 배회하고, 드래그/던지기가 되나요.
- **반응하나요?** `claude-pet-install` 후 Claude Code를 쓰면 상태가 바뀌나요 (작업/생각/완료).
- **트레이** 아이콘과 메뉴가 뜨나요.
- **macOS 전용:** 좌클릭이 터미널/IDE(Terminal / iTerm / VS Code)를 앞으로 가져오나요
  (`osascript`). 최전면 앱 감지가 "완료" 포즈를 게이팅하나요.
- 위 표 대비 뭐가 안 되는지 적어주세요 (작업표시줄 숨김은 설계상 KDE 전용).
