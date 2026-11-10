"""Typed results each specialist must return. Validated on every run; one self-correction, then the fallback."""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

Severity = Literal["low", "medium", "high"]


class VisionItem(BaseModel):
    event_id: str
    verdict: Literal["confirmed", "disputed", "rejected"]
    severity: Severity | None = None
    rationale: str = Field(max_length=400)


class VisionResult(BaseModel):
    events: list[VisionItem]


class LocationItem(BaseModel):
    event_id: str
    jurisdiction: str = Field(max_length=80)
    confidence: Literal["high", "medium", "low"]
    rationale: str = Field(max_length=400)


class LocationResult(BaseModel):
    events: list[LocationItem]


class TriageItem(BaseModel):
    event_id: str
    report_id: int | None = None
    action: Literal["created", "merged", "already_linked", "skipped"]
    rationale: str = Field(max_length=400)


class TriageResult(BaseModel):
    reports: list[TriageItem]


class FilingItem(BaseModel):
    report_id: int
    outcome: Literal["drafted", "submitted", "failed"]
    detail: str = Field(default="", max_length=600)


class FilingResult(BaseModel):
    reports: list[FilingItem]


class FollowUpResult(BaseModel):
    checked: int
    fixed: list[int] = []


def extract_json(text: str) -> dict:
    """The JSON object in a model answer (tolerates ```json fences and surrounding prose)."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[start:end + 1])


def validate(model: type[BaseModel], text: str) -> tuple[BaseModel | None, str | None]:
    try:
        return model.model_validate(extract_json(text)), None
    except (ValueError, ValidationError) as e:
        return None, str(e)[:600]
