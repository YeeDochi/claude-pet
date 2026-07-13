from claudlet.platform import geom

SAMPLE = ("{id1};plasmashell;0,0,1920,1200|"         # desktop -> filtered
          "{id2};org.kde.konsole;100.5,200.2,400,300|"  # kept (float coords)
          "{id3};claudlet;1356,1094,120,105|"        # pet -> filtered
          "{id4};;0,0,32,32")                          # empty class -> filtered


def test_parse_dump_filters_and_ints():
    wins = geom.parse_dump(SAMPLE)
    assert len(wins) == 1
    k = wins[0]
    assert k.title == "org.kde.konsole"
    assert (k.x, k.y, k.w, k.h) == (100, 200, 400, 300)   # floats floored to int


def test_parse_dump_skips_malformed():
    assert geom.parse_dump("garbage|;;|id;cls;1,2,3") == []


def test_window_at_and_surface_via_dump():
    wins = geom.parse_dump(SAMPLE)
    assert geom.window_at(150, 250, wins).title == "org.kde.konsole"
    assert geom.top_surface_under(150, wins, 1080) == 200
    assert geom.top_surface_under(3000, wins, 1080) == 1080


def test_window_at_outside_returns_none():
    wins = geom.parse_dump(SAMPLE)
    assert geom.window_at(5000, 5000, wins) is None


def test_support_surface_no_autoclimb_from_floor():
    # feet on the screen floor, konsole top (200) is far ABOVE the feet ->
    # must NOT climb: returns the floor, not the window top.
    wins = geom.parse_dump(SAMPLE)
    assert geom.support_surface_under(150, wins, 1080, feet_y=1080) == 1080


def test_support_surface_lands_when_above_window():
    # feet above konsole's top (feet_y=100 < top 200) -> eligible -> lands on it
    wins = geom.parse_dump(SAMPLE)
    assert geom.support_surface_under(150, wins, 1080, feet_y=100) == 200


def test_support_surface_stays_on_current_perch():
    # standing on konsole (feet ~ its top 200) -> keeps resting on it (within tol)
    wins = geom.parse_dump(SAMPLE)
    assert geom.support_surface_under(150, wins, 1080, feet_y=200) == 200


# ---- host-window identification & occlusion (focus/visibility) ----

def test_parse_reads_optional_pid():
    wins = geom.parse_dump("{id};org.kde.konsole;10,10,400,300;4242")
    assert wins[0].pid == 4242


def test_parse_pid_absent_is_none():
    wins = geom.parse_dump("{id};org.kde.konsole;10,10,400,300")
    assert wins[0].pid is None


def test_find_host_matches_ancestor_pid():
    wins = [geom.Win("a", 0, 0, 400, 300, "code", 100),
            geom.Win("b", 0, 0, 400, 300, "konsole", 200)]
    # claude's ancestor chain includes 200 (the konsole process) -> that window
    assert geom.find_host(wins, {200, 999}).wid == "b"


def test_find_host_none_when_no_pid_match():
    wins = [geom.Win("a", 0, 0, 400, 300, "konsole", 200)]
    assert geom.find_host(wins, {111, 222}) is None


def test_find_host_skips_explorer_shell_window():
    # Windows Terminal launches via COM/DelegateExecute, so claude.exe's ancestor
    # chain runs up through explorer.exe (pid 27704). explorer owns a visible File
    # Explorer window (CabinetWClass) whose pid is therefore an "ancestor" — but
    # it is NOT the host. find_host must skip it (else clicks focus File Explorer).
    # WindowsTerminal.exe's own pid is not in the chain, so there's no real host
    # window here -> None, and the caller falls back to a class match.
    wins = [geom.Win("expl", 0, 0, 800, 600, "cabinetwclass", 27704)]
    assert geom.find_host(wins, {999, 27704}) is None


def test_find_host_skips_explorer_and_picks_real_terminal():
    # explorer is a fake-ancestor precedes the real terminal in the list; the
    # terminal's pid is genuinely in the chain -> skip explorer, adopt the terminal.
    wins = [geom.Win("expl", 0, 0, 800, 600, "cabinetwclass", 27704),
            geom.Win("term", 0, 0, 900, 500, "consolewindowclass", 3333)]
    h = geom.find_host(wins, {3333, 27704})
    assert h is not None and h.wid == "term"


# pick_focus_target — click-to-focus target selection. Unlike find_host it runs
# over a MINIMIZED-INCLUSIVE window list (so a minimized host can be restored):
# pid-pin first (skipping shell chrome), then a class-substring fallback.
CASCADIA = ["cascadia_hosting_window_class", "consolewindowclass"]


def test_pick_focus_target_pid_match_skips_shell():
    wins = [geom.Win("expl", 0, 0, 0, 0, "cabinetwclass", 27704),
            geom.Win("term", 0, 0, 0, 0, "consolewindowclass", 3333)]
    assert geom.pick_focus_target(wins, {3333, 27704}, CASCADIA) == "term"


def test_pick_focus_target_class_fallback_when_no_pid():
    # WT's window pid isn't in the chain (COM launch) -> fall back to class match
    wins = [geom.Win("term", 0, 0, 0, 0, "cascadia_hosting_window_class", 5555)]
    assert geom.pick_focus_target(wins, {999}, CASCADIA) == "term"


def test_pick_focus_target_finds_minimized_host():
    # the caller includes minimized windows; a minimized terminal (ancestor pid)
    # must still be selected so click-to-focus can restore it.
    wins = [geom.Win("min", 0, 0, 0, 0, "consolewindowclass", 3333)]
    assert geom.pick_focus_target(wins, {3333}, CASCADIA) == "min"


def test_pick_focus_target_none_when_nothing_matches():
    wins = [geom.Win("x", 0, 0, 0, 0, "notepadclass", 42)]
    assert geom.pick_focus_target(wins, {1}, CASCADIA) is None


def test_covered_by_higher_full_cover():
    host = geom.Win("h", 100, 100, 400, 300, "konsole", 1)
    top = geom.Win("t", 0, 0, 1920, 1080, "code", 2)     # maximized above
    assert geom.covered_by_higher(host, [host, top]) is True   # stacking: host below top


def test_not_covered_when_window_is_below():
    host = geom.Win("h", 100, 100, 400, 300, "konsole", 1)
    below = geom.Win("b", 0, 0, 1920, 1080, "code", 2)
    assert geom.covered_by_higher(host, [below, host]) is False  # host is on top


def test_not_covered_by_partial_overlap():
    host = geom.Win("h", 100, 100, 400, 300, "konsole", 1)
    partial = geom.Win("p", 300, 100, 400, 300, "code", 2)      # overlaps, not full
    assert geom.covered_by_higher(host, [host, partial]) is False


def test_window_under_feet_returns_perch():
    w = geom.Win("w", 100, 200, 400, 300, "browser", 1)
    # feet resting on the window's top edge (y=200) -> that's the perch
    assert geom.window_under_feet(150, 200, [w]).wid == "w"


def test_window_under_feet_none_on_desktop():
    w = geom.Win("w", 100, 200, 400, 300, "browser", 1)
    # feet well below the window top and outside it -> bare desktop
    assert geom.window_under_feet(150, 900, [w]) is None
    # feet above the window top (not resting on it) -> not perched on it
    assert geom.window_under_feet(150, 50, [w]) is None


def test_window_under_feet_picks_highest_top():
    lo = geom.Win("lo", 0, 400, 800, 300, "a", 1)
    hi = geom.Win("hi", 0, 250, 800, 300, "b", 2)
    # both span cx; feet at 250 -> the higher top (250) is the perch
    assert geom.window_under_feet(100, 250, [lo, hi]).wid == "hi"
