---
name: claude-pet
description: Launch/attach the claude-pet desktop buddy, or trigger a motion on it. "/claude-pet" attaches a pet to the CURRENT session; "/claude-pet standalone" launches an unattached roaming pet; "/claude-pet <motion>" plays a motion (jump/wave/sing/juggle/float/celebrate/thinking/sleeping/error/attention); "/claude-pet list" lists motions; "/claude-pet stop" clears a held motion. Use when the user types "/claude-pet", "펫 띄워", "펫 붙여", "펫 점프", "start the pet".
---

# claude-pet — launch the desktop buddy

A frameless roaming pixel creature. By default this **attaches** a pet to the
**current session** (so it reacts to this session's Claude Code activity). Pass
`standalone` for an unattached one.

## Routing

Look at the argument the user passed after `/claude-pet`:

- a **motion name** (`jump`, `wave`, `sing`, `juggle`, `float`, `celebrate`,
  `thinking`, `sleeping`, `error`, `attention`), or `list`, or `stop`/`clear`
  → run the motion helper (below); do NOT launch a pet.
- `standalone` → the standalone section.
- nothing → the attach section.

### Trigger a motion

Run the helper with the interpreter and a native path, so it works on Windows
git-bash too (a bare `~/...` path or shebang launch doesn't):
```bash
PY=python3; "$PY" -c "" >/dev/null 2>&1 || PY=python
MOTION=$("$PY" -c "import os;print(os.path.expanduser('~/claude-pet/bin/claude-pet-motion'))")
"$PY" "$MOTION" <arg>
```
e.g. `"$PY" "$MOTION" jump`, `"$PY" "$MOTION" float` (holds until
`"$PY" "$MOTION" stop`), `"$PY" "$MOTION" list`.
The helper broadcasts to every running pet and prints how many reacted; if it
says `-> 0 pet(s)`, no pet is running — offer to attach one with `/claude-pet`.

## Default: attach to THIS session

0. **Pick a Python.** `python3` is canonical on Linux/macOS; on Windows it's
   often a Microsoft Store alias stub that's *present on PATH* but exits
   nonzero without doing anything, so `command -v` alone can't tell it apart
   from a real interpreter — probe that it actually runs:
   ```bash
   PY=python3; "$PY" -c "" >/dev/null 2>&1 || PY=python
   ```

1. **Find this session's id.** Claude Code sets `$CLAUDE_CODE_SESSION_ID` for
   the running session; fall back to the newest transcript under
   `~/.claude/projects/` if it's unset:
   ```bash
   SID="${CLAUDE_CODE_SESSION_ID:-$(ls -t ~/.claude/projects/*/*.jsonl 2>/dev/null | head -1 | xargs -n1 basename | sed 's/\.jsonl$//')}"
   ```

2. **Detect the host app** (terminal/IDE) so click-to-focus targets the right
   window. Build the `src` path with `os.path.expanduser` *inside* Python — do
   NOT interpolate `$HOME` into the `-c` string: on Windows git-bash `$HOME` is a
   `/c/Users/...` MSYS path that native `python.exe` can't import from (MSYS path
   conversion doesn't reach inside quoted program text):
   ```bash
   HOST=$("$PY" -c "import sys, os; sys.path.insert(0, os.path.expanduser('~/claude-pet/src')); import hostinfo; print(hostinfo.detect_host())")
   ```

3. **Skip if one is already attached, else launch it bound to the session.**
   Pets listen on loopback TCP, not a unix socket (stock Windows Python has no
   `AF_UNIX`, so the whole project uses one TCP code path — see
   `src/hostinfo.py`). Check liveness with `hostinfo.pet_alive`, the same
   handshake the hook uses (a bare connect can't tell a real pet from an
   unrelated process that reused a stale port), and launch via a native path
   with `setsid` where available so the pet gets its own process group and
   outlives this tool call (falling back to `nohup` on git-bash, which has no
   `setsid`):
   ```bash
   ALIVE=$("$PY" -c "import sys, os; sys.path.insert(0, os.path.expanduser('~/claude-pet/src')); import hostinfo; print('yes' if hostinfo.pet_alive('$SID') else 'no')")
   LAUNCH=$("$PY" -c "import os; print(os.path.expanduser('~/claude-pet/bin/claude-pet'))")
   if [ "$ALIVE" = "yes" ]; then
       echo "already attached to this session 🐾"
   else
       if command -v setsid >/dev/null 2>&1; then
           setsid "$PY" "$LAUNCH" --session "$SID" --host "$HOST" >/dev/null 2>&1 < /dev/null &
       else
           nohup "$PY" "$LAUNCH" --session "$SID" --host "$HOST" >/dev/null 2>&1 < /dev/null &
       fi
       disown 2>/dev/null || true
       echo "attached to session $SID (host=$HOST) 🐾"
   fi
   ```

**Reactions require hooks.** The pet only reacts to this session if the
claude-pet hooks are installed (`~/claude-pet/bin/claude-pet-install-hooks`) AND
this session loaded them. If hooks were installed *after* this session started,
restart the session (or the pet attaches but stays idle). New sessions
auto-attach their own pet via the SessionStart hook, so `/claude-pet` is mainly
for sessions that predate the install, or to bring a closed pet back.

## `standalone` — an unattached roaming pet

If the user said "standalone" (or just wants a decorative pet that reacts to no
particular session):
```bash
PY=python3; "$PY" -c "" >/dev/null 2>&1 || PY=python
LAUNCH=$("$PY" -c "import os; print(os.path.expanduser('~/claude-pet/bin/claude-pet'))")
if command -v setsid >/dev/null 2>&1; then
    setsid "$PY" "$LAUNCH" >/dev/null 2>&1 < /dev/null &
else
    nohup "$PY" "$LAUNCH" >/dev/null 2>&1 < /dev/null &
fi
disown 2>/dev/null || true
echo "standalone pet running 🐾"
```

## Notes
- Multiple pets are fine — each is independent. Stop one via right-click → 종료.
- This skill never installs hooks or edits settings; it only launches a pet.
