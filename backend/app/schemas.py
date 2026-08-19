from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class AnalysisRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    target_audience: str = Field(default="Beginner", min_length=1, max_length=120)
    transcript: str = Field(min_length=20, max_length=30_000)
    reference_content: str | None = Field(default=None, max_length=30_000)

    @field_validator("topic", "target_audience", "transcript")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank.")
        return value

    @field_validator("reference_content")
    @classmethod
    def strip_optional_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class Scores(BaseModel):
    correctness: int = Field(ge=0, le=100)
    completeness: int = Field(ge=0, le=100)
    logical_flow: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    examples: int = Field(ge=0, le=100)
    jumped_steps: int = Field(ge=0, le=100)
    audience_fit: int = Field(ge=0, le=100)


class Issue(BaseModel):
    category: str
    severity: Literal["low", "medium", "high"] | str
    sentence: str | None = None
    problem: str
    suggestion: str


class AnalysisMeta(BaseModel):
    provider: str
    model: str
    prompt_version: str | None = None


class AnalysisResult(BaseModel):
    scores: Scores
    issues: list[Issue]
    top_priorities: list[str] = Field(min_length=1, max_length=5)
    feedback: str
    revision_guidance: str | None = None
    meta: AnalysisMeta | None = None

    @field_validator("top_priorities", mode="before")
    @classmethod
    def normalize_priorities(cls, value: Any):
        if not isinstance(value, list):
            return [str(value)]
        return [str(item) for item in value[:5]]


class TranscriptionResult(BaseModel):
    text: str
    word_count: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    mime_type: str
    size_bytes: int = Field(ge=0)
    model: str
    language: Literal["en"] = "en"
