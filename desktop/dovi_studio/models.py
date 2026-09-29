from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Media:
    path: Path
    identification: dict[str, Any]
    video: dict[str, Any]
    profile: int | None = None
    compatibility: int | None = None
    duration: float = 0
    max_cll: float | None = None
    size: int = 0

    @property
    def track_id(self) -> int:
        return int(self.video["id"])

    @property
    def props(self) -> dict:
        return self.video.get("properties", {})

    @property
    def tracks(self) -> list[dict]:
        return self.identification.get("tracks", [])


@dataclass
class Analysis:
    verdict: str = "unknown"
    reason: str = "Not inspected"
    full: bool = False
    rpu_count: int = 0
    peak_nits: float | None = None
    base_peak_nits: float | None = None
    summary: str = ""


@dataclass
class Options:
    output_dir: str = ""
    temp_dir: str = ""
    mode: str = "p81"
    method: str = "disk"
    include_fel: bool = False
    allow_risky: bool = False
    backup_el: bool = False
    strict_verify: bool = True
    recursive_depth: int = 8
    tool_paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "Options":
        known = cls.__dataclass_fields__
        obj = cls(**{key: val for key, val in value.items() if key in known})
        # Risk overrides are deliberately limited to the current session.
        obj.allow_risky = False
        return obj


@dataclass
class Job:
    path: Path
    root: Path | None = None
    status: str = "Waiting"
    media: Media | None = None
    analysis: Analysis | None = None
    result: str = ""
    checked: bool = True


class OperationError(RuntimeError):
    pass


class Skipped(OperationError):
    pass


class Cancelled(OperationError):
    pass
