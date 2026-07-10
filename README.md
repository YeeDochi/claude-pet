# claude-pet 🐾

**English** | [한국어](README.ko.md)

A tiny pixel creature that lives on your desktop and reacts to **Claude Code** in
real time — it types while Claude works, waits when Claude needs you, celebrates
when it's done, and roams around while you code. Click it to bring the terminal
back to the front.

Drawn entirely in code — no image assets — so it's self-contained and original
(CC0 artwork).

![states](docs/creature_sheet.en.png)

## Install

```bash
git clone https://github.com/YeeDochi/claude-pet ~/claude-pet
pip install PyQt6
~/claude-pet/bin/claude-pet-install     # hooks + the /claude-pet skill (idempotent)
```

New Claude Code sessions then auto-spawn a pet. Restart any already-running session
to pick up the hooks — or launch one now with `~/claude-pet/bin/claude-pet`.

Best on **KDE Plasma**; the creature runs anywhere PyQt6 does, with the KDE-only
window tricks switching off gracefully. See **[Platform support](docs/platform.md)**.

## What it shows

The creature's pose tracks what Claude is doing — editing, reading, calling MCP,
spawning subagents, thinking, waiting on your input, celebrating (see the sheet
above). In **auto / bypass mode** it puts on a VR visor and cruises, with a per-tool
variant for each activity. It also **perches on and rides your windows** — walking
along the top or living inside — and clips/hides when the window it's on is covered
or minimized.

## Docs

- **[Usage & interaction](docs/usage.md)** — drag & throw, click-to-focus, tray menu, motions, autostart, uninstall
- **[Configuration](docs/configuration.md)** — remap which animation shows for which Claude Code activity
- **[Platform support](docs/platform.md)** — support matrix + how to test on your OS

## License

Code: **MIT** (see [LICENSE](LICENSE)). Creature artwork: **CC0** (see [NOTICE](NOTICE)).
