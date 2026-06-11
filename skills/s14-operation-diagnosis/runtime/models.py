"""Input and output models for the S14 OpenClaw skill.

OpenClaw should validate requests with references/input_schema.json before
calling the runtime. These models repeat the same contract inside Python.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

try:
    from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
except ImportError:  # pragma: no cover - used only in stripped local test envs
    class BaseModel:  # type: ignore[no-redef]
        def __init__(self, **data: Any):
            annotations = getattr(self, "__annotations__", {})
            for name in annotations:
                if name in data:
                    setattr(self, name, data[name])
                elif hasattr(self.__class__, name):
                    setattr(self, name, getattr(self.__class__, name))
                else:
                    setattr(self, name, None)
            for name, value in data.items():
                if name not in annotations:
                    raise ValueError(f"unexpected field: {name}")
            validator = getattr(self, "validate_dates_and_mode", None)
            if validator:
                validator()

    Field = None  # type: ignore[assignment]
    ValidationError = ValueError  # type: ignore[assignment]

    def field_validator(*_args: Any, **_kwargs: Any):
        def deco(fn: Any) -> Any:
            return fn
        return deco

    def model_validator(*_args: Any, **_kwargs: Any):
        def deco(fn: Any) -> Any:
            return fn
        return deco


Platform = Literal["fliggy", "meituan", "ctrip", "qunar", "douyin", "multi"]
ImageQuality = Literal["good", "average", "poor", "unknown"]
ChannelMode = Literal["single", "multi"]
DataSourceMode = Literal["database", "excel_upload"]


def _field(default: Any = None, **kwargs: Any) -> Any:
    if Field:
        if default is None and "default_factory" in kwargs:
            return Field(**kwargs)
        return Field(default, **kwargs)
    return default


class DiagnosisInput(BaseModel):
    hotel_id: str
    platform: Platform
    period_start: date
    period_end: date
    data_source_mode: DataSourceMode = "database"
    input_excel_path: str | None = None
    hotel_name: str | None = None
    channel_source: str | None = None
    channel_mode: ChannelMode | None = None
    image_quality_rating: ImageQuality = "unknown"
    owner_user_id: str | None = None
    output_dir: str = "./outputs"
    public_base_url: str | None = None
    dry_run: bool = True

    @model_validator(mode="after")
    def validate_dates_and_mode(self) -> "DiagnosisInput":
        if self.period_end < self.period_start:
            raise ValueError("period_end must be greater than or equal to period_start")
        if self.data_source_mode == "excel_upload" and not self.input_excel_path:
            raise ValueError("input_excel_path is required when data_source_mode=excel_upload")
        if self.platform == "multi":
            self.channel_mode = "multi"
            self.channel_source = self.channel_source or "多渠道"
        else:
            self.channel_mode = self.channel_mode or "single"
        return self


class ModuleScore(BaseModel):
    module_id: str
    name: str
    score: float
    weight: float
    confidence: Literal["high", "medium", "low"] = "medium"
    reasons: list[str] = _field(default_factory=list)


class DiagnosisOutput(BaseModel):
    status: Literal["ok", "partial", "failed"]
    skill_id: str = "s14-operation-diagnosis"
    final_score: float
    raw_score: float
    module_scores: list[ModuleScore]
    caps: list[str] = _field(default_factory=list)
    missing_fields: list[dict[str, Any]] = _field(default_factory=list)
    report_url: str
    report_file_path: str
    dry_run: bool = True
