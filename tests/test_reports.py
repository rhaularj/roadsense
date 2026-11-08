import pytest
from conftest import add_event

from roadsense.common.db import session
from roadsense.core import geo, open311, reports


def test_severity_rules():
    assert reports.estimate_severity("D40", 0.03, 0.8, 5)["severity"] == "high"
    assert reports.estimate_severity("D40", 0.005, 0.8, 5)["severity"] == "medium"
    assert reports.estimate_severity("D40", 0.03, 0.2, 5)["severity"] == "medium"  # unsure → not high
    assert reports.estimate_severity("D00", 0.01, 0.9, 5)["severity"] == "low"


def test_priority_grows_with_confirmations():
    assert reports.priority("high", "D40", 3) > reports.priority("high", "D40", 1) > reports.priority("low", "D00", 1)


def test_second_driver_merges_into_existing_report(db):
    add_event("ev-aaaaaa", 44.64300, -63.58000, trip="tripA")
    add_event("ev-bbbbbb", 44.64305, -63.58004, trip="tripB")   # ~6 m away, same pothole
    add_event("ev-cccccc", 44.64400, -63.58000, trip="tripB")   # ~110 m away
    with session() as conn:
        first = reports.create_or_merge(conn, "ev-aaaaaa", "medium", "x", "Halifax Regional Municipality", 15)
        second = reports.create_or_merge(conn, "ev-bbbbbb", "high", "x", "Halifax Regional Municipality", 15)
        third = reports.create_or_merge(conn, "ev-cccccc", "low", "y", "Halifax Regional Municipality", 15)
        again = reports.create_or_merge(conn, "ev-bbbbbb", "high", "x", "Halifax Regional Municipality", 15)
    assert first["action"] == "created" and third["action"] == "created"
    assert second["action"] == "merged" and second["report"]["id"] == first["report"]["id"]
    assert second["report"]["confirmations"] == 2 and second["report"]["severity"] == "high"
    assert again["action"] == "already_linked"  # idempotent: re-running never double counts


def test_same_trip_sightings_do_not_count_as_extra_drivers(db):
    add_event("ev-t1", 44.64300, -63.58000, trip="tripA")
    add_event("ev-t2", 44.64303, -63.58002, trip="tripA")
    add_event("ev-t3", 44.64301, -63.58001, trip="tripB")
    with session() as conn:
        reports.create_or_merge(conn, "ev-t1", "medium", "x", "HRM", 15)
        same = reports.create_or_merge(conn, "ev-t2", "medium", "x", "HRM", 15)
        other = reports.create_or_merge(conn, "ev-t3", "medium", "x", "HRM", 15)
    assert same["action"] == "merged" and same["report"]["confirmations"] == 1
    assert other["report"]["confirmations"] == 2


def test_rejected_event_cannot_become_a_report(db):
    add_event("ev-rejected", 44.6, -63.5, status="rejected")
    with session() as conn, pytest.raises(ValueError):
        reports.create_or_merge(conn, "ev-rejected", "low", None, None, 15)


def test_offline_geocoder_finds_halifax(db):
    with session() as conn:
        assert geo.reverse_geocode(conn, 44.6430, -63.5800)["municipality"] == "Halifax Regional Municipality"
        assert geo.reverse_geocode(conn, 43.65, -79.38)["municipality"] is None  # Toronto: not in the fixture


def test_directory_resolves_community_aliases():
    assert open311.service_info("Dartmouth")["authority"] == "Halifax Regional Municipality"
    assert open311.service_info("Atlantis") is None
