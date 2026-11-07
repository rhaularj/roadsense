"""Level 1, the edge device: dashcam video + GPS track in, privacy-safe damage events out.

    python -m roadsense.edge.process_video --video clips/drive.mp4 --gps clips/drive.gpx
    python -m roadsense.edge.process_video --video clips/drive.mp4 --gps clips/drive.gpx --offline   # queue only

Runs the fast detector (YOLOv8m) at a reduced frame rate, groups detections of the same defect with BoT-SORT (camera
motion compensated), keeps the sharpest confident frame of each defect, blurs everything but the damage, and places
the defect on the map: the car's interpolated GPS fix moved forward along the heading by the flat-road distance to
the defect. Events go to the local outbox; unless --offline, the outbox is then uploaded to the agent API.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import cv2

from ..common.config import settings
from ..common.detectors import CLASSES, Detector
from ..common.schemas import DamageEvent
from .camera import Camera, offset_position, uncertainty_m
from .gps import GpsTrack
from .outbox import upload
from .redact import redact
from .tracker import TrackAggregator, TrackState

NAME_BY_CODE = {code: name for code, name, _ in CLASSES.values()}
TRACKER = str(Path(__file__).with_name("botsort_roadsense.yaml"))


def default_outbox() -> Path:
    return settings.data_dir / "outbox"


def _event(state: TrackState, trip_id: str, gps: GpsTrack, camera: Camera) -> DamageEvent:
    car_lat, car_lon, heading, when = gps.at(state.best_t)
    h, w = state.best_frame.shape[:2]
    x1, y1, x2, y2 = state.best["box"]
    ground = camera.ground(state.best["box"], w, h)
    lat, lon = (offset_position(car_lat, car_lon, heading, ground["forward_m"], ground["lateral_m"])
                if ground else (car_lat, car_lon))
    code = state.class_code  # majority vote over the track's frames
    return DamageEvent(
        id=f"{trip_id}-{state.track_id}-{uuid.uuid4().hex[:6]}", trip_id=trip_id, track_id=state.track_id,
        class_code=code, class_name=NAME_BY_CODE[code], confidence=state.best["confidence"],
        frames_seen=state.frames_seen, box=state.best["box"], box_area_ratio=round((x2 - x1) * (y2 - y1) / (w * h), 5),
        lat=round(lat, 6), lon=round(lon, 6), heading=round(heading, 1) % 360, captured_at=when,
        car_lat=round(car_lat, 6), car_lon=round(car_lon, 6),
        distance_m=round(ground["forward_m"], 1) if ground else None,
        width_m=round(ground["width_m"], 2) if ground else None,
        position_uncertainty_m=uncertainty_m(ground["forward_m"] if ground else None))


def process_video(video: str | Path, gps_path: str | Path, trip_id: str | None = None, outbox: Path | None = None,
                  sample_fps: float = 5.0, gps_offset_s: float = 0.0, detector: Detector | None = None,
                  min_frames: int = 3, roi_top: float = 0.0, camera: Camera | None = None,
                  progress: Callable[[float, str], None] | None = None) -> dict:
    """roi_top: fraction of the frame height (sky) dropped before detection; boxes are mapped back to the full frame."""
    trip_id = trip_id or time.strftime("trip%Y%m%d-%H%M%S")
    outbox = (outbox or default_outbox()) / trip_id
    outbox.mkdir(parents=True, exist_ok=True)
    gps = GpsTrack.load(gps_path, offset_s=gps_offset_s)
    detector = detector or Detector(settings.weights_dir / settings.edge_weights, settings.device)
    detector.reset_tracker()
    camera = camera or Camera()

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"cannot open video {video}")
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    stride = max(int(round(video_fps / sample_fps)), 1)
    aggregator = TrackAggregator(min_frames=min_frames, max_gap_s=max(1.5, 3 * stride / video_fps))

    events, frame_idx, processed, infer_s = [], 0, 0, 0.0
    started = time.perf_counter()

    def emit(states):
        for s in states:
            e = _event(s, trip_id, gps, camera)
            cv2.imwrite(str(outbox / f"{e.id}.jpg"), redact(s.best_frame, [s.best["box"]]),
                        [cv2.IMWRITE_JPEG_QUALITY, 90])
            (outbox / f"{e.id}.json").write_text(e.model_dump_json(indent=2), encoding="utf-8")
            events.append(e)

    while True:
        if not cap.grab():
            break
        if frame_idx % stride == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            top = int(frame.shape[0] * roi_top)
            t0 = time.perf_counter()
            detections = detector.track(frame[top:] if top else frame, tracker=TRACKER)
            infer_s += time.perf_counter() - t0
            for d in detections:
                d["box"] = [d["box"][0], d["box"][1] + top, d["box"][2], d["box"][3] + top]
            processed += 1
            emit(aggregator.update(frame_idx / video_fps, frame, detections))
            if progress and total:
                progress(frame_idx / total, f"{processed} frames analysed, {len(events)} defects found")
        frame_idx += 1
    cap.release()
    emit(aggregator.flush())

    elapsed = time.perf_counter() - started
    stats = {"trip_id": trip_id, "outbox": str(outbox), "events": len(events),
             "by_class": {c: sum(e.class_code == c for e in events) for c in sorted({e.class_code for e in events})},
             "video_seconds": round(frame_idx / video_fps, 1), "frames_analysed": processed,
             "detector": detector.label, "tracker": "BoT-SORT (sparse optical flow motion compensation)",
             "detector_fps": round(processed / infer_s, 1) if infer_s else None,
             "pipeline_fps": round(processed / elapsed, 1) if elapsed else None,
             "projected": sum(e.distance_m is not None for e in events)}
    (outbox / "trip.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", required=True)
    p.add_argument("--gps", required=True, help="GPX or CSV (time,lat,lon) track")
    p.add_argument("--trip-id")
    p.add_argument("--fps", type=float, default=5.0, help="frames analysed per second of video")
    p.add_argument("--gps-offset", type=float, default=0.0, help="seconds between GPS track start and video start")
    p.add_argument("--min-frames", type=int, default=3)
    p.add_argument("--roi-top", type=float, default=0.0, help="fraction of frame height (sky) to skip, e.g. 0.35")
    p.add_argument("--offline", action="store_true", help="only queue events in the outbox")
    args = p.parse_args()

    stats = process_video(args.video, args.gps, args.trip_id, sample_fps=args.fps, gps_offset_s=args.gps_offset,
                          min_frames=args.min_frames, roi_top=args.roi_top)
    print(json.dumps(stats, indent=2))
    if not args.offline:
        print(json.dumps(upload(Path(stats["outbox"])), indent=2))


if __name__ == "__main__":
    main()
