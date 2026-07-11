# claude-pet 🐾

**English** | [한국어](README.ko.md)

A tiny pixel creature that lives on your desktop and reacts to **Claude Code** in
real time — it types while Claude works, waits when Claude needs you, celebrates
when it's done, and roams around while you code. Click it to bring the terminal
back to the front.

Drawn entirely in code — no image assets — so it's self-contained and original
(CC0 artwork).

![states](docs/creature_sheet.en.png)

## See it in action

Real desktop capture. Pets perch on the terminal titlebar, roam the desktop, doze
off (💤) between tasks, and clamber over whatever else is on screen.

![claude-pet on the desktop](docs/screenshot.png)

![Pets perch on the terminal and roam the desktop](docs/demo-1.gif)
*Perching on the terminal, roaming, and dozing between tasks.*

![Dragging a pet while the others nap](docs/demo-2.gif)
*Grab and drag them around; the rest keep roaming and napping.*

![Pets roaming over the wallpaper](docs/demo-3.gif)
*They wander over whatever else is on your screen.*

## Install

One line — clones (or updates), installs dependencies (PyQt6, plus pyobjc on macOS), and registers the hooks + skill (needs Python & git). Re-run it anytime to update:

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/YeeDochi/claude-pet/master/install.py | python3 -
```
```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/YeeDochi/claude-pet/master/install.py | python -
```

<details><summary>Prefer to do it by hand</summary>

```bash
git clone https://github.com/YeeDochi/claude-pet ~/claude-pet
~/claude-pet/bin/claude-pet-install     # installs deps (PyQt6, +Quartz on macOS) + hooks + /claude-pet skill (idempotent)
```
</details>

New Claude Code sessions then auto-spawn a pet. Restart any already-running session
to pick up the hooks — or launch one now with `~/claude-pet/bin/claude-pet`.

Best on **KDE Plasma**. Perching on and riding windows also works on **Windows**
(Win32) and **macOS** (experimental — needs `pyobjc-framework-Quartz`, which the
installer adds automatically; the pet self-calibrates window coordinates at
runtime). Elsewhere the window tricks switch off gracefully and the pet just
roams. See **[Platform support](docs/platform.md)**.

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
