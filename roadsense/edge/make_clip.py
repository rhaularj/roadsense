"""Build a test dashcam clip from consecutive still frames (e.g. an RDD2022 test-split sequence).

RDD2022 images are dashcam frames taken about a metre apart, so a run of consecutive file names plays like a slow
drive. Each still is turned into ~1 s of simulated forward motion. Useful for repeatable tests; the final
demo should use real footage.

    python -m roadsense.edge.make_clip --images D:/py/road-pot-hole-detector/data/test/images \
        --prefix United_States_ --count 120 --out clips/us_test.mp4
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2


def drive_frames(frame, n: int, zoom: float = 1.35, horizon: float = 0.45):
    """Simulated forward motion: zoom progressively towards the horizon, so road damage slides down and grows across
    frames the way it does when a car approaches it (good enough to exercise the tracker)."""
    h, w = frame.shape[:2]
    for k in range(n):
        s = 1 + (zoom - 1) * k / max(n - 1, 1)
        cw, ch = w / s, h / s
        x0, y0 = (w - cw) / 2, horizon * h - horizon * ch
        yield cv2.resize(frame[int(y0):int(y0 + ch), int(x0):int(x0 + cw)], (w, h), interpolation=cv2.INTER_LINEAR)


def make_clip(images: list[Path], out: Path, fps: float = 5.0, repeat: int = 3, size: tuple[int, int] = (1280, 720),
              video_fps: float = 30.0):
    """Each still becomes `repeat` frames of simulated forward motion, written at video_fps."""
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), video_fps, size)
    for path in images:
        frame = cv2.imread(str(path))
        if frame is None:
            continue
        for f in drive_frames(cv2.resize(frame, size, interpolation=cv2.INTER_AREA), repeat):
            writer.write(f)
    writer.release()
    return len(images) * repeat / video_fps


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--images", required=True, help="folder of frames")
    p.add_argument("--prefix", default="", help="only files starting with this (one country/sequence)")
    p.add_argument("--start", type=int, default=0, help="index of the first frame after sorting")
    p.add_argument("--count", type=int, default=120)
    p.add_argument("--frames-per-still", type=int, default=30, help="frames of simulated driving per still (1 s)")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    frames = sorted(p for p in Path(args.images).glob(f"{args.prefix}*.jpg"))[args.start:args.start + args.count]
    if not frames:
        raise SystemExit("no frames matched")
    seconds = make_clip(frames, Path(args.out), repeat=args.frames_per_still)
    print(f"wrote {args.out}: {len(frames)} frames, {seconds:.0f} s")


if __name__ == "__main__":
    main()
