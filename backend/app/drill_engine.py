from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from pydantic import ValidationError

from .cloudflare_client import CloudflareAIError, run_tool_call

from .schemas import (
    DrillChallenge,
    DrillGenerateRequest,
    DrillGenerateResult,
    FinalizeDrillRequest,
    FinalizeDrillResult,
    QAEvaluateRequest,
    QAEvaluateResult,
    TopicRefreshRequest,
    TopicRefreshResult,
)


class DrillAIError(RuntimeError):
    pass


CHALLENGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "type": {"type": "string", "enum": ["audience", "deep_dive", "broaden"]},
        "label": {"type": "string"},
        "prompt": {"type": "string"},
        "focus": {"type": "string"},
    },
    "required": ["id", "type", "label", "prompt", "focus"],
}


TOPIC_PROFILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "domain": {"type": "string"},
        "difficulty": {"type": "string", "enum": ["Easy", "Medium", "Hard", "Expert"]},
        "recommendedAudience": {"type": "string", "enum": ["Beginner", "Intermediate", "Advanced", "Expert"]},
        "taskDescription": {"type": "string"},
        "preStudyKeywords": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "string"}},
        "referenceContent": {"type": "string"},
    },
    "required": [
        "id", "title", "domain", "difficulty", "recommendedAudience",
        "taskDescription", "preStudyKeywords", "referenceContent",
    ],
}


def _cloudflare_structured(
    *,
    tool_name: str,
    tool_description: str,
    parameters: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2200,
) -> dict[str, Any]:
    """One structured drill request.

    Transport, retry policy and tool-call extraction now live in
    ``cloudflare_client``. This used to retry twice on its own while
    ``_validated_structured_call`` retried twice around it, so a single drill
    step could issue four full-length inference calls before giving up.
    """
    transport = (
        f"\n\nSTRUCTURED OUTPUT: Call the function tool `{tool_name}` exactly once. "
        "Return the complete result only through its tool arguments. Do not output markdown or free-form JSON."
    )
    try:
        structured, _raw, _model = run_tool_call(
            tool_name=tool_name,
            tool_description=tool_description,
            parameters=parameters,
            system_prompt=system_prompt + transport,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            retry_prompts=["Retry: obey the function schema exactly."],
        )
    except CloudflareAIError as exc:
        raise DrillAIError(str(exc)) from exc
    if structured is None:
        raise DrillAIError("The model did not return the required structured tool call.")
    return structured


def _validated_structured_call(
    *,
    model_cls,
    tool_name: str,
    tool_description: str,
    parameters: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2200,
):
    """Request a structured result and validate it against ``model_cls``.

    The transport layer already retries a missing or malformed tool call. This
    adds exactly one further attempt, for the different failure of a well-formed
    tool call whose *contents* violate the schema, with a prompt that says so.
    """
    last_error: Exception | None = None
    for attempt in range(2):
        effective_prompt = user_prompt
        if attempt:
            effective_prompt += (
                "\n\nVALIDATION RETRY: The prior structured arguments violated the required schema. "
                "Return every required field with the exact types and constraints."
            )
        raw = _cloudflare_structured(
            tool_name=tool_name,
            tool_description=tool_description,
            parameters=parameters,
            system_prompt=system_prompt,
            user_prompt=effective_prompt,
            max_tokens=max_tokens,
        )
        try:
            return model_cls.model_validate(raw)
        except ValidationError as exc:
            last_error = exc
    raise DrillAIError("The model could not return a valid structured response after retry.") from last_error


def _main_context(request: DrillGenerateRequest) -> str:
    issue_text = []
    for issue in request.main_issues[:6]:
        if isinstance(issue, dict):
            problem = str(issue.get("problem") or "").strip()
            category = str(issue.get("category") or "content").strip()
            if problem:
                issue_text.append(f"- {category}: {problem}")
    return "\n".join(issue_text) or "- No major issue list was provided."


def _main_quality_guard(request: DrillGenerateRequest) -> tuple[bool, str, int, list[str]]:
    values = [float(v) for v in request.main_scores.values() if isinstance(v, (int, float))]
    overall = sum(values) / len(values) if values else 0.0
    correctness = float(request.main_scores.get("correctness", overall))
    completeness = float(request.main_scores.get("completeness", overall))
    high_issues = sum(
        1 for issue in request.main_issues
        if isinstance(issue, dict) and str(issue.get("severity", "")).lower() == "high"
    )
    weak_areas = [
        str(issue.get("problem") or issue.get("suggestion") or "").strip()
        for issue in request.main_issues[:6]
        if isinstance(issue, dict) and str(issue.get("problem") or issue.get("suggestion") or "").strip()
    ]

    too_weak = (
        correctness <= 45
        or overall <= 45
        or high_issues >= 3
        or (correctness <= 55 and completeness <= 40)
    )
    if not too_weak:
        return False, "", int(round(max(0, min(100, overall)))), weak_areas

    reasons = []
    if correctness <= 45:
        reasons.append("too many correctness problems")
    if completeness <= 40:
        reasons.append("the explanation is too incomplete")
    if high_issues >= 3:
        reasons.append("several high-severity issues need revision")
    if not reasons:
        reasons.append("the main explanation needs substantial revision")
    reason = (
        "Clarivo is skipping follow-up Q&A because " + ", ".join(reasons) + ". "
        "Revise the main transcript/explanation first, then re-analyze it before doing the drill."
    )
    return True, reason, int(round(max(0, min(45, overall)))), weak_areas[:6]


def _mock_challenges() -> list[dict[str, Any]]:
    return [
        {
            "id": "a-audience",
            "type": "audience",
            "label": "Audience question",
            "prompt": "I'm still a little unsure about the main idea. Could you give me one simple example of how it works?",
            "focus": "Clarify one key idea with one audience-friendly example.",
        },
        {
            "id": "b-deep",
            "type": "deep_dive",
            "label": "Deep dive",
            "prompt": "What is the main reason the core mechanism you described works?",
            "focus": "Explain one underlying mechanism.",
        },
        {
            "id": "c-broaden",
            "type": "broaden",
            "label": "Broaden",
            "prompt": "Where is one practical situation in which this idea is useful?",
            "focus": "Connect the topic to one application.",
        },
    ]


def generate_initial_drills(request: DrillGenerateRequest) -> DrillGenerateResult:
    skip, skip_reason, coverage_seed, weak_areas = _main_quality_guard(request)
    if skip:
        return DrillGenerateResult(
            challenges=[],
            core_concepts_coverage=coverage_seed,
            weak_areas=weak_areas or ["Revise the main explanation before follow-up practice."],
            coverage_status="developing",
            drill_recommended=False,
            skip_reason=skip_reason,
        )

    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return DrillGenerateResult(
            challenges=_mock_challenges(),
            core_concepts_coverage=max(62, coverage_seed),
            weak_areas=weak_areas[:4] or ["Clarify one core mechanism", "Add one concrete application"],
            coverage_status="developing",
            drill_recommended=True,
            skip_reason="",
        )

    params = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "challenges": {"type": "array", "minItems": 3, "maxItems": 3, "items": CHALLENGE_SCHEMA},
            "core_concepts_coverage": {"type": "integer", "minimum": 0, "maximum": 100},
            "weak_areas": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
            "coverage_status": {"type": "string", "enum": ["developing", "satisfactory"]},
            "drill_recommended": {"type": "boolean"},
            "skip_reason": {"type": "string"},
        },
        "required": [
            "challenges", "core_concepts_coverage", "weak_areas", "coverage_status",
            "drill_recommended", "skip_reason",
        ],
    }
    system = """You are Clarivo's Interactive Drill Generator.
The Main Evaluator already scored the long presentation. Do NOT rescore it.
Generate exactly three short single-focus challenges: audience, deep_dive, broaden.

CRITICAL AUDIENCE-QUESTION STYLE:
- It must sound like a REAL person in the selected audience asking during/after a presentation.
- Write it as a natural question ending in '?'.
- It may show confusion, curiosity, a practical concern, or ask for one simple clarification.
- Do NOT write instructor commands such as 'Explain...', 'Describe...', 'Analyze...', 'Discuss...', or 'Tell me...'.
Examples:
Beginner: "I'm not sure I understand what auxiliary memory means here. Could you give me one simple example?"
Intermediate: "Why does this step need extra memory instead of reusing the original array?"
Expert: "How does this behave when the input is already nearly sorted?"

SINGLE-FOCUS CONSTRAINT: every challenge asks about exactly one concept, mechanism, weakness, connection, example, assumption, or application. Never combine two questions with 'and'.
Ground the questions in the reference, transcript, and Main Evaluator issues. Prefer unresolved weaknesses.
The application has already filtered out presentations that are too poor for useful follow-up Q&A, so drill_recommended should normally be true here."""
    user = f"""Topic: {request.topic}
Audience: {request.target_audience}

REFERENCE CONTENT:
{(request.reference_content or 'No explicit reference supplied.')[:14000]}

MAIN PRESENTATION TRANSCRIPT:
{request.transcript[:14000]}

MAIN EVALUATOR SCORES:
{json.dumps(request.main_scores, ensure_ascii=False)}

MAIN EVALUATOR WEAKNESSES:
{_main_context(request)}

Create one A audience question, one B deep-dive question, and one C broaden question. Each must be answerable in 30-60 seconds."""
    result = _validated_structured_call(
        model_cls=DrillGenerateResult,
        tool_name="submit_initial_drills",
        tool_description="Submit three grounded single-focus Clarivo drill challenges.",
        parameters=params,
        system_prompt=system,
        user_prompt=user,
    )
    data = result.model_dump()
    data["drill_recommended"] = True
    data["skip_reason"] = ""
    return DrillGenerateResult.model_validate(data)


def _history_text(request: QAEvaluateRequest) -> str:
    rows = []
    for item in request.history[-6:]:
        rows.append(
            f"Round {item.round_number} [{item.challenge_type}]: Q={item.question}\nA={item.answer}\nScores={json.dumps(item.scores)}\nFeedback={item.feedback}"
        )
    return "\n\n".join(rows) or "No previous Q&A rounds."


def _qa_score_only(request: QAEvaluateRequest) -> dict[str, Any]:
    """Score the CURRENT question+answer only.

    Deliberately excludes main-presentation transcript, prior scores, weak areas,
    coverage, and Q&A history so the Q&A score cannot be contaminated by earlier work.
    """
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return {
            "scores": {"accuracy": 84, "directness": 86, "consistency": 82, "relevance": 88, "audience_fit": 80},
            "overall_score": 84,
            "feedback": "This score is based only on the selected Q&A question and this answer.",
            "strength": "You answered the selected question directly.",
            "improvement": "Add one precise supporting detail to make the answer stronger.",
        }

    score_properties = {
        key: {"type": "integer", "minimum": 0, "maximum": 100}
        for key in ["accuracy", "directness", "consistency", "relevance", "audience_fit"]
    }
    params = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scores": {
                "type": "object", "additionalProperties": False,
                "properties": score_properties, "required": list(score_properties),
            },
            "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "feedback": {"type": "string"},
            "strength": {"type": "string"},
            "improvement": {"type": "string"},
        },
        "required": ["scores", "overall_score", "feedback", "strength", "improvement"],
    }
    system = """You are Clarivo's isolated Q&A scorer.
Score ONLY the CURRENT selected question and the CURRENT answer. Do not infer or use anything from the user's main presentation, earlier Q&A rounds, earlier scores, earlier weaknesses, or coverage state.
The only outside grounding allowed is the topic reference needed to judge factual accuracy.

Score exactly five criteria:
1) Accuracy: factual correctness against the reference.
2) Directness: how directly this answer addresses this one question.
3) Consistency: INTERNAL consistency of this answer with itself; do NOT compare it with any previous presentation or answer.
4) Relevance: stays on this exact question.
5) Audience Fit: wording and depth fit the selected audience.

The overall_score must be derived only from these five current-answer scores. Prior work must have zero influence on these scores."""
    user = f"""Topic: {request.topic}
Audience: {request.target_audience}

REFERENCE CONTENT (accuracy grounding only):
{(request.reference_content or 'No explicit reference supplied.')[:13000]}

CURRENT QUESTION:
{request.selected_challenge.prompt}
Single focus: {request.selected_challenge.focus}

CURRENT ANSWER:
{request.answer_transcript[:8000]}

Score only this question-answer pair."""
    raw = _cloudflare_structured(
        tool_name="submit_isolated_qa_score",
        tool_description="Submit the isolated five-criterion score for this Q&A answer only.",
        parameters=params,
        system_prompt=system,
        user_prompt=user,
        max_tokens=1500,
    )
    try:
        scores = raw.get("scores") or {}
        required = ["accuracy", "directness", "consistency", "relevance", "audience_fit"]
        if not all(isinstance(scores.get(key), (int, float)) for key in required):
            raise ValueError("Missing Q&A score fields")
        normalized = {key: max(0, min(100, int(round(float(scores[key]))))) for key in required}
        overall = int(round(sum(normalized.values()) / len(normalized)))
        return {
            "scores": normalized,
            "overall_score": overall,
            "feedback": str(raw.get("feedback") or "").strip() or "Q&A answer evaluated.",
            "strength": str(raw.get("strength") or "").strip(),
            "improvement": str(raw.get("improvement") or "").strip(),
        }
    except Exception as exc:
        raise DrillAIError("The Q&A scorer returned an invalid structured result.") from exc


def _followup_style_instruction(challenge_type: str, audience: str) -> str:
    if challenge_type == "audience":
        return f"""Create exactly ONE new audience question for a {audience} listener.
It must sound like a real audience member speaking naturally, not an instructor giving a task.
Use a genuine listener voice: confusion, curiosity, practical concern, or one clarification.
It MUST end with '?'. Never start with Explain, Describe, Analyze, Discuss, Define, Tell me, or Give me.
Ask only one thing."""
    if challenge_type == "deep_dive":
        return "Create exactly ONE new deep-dive question about one mechanism, cause, assumption, or reasoning step. Ask only one thing."
    return "Create exactly ONE new broaden question connecting the topic to one application, neighboring idea, or practical context. Ask only one thing."


def _update_learning_state(request: QAEvaluateRequest, qa_score: dict[str, Any]) -> dict[str, Any]:
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    stop_for_round_limit = request.current_round >= request.max_rounds
    if provider == "mock":
        coverage = min(96, max(request.prior_coverage, 55) + (10 if qa_score["overall_score"] >= 70 else 3))
        stop = stop_for_round_limit or coverage >= 95
        next_challenges = []
        if not stop:
            same_type = request.selected_challenge.type
            mock = next(item for item in _mock_challenges() if item["type"] == same_type).copy()
            mock["id"] = f"{same_type}-{uuid.uuid4().hex[:8]}"
            if same_type == "audience":
                mock["prompt"] = "I understand the basic idea, but what would I actually notice if this part worked differently?"
            next_challenges = [mock]
        return {
            "core_concepts_coverage": coverage,
            "resolved_weak_areas": request.prior_weak_areas[:1] if qa_score["overall_score"] >= 75 else [],
            "remaining_weak_areas": request.prior_weak_areas[1:] if qa_score["overall_score"] >= 75 else request.prior_weak_areas,
            "coverage_status": "satisfactory" if stop and coverage >= 85 else "developing",
            "should_stop": stop,
            "stop_reason": "Maximum rounds reached." if stop_for_round_limit else ("Coverage is satisfactory." if stop else "Continue with another question of the same type."),
            "next_challenges": next_challenges,
            "final_summary": None,
        }

    summary_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "key_strengths": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
            "remaining_gaps": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
            "qna_progress": {"type": "string"},
            "next_steps": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
        },
        "required": ["key_strengths", "remaining_gaps", "qna_progress", "next_steps"],
    }
    params = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "core_concepts_coverage": {"type": "integer", "minimum": 0, "maximum": 100},
            "resolved_weak_areas": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "remaining_weak_areas": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            "coverage_status": {"type": "string", "enum": ["developing", "satisfactory"]},
            "should_stop": {"type": "boolean"},
            "stop_reason": {"type": "string"},
            "next_challenges": {"type": "array", "maxItems": 1, "items": CHALLENGE_SCHEMA},
            "final_summary": summary_schema,
        },
        "required": [
            "core_concepts_coverage", "resolved_weak_areas", "remaining_weak_areas",
            "coverage_status", "should_stop", "stop_reason", "next_challenges", "final_summary",
        ],
    }
    system = f"""You are Clarivo's learning-state updater. The CURRENT Q&A score has already been computed independently. NEVER change or reinterpret that score.
Use the answer, reference, prior coverage, prior weak areas, and history only to update learning coverage and decide the next practice action.

Rules:
- Resolve a weak area only if the current answer actually addressed it correctly.
- Stop if current_round reaches max_rounds or coverage is genuinely satisfactory.
- If continuing, create EXACTLY ONE new challenge, and it MUST be the SAME TYPE as the challenge just answered: {request.selected_challenge.type}.
- Do not regenerate the other two types. The UI keeps those existing questions.
- Avoid repeating a previously asked focus.
- Every challenge is single-focus.
{_followup_style_instruction(request.selected_challenge.type, request.target_audience)}
If stopping, next_challenges must be empty and provide a real final_summary. If continuing, next_challenges must contain exactly one challenge and final_summary should be empty."""
    user = f"""Topic: {request.topic}
Audience: {request.target_audience}
Current round: {request.current_round}/{request.max_rounds}
Prior coverage: {request.prior_coverage}%
Prior weak areas: {json.dumps(request.prior_weak_areas, ensure_ascii=False)}

REFERENCE:
{(request.reference_content or 'No explicit reference supplied.')[:12000]}

JUST-ANSWERED CHALLENGE [{request.selected_challenge.type}]:
{request.selected_challenge.prompt}
Focus: {request.selected_challenge.focus}

CURRENT ANSWER:
{request.answer_transcript[:7000]}

ISOLATED CURRENT Q&A SCORE (already final; do not alter):
{json.dumps(qa_score, ensure_ascii=False)}

PREVIOUS Q&A HISTORY (for non-repetition and coverage only; never use it to change the current Q&A score):
{_history_text(request)[:9000]}

Update coverage and, if continuing, return one new {request.selected_challenge.type} challenge only."""
    raw = _cloudflare_structured(
        tool_name="submit_learning_state_update",
        tool_description="Update coverage and optionally return one same-type follow-up question.",
        parameters=params,
        system_prompt=system,
        user_prompt=user,
        max_tokens=2200,
    )

    try:
        stop = bool(raw.get("should_stop")) or stop_for_round_limit
        next_items = raw.get("next_challenges") if isinstance(raw.get("next_challenges"), list) else []
        if stop:
            next_items = []
        else:
            if len(next_items) != 1:
                raise ValueError("Expected exactly one next challenge while continuing")
            challenge = DrillChallenge.model_validate(next_items[0])
            if challenge.type != request.selected_challenge.type:
                raise ValueError("Next challenge type did not match selected type")
            next_items = [challenge.model_dump()]
        return {
            "core_concepts_coverage": max(0, min(100, int(raw.get("core_concepts_coverage", request.prior_coverage)))),
            "resolved_weak_areas": [str(x) for x in (raw.get("resolved_weak_areas") or [])][:8],
            "remaining_weak_areas": [str(x) for x in (raw.get("remaining_weak_areas") or [])][:8],
            "coverage_status": "satisfactory" if str(raw.get("coverage_status")) == "satisfactory" else "developing",
            "should_stop": stop,
            "stop_reason": "Maximum drill rounds reached." if stop_for_round_limit else str(raw.get("stop_reason") or ""),
            "next_challenges": next_items,
            "final_summary": raw.get("final_summary"),
        }
    except (ValueError, ValidationError) as exc:
        raise DrillAIError("The learning-state updater could not generate a valid same-type follow-up.") from exc


def _default_final_summary(qa_score: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return {
        "key_strengths": [qa_score.get("strength")] if qa_score.get("strength") else [],
        "remaining_gaps": list(state.get("remaining_weak_areas") or [])[:5],
        "qna_progress": qa_score.get("feedback") or "",
        "next_steps": list(state.get("remaining_weak_areas") or [])[:3] or ["Try another topic from the Topic Library."],
    }


def evaluate_qa_round(request: QAEvaluateRequest) -> QAEvaluateResult:
    # IMPORTANT: scoring and learning-state updates are two separate calls so prior
    # presentation/history cannot leak into the current Q&A score.
    qa_score = _qa_score_only(request)
    state = _update_learning_state(request, qa_score)

    final_summary = state.get("final_summary")
    if state["should_stop"]:
        if not isinstance(final_summary, dict) or not any(final_summary.values()):
            final_summary = _default_final_summary(qa_score, state)
    else:
        final_summary = None

    return QAEvaluateResult.model_validate({
        **qa_score,
        "core_concepts_coverage": state["core_concepts_coverage"],
        "resolved_weak_areas": state["resolved_weak_areas"],
        "remaining_weak_areas": state["remaining_weak_areas"],
        "coverage_status": state["coverage_status"],
        "should_stop": state["should_stop"],
        "stop_reason": state["stop_reason"],
        "next_challenges": state["next_challenges"],
        "final_summary": final_summary,
    })


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text[:70] or uuid.uuid4().hex[:10]


def _mock_refreshed_topics(count: int) -> list[dict[str, Any]]:
    seeds = [
        ("Explain Binary Search", "Data Structures & Algorithms", "Easy", "Beginner", ["Sorted array", "Search interval", "Midpoint", "O(log n)"], "Binary search repeatedly halves a sorted search range by comparing the target with the middle element. It runs in O(log n) time when random access is available and requires the data to be ordered under the same comparison rule."),
        ("Explain Gradient Descent", "Machine Learning", "Medium", "Intermediate", ["Loss function", "Gradient", "Learning rate", "Convergence"], "Gradient descent iteratively updates parameters in the direction opposite the gradient of an objective. The learning rate controls step size; steps that are too large may diverge, while very small steps converge slowly."),
        ("Explain DNA Replication", "Biology", "Medium", "Intermediate", ["DNA polymerase", "Helicase", "Leading strand", "Lagging strand"], "DNA replication copies DNA before cell division. Helicase separates the strands, primase creates primers, and DNA polymerases synthesize new DNA in the 5-prime to 3-prime direction, with different mechanics on leading and lagging strands."),
        ("Explain Confidence Intervals", "Statistics", "Medium", "Intermediate", ["Estimator", "Standard error", "Confidence level", "Margin of error"], "A confidence interval is produced by a procedure that, under its assumptions, captures the target parameter at a stated long-run rate such as 95%. It is not generally a 95% probability that a fixed parameter lies in one already-computed frequentist interval."),
        ("Explain Hash Tables", "Data Structures & Algorithms", "Medium", "Intermediate", ["Hash function", "Collision", "Load factor", "Expected O(1)"], "A hash table maps keys to array positions with a hash function. Collisions are handled with schemes such as chaining or open addressing. Average operations can be O(1) under suitable hashing and load, while worst-case behavior can degrade."),
        ("Explain Backpropagation", "Machine Learning", "Hard", "Advanced", ["Chain rule", "Computational graph", "Gradient", "Parameter update"], "Backpropagation efficiently computes derivatives through a computational graph by applying the chain rule from outputs toward earlier operations. It computes gradients; an optimizer then uses those gradients to update parameters."),
    ]
    out = []
    for title, domain, difficulty, audience, keywords, reference in seeds[:count]:
        out.append({
            "id": f"refresh-{_slug(title)}-{uuid.uuid4().hex[:6]}",
            "title": title,
            "domain": domain,
            "difficulty": difficulty,
            "recommendedAudience": audience,
            "taskDescription": f"Explain {title.replace('Explain ', '')} clearly, including the core mechanism, one important limitation or condition, and one concrete example where appropriate.",
            "preStudyKeywords": keywords,
            "referenceContent": reference,
        })
    return out


def refresh_topics(request: TopicRefreshRequest) -> TopicRefreshResult:
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return TopicRefreshResult(topics=_mock_refreshed_topics(request.count))

    params = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "topics": {
                "type": "array",
                "minItems": request.count,
                "maxItems": request.count,
                "items": TOPIC_PROFILE_SCHEMA,
            }
        },
        "required": ["topics"],
    }
    system = """You generate fresh Clarivo Topic Library practice profiles.
Return diverse educational topics appropriate for students and technical learners. Each topic must be self-contained and factually grounded.
Requirements per topic:
- concise title beginning with 'Explain' or a clear 'Why ...' explanation task
- domain
- difficulty Easy/Medium/Hard/Expert
- recommended audience Beginner/Intermediate/Advanced/Expert
- task description specifying what to explain
- 3-5 pre-study keywords
- compact but authoritative reference content (roughly 100-220 words) covering definition/mechanism, critical caveats, and key facts needed for evaluation
Avoid duplicate or near-duplicate topics from the excluded list. Do not include current events or unstable facts."""
    excluded = "\n".join(f"- {title}" for title in request.exclude_titles[-30:]) or "- none"
    user = f"""Generate exactly {request.count} new topic profiles.
Do not repeat these existing/recent titles:
{excluded}

Use a varied mix across computer science, mathematics/statistics, science, and technology. Make each reference content sufficient to ground Clarivo's evaluator."""
    result = _validated_structured_call(
        model_cls=TopicRefreshResult,
        tool_name="submit_topic_refresh",
        tool_description="Submit a refreshed set of grounded Clarivo Topic Library profiles.",
        parameters=params,
        system_prompt=system,
        user_prompt=user,
        max_tokens=4200,
    )
    # Replace model-generated IDs with collision-resistant, UI-safe IDs.
    data = result.model_dump()
    for topic in data["topics"]:
        topic["id"] = f"refresh-{_slug(topic['title'])}-{uuid.uuid4().hex[:6]}"
    return TopicRefreshResult.model_validate(data)


def finalize_drill(request: FinalizeDrillRequest) -> FinalizeDrillResult:
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return FinalizeDrillResult(
            coverage_status="satisfactory" if request.core_concepts_coverage >= 85 else "developing",
            core_concepts_coverage=request.core_concepts_coverage,
            final_summary={
                "key_strengths": ["Completed the main explanation", "Practiced follow-up reasoning"],
                "remaining_gaps": request.remaining_weak_areas[:5],
                "qna_progress": "The drill history is saved with this session.",
                "next_steps": request.remaining_weak_areas[:3] or ["Try a related topic from the library."],
            },
        )

    summary_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "coverage_status": {"type": "string", "enum": ["developing", "satisfactory"]},
            "core_concepts_coverage": {"type": "integer", "minimum": 0, "maximum": 100},
            "final_summary": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "key_strengths": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
                    "remaining_gaps": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
                    "qna_progress": {"type": "string"},
                    "next_steps": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
                },
                "required": ["key_strengths", "remaining_gaps", "qna_progress", "next_steps"],
            },
        },
        "required": ["coverage_status", "core_concepts_coverage", "final_summary"],
    }
    system = """You are Clarivo's Final Learning Summary engine. Summarize the user's main explanation and Q&A history without inventing mastery. Return concise key strengths, remaining unresolved gaps, Q&A progress, and actionable next steps. Coverage status means evidence gathered in this session only."""
    history = "\n\n".join(
        f"Round {item.round_number}: Q={item.question}\nA={item.answer}\nScores={json.dumps(item.scores)}\nFeedback={item.feedback}"
        for item in request.history[-6:]
    ) or "No Q&A rounds completed."
    user = f"""Topic: {request.topic}
Audience: {request.target_audience}
Current coverage: {request.core_concepts_coverage}%
Remaining weak areas: {json.dumps(request.remaining_weak_areas, ensure_ascii=False)}

REFERENCE:
{(request.reference_content or 'No explicit reference supplied.')[:12000]}

MAIN TRANSCRIPT:
{request.main_transcript[:10000]}

Q&A HISTORY:
{history[:12000]}

Create a concise final learning summary based only on evidence from this session."""
    return _validated_structured_call(
        model_cls=FinalizeDrillResult,
        tool_name="submit_final_learning_summary",
        tool_description="Submit Clarivo's final session learning summary.",
        parameters=summary_schema,
        system_prompt=system,
        user_prompt=user,
        max_tokens=1800,
    )
