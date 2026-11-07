"""Flat-road camera geometry: where a detection is on the ground, and how wide it is.

A pinhole camera at height h, pitched down by θ, sees a ground point at image row v at forward distance
d = h / tan(θ + atan((v - cy) / fy)). The bottom edge of a box is where the defect touches the road. With d known,
the lateral offset is (u - cx) · d / fx and the width is box_width · d / fx. Flat ground is an assumption, so
distances beyond 40 m (near the horizon) are not trusted.

Calibrate once per vehicle: tape-measure the camera height, take the horizontal field of view from the dashcam's
spec sheet, and set the pitch so the horizon row matches cy - fy·tan(pitch).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

MAX_TRUSTED_M = 40.0
GPS_ERROR_M = 6.0  # typical consumer GNSS error in a moving car


@dataclass(frozen=True)
class Camera:
    height_m: float = float(os.environ.get("ROADSENSE_CAMERA_HEIGHT_M", "1.3"))
    pitch_deg: float = float(os.environ.get("ROADSENSE_CAMERA_PITCH_DEG", "3.0"))   # downwards
    hfov_deg: float = float(os.environ.get("ROADSENSE_CAMERA_HFOV_DEG", "110"))

    def ground(self, box: list[int], width: int, height: int) -> dict | None:
        """Forward/lateral distance (m) of the box's ground contact point and its width (m), or None above horizon."""
        fx = (width / 2) / math.tan(math.radians(self.hfov_deg) / 2)
        cx, cy = width / 2, height / 2
        x1, _, x2, y2 = box
        angle = math.radians(self.pitch_deg) + math.atan((y2 - cy) / fx)
        if angle <= math.radians(0.5):
            return None
        forward = self.height_m / math.tan(angle)
        if forward > MAX_TRUSTED_M:
            return None
        return {"forward_m": forward, "lateral_m": ((x1 + x2) / 2 - cx) * forward / fx,
                "width_m": (x2 - x1) * forward / fx}


def offset_position(lat: float, lon: float, heading_deg: float, forward_m: float, lateral_m: float) -> tuple:
    """Move a GPS fix forward along the heading and sideways (right positive). Local flat approximation, < 50 m."""
    h = math.radians(heading_deg)
    north = forward_m * math.cos(h) - lateral_m * math.sin(h)
    east = forward_m * math.sin(h) + lateral_m * math.cos(h)
    return (lat + north / 111_320.0, lon + east / (111_320.0 * math.cos(math.radians(lat))))


def uncertainty_m(forward_m: float | None) -> float:
    """GPS error plus a distance-proportional share for camera pose and non-flat ground (inference, not measured)."""
    return round(GPS_ERROR_M + 0.15 * (forward_m or 15.0), 1)
