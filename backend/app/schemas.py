from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


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


class DrillChallenge(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    type: Literal["audience", "deep_dive", "broaden"]
    label: str = Field(min_length=1, max_length=60)
    prompt: str = Field(min_length=5, max_length=1000)
    focus: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def audience_must_sound_like_audience(self):
        if self.type != "audience":
            return self
        prompt = self.prompt.strip()
        lowered = prompt.lower()
        bad_starts = ("explain ", "describe ", "analyze ", "discuss ", "define ", "tell me ", "give me ")
        if not prompt.endswith("?") or lowered.startswith(bad_starts):
            raise ValueError(
                "Audience questions must sound like a real listener asking a natural question, not an instructor command."
            )
        return self


class DrillGenerateRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    target_audience: str = Field(min_length=1, max_length=120)
    transcript: str = Field(min_length=20, max_length=30_000)
    reference_content: str | None = Field(default=None, max_length=30_000)
    main_scores: dict[str, int] = Field(default_factory=dict)
    main_issues: list[dict[str, Any]] = Field(default_factory=list)


class DrillGenerateResult(BaseModel):
    challenges: list[DrillChallenge] = Field(default_factory=list, max_length=3)
    core_concepts_coverage: int = Field(ge=0, le=100)
    weak_areas: list[str] = Field(default_factory=list, max_length=6)
    coverage_status: Literal["developing", "satisfactory"] = "developing"
    drill_recommended: bool = True
    skip_reason: str = Field(default="", max_length=800)


class QAScores(BaseModel):
    accuracy: int = Field(ge=0, le=100)
    directness: int = Field(ge=0, le=100)
    consistency: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    audience_fit: int = Field(ge=0, le=100)


class QARoundHistoryItem(BaseModel):
    round_number: int = Field(ge=1, le=20)
    challenge_type: str = Field(max_length=80)
    question: str = Field(max_length=1500)
    answer: str = Field(max_length=10_000)
    scores: dict[str, int] = Field(default_factory=dict)
    feedback: str = Field(default="", max_length=4000)


class QAEvaluateRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    target_audience: str = Field(min_length=1, max_length=120)
    reference_content: str | None = Field(default=None, max_length=30_000)
    selected_challenge: DrillChallenge
    answer_transcript: str = Field(min_length=5, max_length=10_000)
    history: list[QARoundHistoryItem] = Field(default_factory=list, max_length=10)
    current_round: int = Field(ge=1, le=20)
    max_rounds: int = Field(default=3, ge=1, le=5)
    prior_coverage: int = Field(default=0, ge=0, le=100)
    prior_weak_areas: list[str] = Field(default_factory=list, max_length=10)


class FinalLearningSummary(BaseModel):
    key_strengths: list[str] = Field(default_factory=list, max_length=5)
    remaining_gaps: list[str] = Field(default_factory=list, max_length=5)
    qna_progress: str = Field(default="", max_length=4000)
    next_steps: list[str] = Field(default_factory=list, max_length=4)


class QAEvaluateResult(BaseModel):
    scores: QAScores
    overall_score: int = Field(ge=0, le=100)
    feedback: str = Field(min_length=1, max_length=4000)
    strength: str = Field(default="", max_length=1200)
    improvement: str = Field(default="", max_length=1200)
    core_concepts_coverage: int = Field(ge=0, le=100)
    resolved_weak_areas: list[str] = Field(default_factory=list, max_length=8)
    remaining_weak_areas: list[str] = Field(default_factory=list, max_length=8)
    coverage_status: Literal["developing", "satisfactory"]
    should_stop: bool
    stop_reason: str = Field(default="", max_length=500)
    next_challenges: list[DrillChallenge] = Field(default_factory=list, max_length=3)
    final_summary: FinalLearningSummary | None = None


class TopicProfile(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=4, max_length=180)
    domain: str = Field(min_length=2, max_length=100)
    difficulty: Literal["Easy", "Medium", "Hard", "Expert"]
    recommendedAudience: Literal["Beginner", "Intermediate", "Advanced", "Expert"]
    taskDescription: str = Field(min_length=20, max_length=1200)
    preStudyKeywords: list[str] = Field(min_length=3, max_length=5)
    referenceContent: str = Field(min_length=80, max_length=6000)


class TopicRefreshRequest(BaseModel):
    exclude_titles: list[str] = Field(default_factory=list, max_length=30)
    count: int = Field(default=5, ge=3, le=6)


class TopicRefreshResult(BaseModel):
    topics: list[TopicProfile] = Field(min_length=3, max_length=6)


class FinalizeDrillRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    target_audience: str = Field(min_length=1, max_length=120)
    reference_content: str | None = Field(default=None, max_length=30_000)
    main_transcript: str = Field(min_length=20, max_length=30_000)
    history: list[QARoundHistoryItem] = Field(default_factory=list, max_length=10)
    core_concepts_coverage: int = Field(default=0, ge=0, le=100)
    remaining_weak_areas: list[str] = Field(default_factory=list, max_length=10)


class FinalizeDrillResult(BaseModel):
    coverage_status: Literal["developing", "satisfactory"]
    core_concepts_coverage: int = Field(ge=0, le=100)
    final_summary: FinalLearningSummary
