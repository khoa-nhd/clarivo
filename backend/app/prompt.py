"""Adapter around the evaluator prompt copied from the user's old project.

Do not edit the rubric here. The original, already-tuned prompt lives in
backend/legacy_ai/prompt_builder.py and is intentionally preserved.
"""

from legacy_ai.prompt_builder import PROMPT_VERSION, build_prompts
from legacy_ai.schemas import AnalysisInput
from .schemas import AnalysisRequest


def build_evaluation_prompts(request: AnalysisRequest) -> tuple[str, str, str]:
    legacy_input = AnalysisInput(
        topic=request.topic,
        reference_content=request.reference_content,
        target_audience=request.target_audience,
        transcript=request.transcript,
    )
    system_prompt, user_prompt = build_prompts(legacy_input)
    return system_prompt, user_prompt, PROMPT_VERSION
