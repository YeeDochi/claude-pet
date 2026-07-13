from claudlet.core.state_engine import tool_to_state, StateEngine


def test_tool_states_override():
    e = StateEngine(tool_states={"Bash": "work_search", "Grep": "sing", "*": "thinking"})
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Bash"}, 0.0)
    assert e.display_state(0.0) == "work_search"           # remapped tool
    e2 = StateEngine(tool_states={"Grep": "sing"})
    e2.handle({"event": "PreToolUse", "session": "a", "tool_name": "Grep"}, 0.0)
    assert e2.display_state(0.0) == "sing"                 # mapped to a fun motion
    e3 = StateEngine(tool_states={"*": "thinking"})
    e3.handle({"event": "PreToolUse", "session": "a", "tool_name": "Unheard"}, 0.0)
    assert e3.display_state(0.0) == "thinking"             # "*" fallback


def test_event_states_override():
    e = StateEngine(event_states={"prompt": "juggle"})
    e.handle({"event": "UserPromptSubmit", "session": "a"}, 0.0)
    assert e.display_state(0.0) == "juggle"


def test_raw_event_mapping_for_unhandled_events():
    # an event without a dedicated slot (PostToolUse) is mappable by raw name
    e = StateEngine(raw_events={"PostToolUse": "wave"})
    e.handle({"event": "PostToolUse", "session": "a", "tool_name": "Edit"}, 0.0)
    assert e.display_state(0.0) == "wave"


def test_raw_event_does_not_override_handled_slots():
    # a handled event (UserPromptSubmit) keeps its slot behaviour even if also
    # named in raw_events — the specific branch wins
    e = StateEngine(raw_events={"UserPromptSubmit": "sing"})
    e.handle({"event": "UserPromptSubmit", "session": "a"}, 0.0)
    assert e.display_state(0.0) == "thinking"


def test_custom_target_gets_work_priority_and_decays():
    # a custom tool state must win over idle (priority) and still time out so it
    # doesn't stick forever with no further events
    e = StateEngine(tool_states={"Grep": "sing"})
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Grep"}, 0.0)
    assert e.display_state(1.0) == "sing"
    # WORK_TIMEOUT decay (then straight to sleeping, since it's also past SLEEP)
    assert e.display_state(1000.0) in ("idle", "sleeping")


def test_tool_to_state_known_and_fallback():
    assert tool_to_state("Edit") == "work_computer"
    assert tool_to_state("Bash") == "work_computer"
    assert tool_to_state("Read") == "work_search"
    assert tool_to_state("Grep") == "work_search"
    assert tool_to_state("WebFetch") == "work_web"
    assert tool_to_state("Skill") == "work_skill"
    assert tool_to_state("mcp__gitlab__get_project") == "work_web"
    assert tool_to_state("SomethingNew") == "work_computer"   # fallback


def test_pretooluse_sets_work_state():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Edit"}, now=0.0)
    assert e.display_state(now=0.0) == "work_computer"


def test_agent_dispatch_does_not_change_main_state():
    # subagent dispatch (PreToolUse tool_name "Agent") is companion-only: it must
    # NOT turn the main creature into an agent state — it just opens the counter,
    # leaving the main state as-is (here: still idle) so the main pet keeps
    # reflecting the parent's own activity.
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Agent"}, now=0.0)
    assert e.display_state(now=0.0) == "idle"
    assert e.agents_active() == 1


def _ev(name, sid="a", **kw):
    d = {"event": name, "session": sid}
    d.update(kw)
    return d


def test_agents_active_counts_open_window():
    e = StateEngine()
    assert e.agents_active() == 0
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    assert e.agents_active() == 1
    e.handle(_ev("SubagentStop"), now=1.0)
    assert e.agents_active() == 0


def test_agents_active_persists_across_other_motions():
    # THE point: a companion must stay up while the main creature shows other
    # work (background/parallel agent) — agents_active independent of display.
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("PreToolUse", tool_name="Read"), now=1.0)   # parent keeps working
    assert e.display_state(now=1.0) == "work_search"         # main moved on
    assert e.agents_active() == 1                            # companion stays


def test_agents_active_parallel_and_floor():
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("PreToolUse", tool_name="Task"), now=0.1)   # alias also counts
    assert e.agents_active() == 2
    e.handle(_ev("SubagentStop"), now=1.0)
    assert e.agents_active() == 1
    e.handle(_ev("SubagentStop"), now=1.1)
    assert e.agents_active() == 0
    e.handle(_ev("SubagentStop"), now=1.2)                   # extra -> floor at 0
    assert e.agents_active() == 0


def test_agents_survive_turn_boundaries():
    # BACKGROUND subagents outlive the turn: the user chats (UserPromptSubmit)
    # and the main turn ends (Stop) while they still run — the companion must
    # NOT vanish then. Only their real SubagentStop closes the window.
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("Stop"), now=1.0)
    assert e.agents_active() == 1
    e.handle(_ev("UserPromptSubmit"), now=2.0)
    assert e.agents_active() == 1
    e.handle(_ev("SubagentStop"), now=3.0)
    assert e.agents_active() == 0


def test_agents_reset_on_session_boundaries():
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("SessionStart"), now=1.0)     # fresh session -> nothing carried
    assert e.agents_active() == 0


def test_agent_state_is_thinking_while_active_and_closes_with_window():
    # the companion shows its OWN life: thinking while the agent runs (subagent
    # tool events never reach parent hooks — session tools are the PARENT's and
    # must not repaint the companion), gone when the window closes.
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    assert e.agent_state() == "thinking"          # spinning up
    e.handle(_ev("PreToolUse", tool_name="Bash"), now=0.1)
    assert e.agent_state() == "thinking"          # parent tool: companion unmoved
    e.handle(_ev("SubagentStop"), now=0.3)
    assert e.agent_state() is None                # window closed (legacy path)


def test_no_sessions_is_sleeping():
    e = StateEngine()
    assert e.display_state(now=0.0) == "sleeping"


def test_priority_picks_attention_over_work():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Edit"}, now=0.0)
    e.handle({"event": "Notification", "session": "b",
              "notification_type": "permission_prompt"}, now=0.0)
    assert e.display_state(now=0.0) == "attention"


def test_debounce_holds_fast_tool_switch():
    e = StateEngine()
    # a fast Read then an immediate Edit within the debounce window
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Read"}, now=0.0)
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Edit"}, now=0.2)
    # still inside 0.8s hold -> the search motion is still what shows
    assert e.display_state(now=0.3) == "work_search"
    # after the hold expires, the pending Edit is promoted
    assert e.display_state(now=0.9) == "work_computer"


def test_same_tool_repeats_do_not_reset_forever():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Read"}, now=0.0)
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Grep"}, now=0.1)
    # Grep is also work_search — no visible change, no pending needed
    assert e.display_state(now=0.2) == "work_search"
    assert e.display_state(now=1.0) == "work_search"


def test_stop_focused_goes_idle_not_celebrate():
    e = StateEngine(is_focused=lambda: True)
    e.handle({"event": "Stop", "session": "a"}, now=0.0)
    assert e.display_state(now=0.0) == "idle"


def test_stop_unfocused_celebrates_then_decays_to_idle():
    e = StateEngine(is_focused=lambda: False)
    e.handle({"event": "Stop", "session": "a"}, now=0.0)
    assert e.display_state(now=0.5) == "celebrate"
    assert e.display_state(now=1.7) == "idle"      # after CELEBRATE_DUR (1.6s)


def test_idle_sleeps_after_timeout():
    e = StateEngine(is_focused=lambda: True)
    e.handle({"event": "Stop", "session": "a"}, now=0.0)      # -> idle
    assert e.display_state(now=10.0) == "idle"
    assert e.display_state(now=61.0) == "sleeping"            # 60s quiet


def test_idle_prompt_sleeps_immediately():
    e = StateEngine()
    e.handle({"event": "Notification", "session": "a",
              "notification_type": "idle_prompt"}, now=0.0)
    assert e.display_state(now=0.1) == "sleeping"


def test_stopfailure_errors_then_decays():
    e = StateEngine()
    e.handle({"event": "StopFailure", "session": "a"}, now=0.0)
    assert e.display_state(now=1.0) == "error"
    assert e.display_state(now=2.1) == "idle"                 # after ERROR_DUR (2.0s)


def test_userpromptsubmit_thinks_then_works():
    e = StateEngine()
    e.handle({"event": "UserPromptSubmit", "session": "a"}, now=0.0)
    assert e.display_state(now=0.0) == "thinking"
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Read"}, now=0.5)
    assert e.display_state(now=0.5) == "work_search"


def test_sessionend_drops_session():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Edit"}, now=0.0)
    e.handle({"event": "SessionEnd", "session": "a"}, now=0.1)
    assert e.display_state(now=0.1) == "sleeping"


def test_work_state_times_out_when_no_stop_fires():
    # user interrupts (ESC) mid-Bash: no Stop, no further events
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Bash"}, now=0.0)
    assert e.display_state(now=10.0) == "work_computer"
    # after WORK_TIMEOUT of silence it falls back and (being long-quiet) sleeps
    assert e.display_state(now=121.0) == "sleeping"


def test_thinking_times_out_when_no_stop_fires():
    e = StateEngine()
    e.handle({"event": "UserPromptSubmit", "session": "a"}, now=0.0)
    assert e.display_state(now=10.0) == "thinking"
    assert e.display_state(now=121.0) == "sleeping"


# --- issue #2: companion lifetime tracks Claude Code's background_tasks -------
# Events forwarded from a Stop/SubagentStop payload carry two reconciled counts
# (see hook.build_message): bg_agents = running subagent-type tasks excluding
# the stopping agent itself; bg_tasks = ALL running background tasks excluding
# self. The engine uses these as ground truth instead of blind -1 arithmetic.

def test_companion_persists_while_subagent_backgrounds_work():
    # A subagent yields (its SubagentStop) but its own background shell is still
    # running: no active subagent (bg_agents=0) yet work remains (bg_tasks=1).
    # The companion must STAY, shown idle -- not vanish mid-work (the bug).
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    assert e.agents_active() == 1
    e.handle(_ev("SubagentStop", bg_agents=0, bg_tasks=1), now=1.0)
    assert e.agents_active() == 1
    assert e.agent_state() == "idle"


def test_companion_departs_when_background_work_clears():
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("SubagentStop", bg_agents=0, bg_tasks=1), now=1.0)
    assert e.agents_active() == 1
    e.handle(_ev("SubagentStop", bg_agents=0, bg_tasks=0), now=2.0)
    e.display_state(now=2.0 + 10.0)               # past the depart grace
    assert e.agents_active() == 0
    assert e.agent_state() is None


def test_subagentstop_reconciles_count_to_ground_truth():
    # two dispatched; a stop reporting 1 still active reconciles to 1 exactly,
    # not blind decrement.
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.1)
    assert e.agents_active() == 2
    e.handle(_ev("SubagentStop", bg_agents=1, bg_tasks=1), now=1.0)
    assert e.agents_active() == 1
    assert e.agent_state() == "thinking"


def test_stop_reconciles_companions_from_background_tasks():
    # the MAIN-turn Stop carries ground truth too: a lone yielded agent (shell
    # still running) keeps one idle companion.
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("Stop", bg_agents=0, bg_tasks=2), now=1.0)
    assert e.agents_active() == 1
    assert e.agent_state() == "idle"


def test_subagentstop_without_background_tasks_uses_legacy_decrement():
    # older Claude Code payloads carry no background_tasks -> preserve -1.
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.1)
    e.handle(_ev("SubagentStop"), now=1.0)
    assert e.agents_active() == 1


def test_hook_to_engine_companion_survives_its_own_final_stop():
    # end-to-end contract, and the core issue #2 fix: at an agent's OWN final
    # SubagentStop it still lists itself as running (the UI still shows it), so
    # piping that real payload through build_message must KEEP the companion --
    # it only leaves once a later snapshot no longer lists the work.
    import json
    from claudlet import hook
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    bt = [{"id": "A", "type": "subagent", "status": "running"}]   # self, still listed
    msg = json.loads(hook.build_message(
        ["claudlet-hook", "SubagentStop"],
        {"session_id": "a", "agent_id": "A", "background_tasks": bt}))
    e.handle(msg, now=1.0)
    assert e.agents_active() == 1                 # stays (was the bug: it left here)
    assert e.agent_state() is not None            # still shown as an active agent

    # a later snapshot with no running work -> departs after the linger grace
    # (trailing the UI, never leading it)
    empty = json.loads(hook.build_message(
        ["claudlet-hook", "Stop"], {"session_id": "a", "background_tasks": []}))
    e.handle(empty, now=2.0)
    assert e.agents_active() == 1                 # grace: still here right away
    e.display_state(now=2.0 + 10.0)               # past the grace
    assert e.agents_active() == 0


def test_no_companion_from_unrelated_background_shell():
    # a background task with no subagent ever dispatched (e.g. a plain user bash
    # run in the background) must NOT conjure a companion out of nowhere.
    e = StateEngine()
    e.handle(_ev("Stop", bg_agents=0, bg_tasks=1), now=0.0)
    assert e.agents_active() == 0


# NOTE: there was a COMPANION_IDLE_TIMEOUT (30s idle drop) here, added on the
# assumption that Claude Code's bottom UI drops an idle agent at 30s. Issue #3
# measured that assumption to be false (the UI holds the line until the
# background work actually finishes), so the timeout is gone — see
# test_idle_companion_outlives_any_fixed_timeout_while_work_runs below.

def test_active_agent_not_dropped_by_time_passing():
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("SubagentStop", bg_agents=1, bg_tasks=1), now=1.0)    # active
    e.display_state(now=40.0)
    assert e.agents_active() == 1


# --- issue #2 follow-up: don't LEAD the UI -- linger a beat after the snapshot
# empties, so the companion never vanishes before Claude Code's bottom line.

def test_empty_snapshot_starts_grace_not_instant_departure():
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("SubagentStop", bg_agents=0, bg_tasks=0), now=1.0)   # snapshot empty
    assert e.agents_active() == 1                 # still here (grace running)
    e.display_state(now=1.5)
    assert e.agents_active() == 1                 # within grace -> still here
    e.display_state(now=1.0 + 10.0)               # well past grace
    assert e.agents_active() == 0                 # now it departs


def test_work_reappearing_within_grace_cancels_departure():
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("SubagentStop", bg_agents=0, bg_tasks=0), now=1.0)   # empty -> grace
    e.handle(_ev("SubagentStop", bg_agents=1, bg_tasks=1), now=2.0)   # it's back!
    e.display_state(now=20.0)
    assert e.agents_active() == 1                 # departure cancelled


# --- issue #3: the 30s idle-drop assumption was WRONG. Measured on hardware:
# Claude Code's bottom line keeps showing the background work until it actually
# finishes (~46s in the repro), while the idle timeout force-dropped the
# companion at ~34s. While the snapshot still lists running work, the idle
# companion must stay -- however long that takes.

def test_idle_companion_outlives_any_fixed_timeout_while_work_runs():
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("SubagentStop", bg_agents=0, bg_tasks=1), now=4.4)   # yielded, work runs
    e.display_state(now=40.0)                    # issue #3: dropped here (~34s). Wrong.
    assert e.agents_active() == 1
    e.display_state(now=300.0)                   # even minutes later: work still listed
    assert e.agents_active() == 1
    # the work actually finishing (empty snapshot) is what ends it, grace later
    e.handle(_ev("Stop", bg_agents=0, bg_tasks=0), now=301.0)
    e.display_state(now=310.0)
    assert e.agents_active() == 0


def test_final_stop_departs_without_any_later_event():
    # A background agent that finishes while the session sits idle: its own
    # final SubagentStop (which still lists itself as running) is the LAST hook
    # event -- no later snapshot ever arrives. The companion must still depart
    # on its own (grace, then goodbye), not linger forever.
    import json
    from claudlet import hook
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    bt = [{"id": "A", "type": "subagent", "status": "running"}]   # only itself
    msg = json.loads(hook.build_message(
        ["claudlet-hook", "SubagentStop"],
        {"session_id": "a", "agent_id": "A", "background_tasks": bt}))
    e.handle(msg, now=1.0)
    e.display_state(now=1.5)
    assert e.agents_active() == 1                 # grace: still here for a beat
    e.display_state(now=10.0)                     # ...but departs unaided
    assert e.agents_active() == 0


def test_parent_tools_do_not_drive_companion_state():
    # Subagent tool events are ISOLATED from parent hooks (verified live), so
    # any PreToolUse arriving while an agent window is open is the PARENT's own
    # work -- mirroring it made the companion copy the main creature. The
    # companion's state must stay its own (thinking while active, idle while
    # waiting), whatever the parent does.
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    assert e.agent_state() == "thinking"
    e.handle(_ev("PreToolUse", tool_name="Bash"), now=1.0)    # parent's own tool
    assert e.agent_state() == "thinking"                      # NOT work_computer
    e.handle(_ev("SubagentStop", bg_agents=0, bg_tasks=1), now=2.0)  # yielded
    e.handle(_ev("PreToolUse", tool_name="Read"), now=3.0)    # parent keeps going
    assert e.agent_state() == "idle"                          # still its own state


def test_parent_activity_during_grace_does_not_block_departure():
    e = StateEngine()
    e.handle(_ev("PreToolUse", tool_name="Agent"), now=0.0)
    e.handle(_ev("SubagentStop", bg_agents=0, bg_tasks=0), now=1.0)   # grace starts
    e.handle(_ev("PreToolUse", tool_name="Bash"), now=2.0)    # parent working
    e.handle(_ev("PreToolUse", tool_name="Edit"), now=2.5)
    e.display_state(now=10.0)
    assert e.agents_active() == 0                             # departed on schedule
