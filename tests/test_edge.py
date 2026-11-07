from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from roadsense.edge.gps import Fix, GpsTrack, haversine_m, simulate_route, write_gpx
from roadsense.edge.redact import redact
from roadsense.edge.tracker import TrackAggregator

T0 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def test_haversine_one_degree_latitude():
    assert haversine_m(44.0, -63.0, 45.0, -63.0) == pytest.approx(111_195, rel=1e-3)


def test_gps_interpolates_and_gives_heading():
    track = GpsTrack([Fix(T0, 44.0, -63.0), Fix(T0 + timedelta(seconds=10), 44.0, -62.99)])
    lat, lon, heading, when = track.at(5)
    assert (lat, lon) == pytest.approx((44.0, -62.995))
    assert heading == pytest.approx(90, abs=0.1)  # due east
    assert when == T0 + timedelta(seconds=5)
    assert track.at(999)[1] == pytest.approx(-62.99)  # clamped past the end


def test_gpx_and_csv_round_trip(tmp_path):
    fixes = simulate_route([(44.0, -63.0), (44.001, -63.0)], speed_kmh=36, start=T0)
    assert len(fixes) >= 11  # ~111 m at 10 m/s
    write_gpx(fixes, tmp_path / "r.gpx")
    assert GpsTrack.load(tmp_path / "r.gpx").at(5)[0] == pytest.approx(44.00045, abs=1e-5)
    (tmp_path / "r.csv").write_text("time,lat,lon\n2026-11-02T12:00:00Z,44,-63\n2026-11-02T12:00:10Z,44.001,-63\n")
    assert GpsTrack.load(tmp_path / "r.csv").at(10)[0] == pytest.approx(44.001)


def det(tid, code="D40", conf=0.6):
    return {"track_id": tid, "code": code, "name": code, "confidence": conf, "box": [10, 10, 20, 20]}


def test_tracker_emits_one_event_per_defect_after_it_leaves_view():
    agg, frame = TrackAggregator(min_frames=3, max_gap_s=1.0), np.zeros((100, 100, 3), np.uint8)
    for i, conf in enumerate([0.4, 0.9, 0.5]):
        assert agg.update(i * 0.2, frame, [det(7, conf=conf), det(8)] if i == 0 else [det(7, conf=conf)]) == []
    done = agg.update(2.0, frame, [])
    assert [s.track_id for s in done] == [7]  # track 8 was seen once: filtered as a one-frame false alarm
    assert done[0].best["confidence"] == 0.9 and done[0].frames_seen == 3
    assert agg.active == {}


def test_tracker_majority_class_vote():
    agg, frame = TrackAggregator(min_frames=1), np.zeros((10, 10, 3), np.uint8)
    for code in ("D20", "D40", "D40"):
        agg.update(0, frame, [det(1, code)])
    assert agg.flush()[0].class_code == "D40"


def test_redaction_keeps_damage_and_blurs_the_rest():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
    out = redact(frame, [[50, 50, 100, 100]], margin=0)
    assert np.array_equal(out[50:100, 50:100], frame[50:100, 50:100])
    assert np.abs(out[150:, 150:].astype(int) - frame[150:, 150:]).mean() > 30


def test_points_along_a_route_are_evenly_spaced():
    from roadsense.edge.gps import points_along

    pts = points_along([(44.0, -63.0), (44.001, -63.0), (44.002, -63.0)], 50.0)  # ~222 m straight north
    gaps = [haversine_m(*a, *b) for a, b in zip(pts, pts[1:])]
    assert len(pts) == 5 and all(abs(g - 50.0) < 0.5 for g in gaps)


def test_simulated_route_follows_real_street_geometry():
    from roadsense.edge.simulate_gps import HALIFAX_ROUTE

    # dense OSRM road geometry, not a handful of hand-typed corners
    assert len(HALIFAX_ROUTE) > 30
    assert max(haversine_m(*a, *b) for a, b in zip(HALIFAX_ROUTE, HALIFAX_ROUTE[1:])) < 200
