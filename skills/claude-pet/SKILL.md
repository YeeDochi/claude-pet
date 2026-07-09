---
name: claude-pet
description: Launch the claude-pet desktop buddy — a pixel creature that roams your screen and reacts to Claude Code. Use when the user types "/claude-pet" or says "펫 띄워", "펫 켜", "start the pet", "run claude-pet", or otherwise wants the desktop pet running.
---

# claude-pet — launch the desktop buddy

When invoked, launch **one** claude-pet instance, detached so it keeps running
after this shell/session ends. The pet is a frameless, roaming pixel creature
that reacts to Claude Code hook events.

## Steps

1. **Locate the launcher.** It is normally at `~/claude-pet/bin/claude-pet`.
   If that file does not exist, ask the user where they cloned claude-pet and
   use that path.

2. **Launch it detached** (so it outlives the current shell):
   ```bash
   setsid ~/claude-pet/bin/claude-pet >/dev/null 2>&1 < /dev/null & disown
   ```

3. **Confirm it started:**
   ```bash
   pgrep -f "src/pet.py" >/dev/null && echo "claude-pet running 🐾" || echo "failed — check ~/claude-pet and that PyQt6 is installed"
   ```

## Notes

- This skill only **launches** a pet. It does not install hooks or edit
  settings. The per-session auto-launch + reactions are set up separately via
  `~/claude-pet/bin/claude-pet-install-hooks`.
- If a pet is already running this just adds another one; that's fine (each is
  independent). To stop one, right-click it → 종료.
