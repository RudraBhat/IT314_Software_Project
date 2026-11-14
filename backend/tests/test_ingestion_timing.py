from main import _seconds_until_next_ingestion


def test_local_ingestion_waits_only_for_remaining_start_to_start_interval():
    assert _seconds_until_next_ingestion(900, cycle_started=100, completed=110) == 890


def test_local_ingestion_skips_missed_ticks_without_burst_polling():
    assert _seconds_until_next_ingestion(900, cycle_started=100, completed=1_200) == 700
    assert _seconds_until_next_ingestion(900, cycle_started=100, completed=1_000) == 0
    assert _seconds_until_next_ingestion(900, cycle_started=100, completed=1_900) == 0
    assert _seconds_until_next_ingestion(900, cycle_started=100, completed=1_901) == 899
