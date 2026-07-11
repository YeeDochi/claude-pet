# claudlet 🐾

**English** | [한국어](README.ko.md)

[![PyPI](https://img.shields.io/pypi/v/claudlet)](https://pypi.org/project/claudlet/)

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

![claudlet on the desktop](docs/screenshot.png)

![Pets perch on the terminal and roam the desktop](docs/demo-1.gif)
*Perching on the terminal, roaming, and dozing between tasks.*

![Dragging a pet while the others nap](docs/demo-2.gif)
*Grab and drag them around; the rest keep roaming and napping.*

![Pets roaming over the wallpaper](docs/demo-3.gif)
*They wander over whatever else is on your screen.*

## Install

Install with [pipx](https://pipx.pypa.io) (an isolated app install — pulls the
deps, incl. `pyobjc-framework-Quartz` on macOS, and puts the `claudlet*`
commands on your PATH), then wire it into Claude Code:

```bash
pipx install claudlet
claudlet-install      # registers the hooks + /claudlet skill (idempotent)
```

Update later with `pipx upgrade claudlet && claudlet-install`, or from inside
Claude Code with `/claudlet update`. To install an unreleased revision, point
pipx at the repo instead: `pipx install "git+https://github.com/YeeDochi/Claudlet@master"`.

Remove it with `claudlet-uninstall` (stops pets, unregisters the hooks + skill;
add `--purge` to also delete your config), then `pipx uninstall claudlet`.

<details><summary>Without pipx — one-line source install</summary>

Clones (or updates) to `~/claudlet`, installs deps, registers hooks + skill:
```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/YeeDochi/Claudlet/master/install.py | python3 -
```
```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/YeeDochi/Claudlet/master/install.py | python -
```
</details>

New Claude Code sessions then auto-spawn a pet. Restart any already-running session
to pick up the hooks — or launch one now with `claudlet`.

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
- **[Configuration](docs/configuration.md)** — remap which animation shows for which Claude Code activity (run `claudlet-config` or `/claudlet config` to locate & inspect it)
- **[Platform support](docs/platform.md)** — support matrix + how to test on your OS

## License

Code: **MIT** (see [LICENSE](LICENSE)). Creature artwork: **CC0** (see [NOTICE](NOTICE)).
