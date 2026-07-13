from claudlet.core.state_engine import StateEngine


def test_ask_user_question_shows_asking():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a",
              "tool_name": "AskUserQuestion"}, 0.0)
    assert e.display_state(0.0) == "asking"


def test_exit_plan_mode_shows_asking():
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a",
              "tool_name": "ExitPlanMode"}, 0.0)
    assert e.display_state(0.0) == "asking"


def test_asking_outranks_work_in_another_session():
    # one session grinding, another waiting on the user -> the wait wins,
    # because the user needs to act (finer/​separate from attention, but high pri)
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a", "tool_name": "Edit"}, 0.0)
    e.handle({"event": "PreToolUse", "session": "b",
              "tool_name": "AskUserQuestion"}, 0.0)
    assert e.display_state(0.1) == "asking"


def test_asking_is_distinct_from_attention():
    # permission_prompt is attention; AskUserQuestion is asking — not the same
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a",
              "tool_name": "AskUserQuestion"}, 0.0)
    assert e.display_state(0.0) == "asking"
    assert e.display_state(0.0) != "attention"


def test_asking_is_overridable():
    e = StateEngine(event_states={"asking": "wave"})
    e.handle({"event": "PreToolUse", "session": "a",
              "tool_name": "ExitPlanMode"}, 0.0)
    assert e.display_state(0.0) == "wave"


def test_asking_decays_when_left_hanging():
    # if the user never answers, the pet shouldn't be stuck asking forever
    e = StateEngine()
    e.handle({"event": "PreToolUse", "session": "a",
              "tool_name": "AskUserQuestion"}, 0.0)
    assert e.display_state(1.0) == "asking"
    assert e.display_state(1000.0) in ("idle", "sleeping")
