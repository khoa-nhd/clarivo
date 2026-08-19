import re
from .schemas import AnalysisRequest


def _sentences(text: str) -> list[str]:
    values = re.split(r"(?<=[.!?])\s+", text.strip())
    return [value.strip() for value in values if value.strip()]


def run_mock(request: AnalysisRequest) -> tuple[dict, str]:
    words = request.transcript.split()
    sentences = _sentences(request.transcript)
    length = len(words)
    has_example = any(token in request.transcript.lower() for token in ["for example", "for instance", "imagine", "such as"])

    completeness = min(91, 58 + length // 9)
    clarity = 82 if len(sentences) >= 3 else 70
    examples = 84 if has_example else 58

    issues = []
    if not has_example:
        issues.append({
            "category": "examples",
            "severity": "medium",
            "sentence_index": max(1, min(2, len(sentences))) if sentences else 1,
            "sentence": sentences[1] if len(sentences) > 1 else (sentences[0] if sentences else None),
            "problem": "The explanation stays abstract and does not give the learner a concrete example to test the idea against.",
            "suggestion": "Add one short real-world or numerical example immediately after the core definition.",
        })
    if length < 110:
        issues.append({
            "category": "completeness",
            "severity": "medium",
            "sentence_index": 1,
            "sentence": sentences[0] if sentences else None,
            "problem": "The explanation is fairly short, so some important reasoning or context may be missing.",
            "suggestion": "State the core idea, explain why it works, then connect the steps before concluding.",
        })

    return {
        "scores": {
            "correctness": 84,
            "completeness": completeness,
            "logical_flow": 78,
            "clarity": clarity,
            "examples": examples,
            "jumped_steps": 74,
            "audience_fit": 82,
        },
        "issues": issues,
        "top_priorities": [
            "Add one concrete example that makes the central idea testable.",
            "Make the reason behind each major step explicit instead of only naming the step.",
            "End by reconnecting the explanation to the original topic question.",
        ],
        "feedback": (
            "This mock report shows the final UI and queue behavior before a Cloudflare AI token is connected. "
            "The explanation has a clear direction, but it can become easier to learn from by making the reasoning between steps explicit and adding a concrete example."
        ),
    }, "mock-evaluator"
