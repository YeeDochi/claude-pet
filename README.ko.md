# claude-pet 🐾

[English](README.md) | **한국어**

**Claude Code**의 활동에 실시간으로 반응하는, 데스크톱 위에 사는 작은 픽셀 크리처예요.
Claude가 작업하면 타이핑하고, 입력이 필요하면 기다리고, 끝나면 신나하고, 코딩하는 동안
화면을 돌아다녀요. 클릭하면 터미널을 앞으로 가져와요.

아트는 전부 코드로 그려서(이미지 에셋 없음) 자체 완결적이고 오리지널이에요 (아트 CC0).

![states](docs/creature_sheet.png)

## 실제 사용 모습

실제 데스크톱 화면 녹화 — 펫들이 터미널 타이틀바에 올라타고, 바탕화면을 돌아다니고,
작업 사이엔 잠들고(💤), 화면에 뭐가 떠 있든 그 위를 타고 다녀요.

![바탕화면 위의 claude-pet](docs/screenshot.png)

![터미널에 올라타 로밍하는 펫들](docs/demo-1.gif)

*터미널 위에 올라타고, 돌아다니고, 작업 사이엔 꾸벅꾸벅.*


![펫을 드래그하는 모습](docs/demo-2.gif)

*집어서 끌고 다닐 수 있고, 나머지는 계속 로밍·낮잠.*

![배경 위를 돌아다니는 펫들](docs/demo-3.gif)

*화면에 뭐가 떠 있든 그 위를 돌아다녀요.*

## 설치

한 줄 — 클론(또는 업데이트)·의존성 설치(PyQt6, macOS면 pyobjc까지)·훅+스킬 등록까지 한 번에 (Python·git 필요). 업데이트도 이 한 줄 다시 실행:

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/YeeDochi/claude-pet/master/install.py | python3 -
```
```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/YeeDochi/claude-pet/master/install.py | python -
```

<details><summary>직접 단계별로</summary>

```bash
git clone https://github.com/YeeDochi/claude-pet ~/claude-pet
~/claude-pet/bin/claude-pet-install     # 의존성(PyQt6, macOS면 Quartz) + 훅 + /claude-pet 스킬 (idempotent)
```
</details>

이후 새 Claude Code 세션은 펫을 자동으로 띄워요. 이미 돌아가던 세션은 재시작해야 훅을
인식해요 — 아니면 `~/claude-pet/bin/claude-pet`로 지금 하나 띄워도 돼요.

**KDE Plasma**에서 가장 잘 동작해요. 창 위에 올라타기/타고 다니기는 **Windows**(Win32)와
**macOS**(실험적 — `pyobjc-framework-Quartz` 필요, 인스톨러가 자동 설치하고 창 좌표는
런타임에 자동 보정)에서도 되고, 그 외 환경에선 창 기능만 곱게 꺼지고 펫은 그냥 돌아다녀요.
→ **[플랫폼 지원](docs/platform.md)**

## 뭘 보여주나요

크리처의 포즈가 Claude가 지금 뭘 하는지를 따라가요 — 편집·읽기·MCP 호출·서브에이전트·생각·
입력 대기·완료(위 시트 참고). **auto/bypass 모드**에선 VR 바이저를 끼고 순항하고, 작업 종류별로
변형이 있어요. 또 **창에 올라타고 함께 다녀요** — 상단을 걷거나 안에서 지내고, 올라탄 창이
가려지거나 최소화되면 같이 잘리거나 숨어요.

## 문서

- **[사용법 & 인터랙션](docs/usage.ko.md)** — 드래그/던지기, 클릭-포커스, 트레이 메뉴, 모션, 자동시작, 제거
- **[설정](docs/configuration.ko.md)** — 어떤 활동에 어떤 애니를 보일지 재매핑
- **[플랫폼 지원](docs/platform.ko.md)** — 지원 매트릭스 + 각 OS 테스트 방법

## 라이선스

코드: **MIT** ([LICENSE](LICENSE)). 크리처 아트: **CC0** ([NOTICE](NOTICE)).
