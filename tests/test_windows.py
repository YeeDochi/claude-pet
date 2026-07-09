import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import windows

SAMPLE = ("{id1};plasmashell;0,0,1920,1200|"         # desktop -> filtered
          "{id2};org.kde.konsole;100.5,200.2,400,300|"  # kept (float coords)
          "{id3};claude-pet;1356,1094,120,105|"        # pet -> filtered
          "{id4};;0,0,32,32")                          # empty class -> filtered


def test_parse_kwin_dump_filters_and_ints():
    wins = windows.parse_kwin_dump(SAMPLE)
    assert len(wins) == 1
    k = wins[0]
    assert k.title == "org.kde.konsole"
    assert (k.x, k.y, k.w, k.h) == (100, 200, 400, 300)   # floats floored to int


def test_parse_kwin_dump_skips_malformed():
    assert windows.parse_kwin_dump("garbage|;;|id;cls;1,2,3") == []


def test_window_at_and_surface_via_dump():
    wins = windows.parse_kwin_dump(SAMPLE)
    assert windows.window_at(150, 250, wins).title == "org.kde.konsole"
    assert windows.top_surface_under(150, wins, 1080) == 200
    assert windows.top_surface_under(3000, wins, 1080) == 1080


def test_window_at_outside_returns_none():
    wins = windows.parse_kwin_dump(SAMPLE)
    assert windows.window_at(5000, 5000, wins) is None


def test_support_surface_no_autoclimb_from_floor():
    # feet on the screen floor, konsole top (200) is far ABOVE the feet ->
    # must NOT climb: returns the floor, not the window top.
    wins = windows.parse_kwin_dump(SAMPLE)
    assert windows.support_surface_under(150, wins, 1080, feet_y=1080) == 1080


def test_support_surface_lands_when_above_window():
    # feet above konsole's top (feet_y=100 < top 200) -> eligible -> lands on it
    wins = windows.parse_kwin_dump(SAMPLE)
    assert windows.support_surface_under(150, wins, 1080, feet_y=100) == 200


def test_support_surface_stays_on_current_perch():
    # standing on konsole (feet ~ its top 200) -> keeps resting on it (within tol)
    wins = windows.parse_kwin_dump(SAMPLE)
    assert windows.support_surface_under(150, wins, 1080, feet_y=200) == 200
