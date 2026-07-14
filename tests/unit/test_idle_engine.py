from claudlet.core.idle_engine import IdleEnergy, HIGH, MID, LOW


def test_starts_full_and_high():
    e = IdleEnergy()
    assert e.value == 1.0
    assert e.level() == HIGH


def test_events_drain_energy():
    e = IdleEnergy()
    for i in range(200):
        e.note_event(now=float(i))
    assert e.value < 1.0


def test_roam_drains_energy():
    e = IdleEnergy()
    start = e.value
    for i in range(500):
        e.note_roam(now=float(i))
    assert e.value < start


def test_passive_time_drains_slowly_when_not_resting():
    e = IdleEnergy()
    e.update(now=0.0, resting=False)     # first call records the clock baseline
    e.update(now=300.0, resting=False)   # 5 min elapsed -> drains
    assert e.value < 1.0


def test_resting_recovers_energy():
    e = IdleEnergy(energy=0.3)
    low = e.value
    for i in range(1, 4000):
        e.update(now=float(i), resting=True)
    assert e.value > low


def test_energy_clamped_to_unit_interval():
    e = IdleEnergy(energy=0.02)
    for i in range(10000):
        e.note_event(now=float(i))
        e.note_roam(now=float(i))
    assert e.value >= 0.0
    e2 = IdleEnergy(energy=0.99)
    for i in range(1, 100000):
        e2.update(now=float(i), resting=True)
    assert e2.value <= 1.0


def test_levels_partition_by_threshold():
    assert IdleEnergy(energy=0.9).level() == HIGH
    assert IdleEnergy(energy=0.5).level() == MID
    assert IdleEnergy(energy=0.1).level() == LOW


def test_wake_rebounds_energy():
    e = IdleEnergy(energy=0.2)
    e.wake(now=100.0)
    assert e.value > 0.2
