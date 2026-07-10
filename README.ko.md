# claude-pet 🐾

[English](README.md) | **한국어**

**Claude Code**의 활동에 실시간으로 반응하는, 데스크톱 위에 사는 작은 픽셀 크리처예요.
Claude가 작업하면 타이핑하고, 입력이 필요하면 기다리고, 끝나면 신나하고, 코딩하는 동안
화면을 돌아다녀요. 클릭하면 터미널을 앞으로 가져와요.

아트는 전부 코드로 그려서(이미지 에셋 없음) 자체 완결적이고 오리지널이에요 (아트 CC0).

![states](docs/creature_sheet.png)

## 설치

```bash
git clone https://github.com/YeeDochi/claude-pet ~/claude-pet
pip install PyQt6
~/claude-pet/bin/claude-pet-install     # 훅 + /claude-pet 스킬 (idempotent)
```

이후 새 Claude Code 세션은 펫을 자동으로 띄워요. 이미 돌아가던 세션은 재시작해야 훅을
인식해요 — 아니면 `~/claude-pet/bin/claude-pet`로 지금 하나 띄워도 돼요.

**KDE Plasma**에서 가장 잘 동작하고, 크리처 자체는 PyQt6 되는 곳이면 어디서든 실행돼요
(KDE 전용 창 기능은 그 외 환경에선 곱게 꺼짐). → **[플랫폼 지원](docs/platform.md)**

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
