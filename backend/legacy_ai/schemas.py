from __future__ import annotations
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"

Category = Literal[
    "correctness", "completeness", "logical_flow", "clarity",
    "examples", "jumped_steps", "audience_fit"
]

class AnalysisInput(StrictModel):
    topic: str = Field(min_length=1)
    reference_content: str | None = None
    target_audience: str = Field(min_length=1)
    transcript: str = Field(min_length=1)

    @field_validator("topic", "target_audience", "transcript")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank.")
        return value

    @field_validator("reference_content")
    @classmethod
    def normalize_optional_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

class Scores(StrictModel):
    correctness: int = Field(ge=0, le=100)
    completeness: int = Field(ge=0, le=100)
    logical_flow: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    examples: int = Field(ge=0, le=100)
    jumped_steps: int = Field(ge=0, le=100)
    audience_fit: int = Field(ge=0, le=100)

class Issue(StrictModel):
    category: Category
    severity: Severity

    sentence: str | None = Field(
        default=None,
        description=(
            "The full exact transcript sentence related to this issue. "
            "Use null if the issue applies to the explanation as a whole."
        )
    )

    problem: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)

class DimensionEvidence(StrictModel):
    """Why one dimension received the score it did.

    Optional throughout. The seven scores stay the contract; this is
    supplementary justification, and a model that omits it must not turn a
    usable evaluation into a failure and a second paid retry.
    """

    evidence: list[str] = Field(default_factory=list, max_length=3)
    reasoning: str = ""
    confidence: Literal["high", "medium", "low", "insufficient_evidence"] | None = None


class ReferenceCheck(StrictModel):
    """Explicit transcript-versus-reference comparison.

    ``unsupported_by_reference`` is claims the transcript makes that the
    reference neither confirms nor denies - useful to the presenter, and not the
    same thing as being wrong.
    """

    reference_available: bool = False
    supported_claims: list[str] = Field(default_factory=list, max_length=5)
    missing_from_transcript: list[str] = Field(default_factory=list, max_length=5)
    contradicted_by_reference: list[str] = Field(default_factory=list, max_length=5)
    unsupported_by_reference: list[str] = Field(default_factory=list, max_length=5)


class CompactEvaluation(StrictModel):
    scores: Scores
    issues: list[Issue] = Field(default_factory=list, max_length=12)
    top_priorities: list[str] = Field(min_length=1, max_length=5)
    overall_feedback: str = Field(min_length=1)
    revision_guidance: str = Field(min_length=1)
    dimension_evidence: dict[Category, DimensionEvidence] | None = None
    reference_check: ReferenceCheck | None = None
