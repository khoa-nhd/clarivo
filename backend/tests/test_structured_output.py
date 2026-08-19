from app.cloudflare_provider import _extract_tool_arguments, TOOL_NAME
from legacy_ai.schemas import CompactEvaluation


def sample_evaluation():
    return {
        "scores": {
            "correctness": 90,
            "completeness": 82,
            "logical_flow": 85,
            "clarity": 88,
            "examples": 75,
            "jumped_steps": 84,
            "audience_fit": 91,
        },
        "issues": [
            {
                "category": "clarity",
                "severity": "medium",
                "sentence": 'He said "least squares" without context.',
                "problem": "One transition is ambiguous.",
                "suggestion": "State what quantity is being minimized.",
            }
        ],
        "top_priorities": [
            "Clarify the optimization target",
            "Add one useful example",
            "Strengthen the transition",
        ],
        "overall_feedback": 'Strong explanation with safe embedded "quotes".',
        "revision_guidance": "Clarify the objective before discussing optimization.",
    }


def run_test():
    expected = sample_evaluation()
    cloudflare_payload = {
        "success": True,
        "result": {
            "tool_calls": [
                {
                    "name": TOOL_NAME,
                    "arguments": expected,
                }
            ]
        },
    }
    extracted = _extract_tool_arguments(cloudflare_payload)
    assert extracted == expected
    CompactEvaluation.model_validate(extracted)
    print("structured-output test: OK")


if __name__ == "__main__":
    run_test()
