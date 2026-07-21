# Usage & interaction

[← README](../README.md) · **English** | [한국어](usage.ko.md)

## How it works

```
Claude Code ──hook──▶ claudlet-hook ──loopback TCP──▶ pet (PyQt6 window)
```

- **`src/claudlet/pet.py`** — the pet: a frameless, translucent, always-on-top
  window. On Linux it runs under XWayland (`QT_QPA_PLATFORM=xcb`) so it can
  position itself, which native Wayland forbids; on macOS/Windows it uses the
  native Qt platform.
- **`src/claudlet/creature.py`** — the creature renderer (pure `QPainter`, state-driven).
- **`bin/claudlet-hook`** — forwards each Claude Code hook event to the pet over
  a per-session loopback TCP socket (port published in
  `$XDG_RUNTIME_DIR/claudlet-<session>.port`; stock Windows Python builds have
  no unix domain sockets, so TCP is used everywhere for one code path) and
  launches a pet on `SessionStart`. Never blocks Claude.

All `bin/*` tools are Python, so they run wherever Python does.

## Interaction

- **Drag** to pick it up and throw it — it falls with gravity and bounces. Fling it
  inside a window and it bounces off the interior walls; drag it out to leave.
- **Left-click** — bring the Claude Code terminal/IDE to the front.
- **Hover back-and-forth over it** to pet it — hearts pop and it grins. (Not while
  it's asleep.)
- **Right-click / tray** — menu: *커서 따라오기* (follow the cursor) · *모션* submenu
  (jump / wave / sing / juggle / celebrate) · *주머니 쏙* (pocket — tucks into a slit
  in the screen and peeks its head out, staying put and not covering your work) ·
  *quiet (mute)* · *quit*.
- **Motions from the CLI/skill** — `/claudlet <motion>` (or
  `bin/claudlet-motion <motion>`): `jump`, `wave`, `sing`, `juggle`, `float`, plus
  `celebrate` / `thinking` / `sleeping` / `error` / `attention`; `list`, `stop`.

## The `/claudlet` skill

`claudlet-install` links this skill into `~/.claude/skills/` for you. In any
session, `/claudlet` (or "펫 띄워") launches a pet on demand — handy for a session
that predates the install, or to bring a closed pet back. Per-session auto-launch
still comes from the hooks.

Manual link, if you installed hooks only:

```bash
ln -s ~/claudlet/skills/claudlet ~/.claude/skills/claudlet
```

## Autostart

Copy the desktop entry so a standalone pet launches at login:

```bash
cp ~/claudlet/packaging/claudlet.desktop ~/.config/autostart/
```

Remove that file to disable.

## Uninstall

```bash
claudlet-uninstall          # stop pets, remove hooks + skill link, clean up
claudlet-uninstall --purge  # the above + delete ~/.config/claudlet
```

`claudlet-uninstall` stops any running pets, removes the hooks from
`settings.json`, unlinks the `/claudlet` skill, and clears stray port files.
`--purge` additionally deletes your config. It does **not** remove the package
itself — it prints the command to do that (`pipx uninstall claudlet` or
`pip uninstall claudlet`). `claudlet-install --remove` is a synonym.

From a source checkout use the shim: `~/claudlet/bin/claudlet-uninstall`
(add `rm ~/.config/autostart/claudlet.desktop` if you enabled autostart, and
`rm -rf ~/claudlet` to drop the checkout).
