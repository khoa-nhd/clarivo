import os

os.environ.setdefault("AI_PROVIDER", "mock")

from app.drill_engine import evaluate_qa_round, finalize_drill, generate_initial_drills, refresh_topics
from app.schemas import DrillGenerateRequest, FinalizeDrillRequest, QAEvaluateRequest, TopicRefreshRequest


def test_drill_loop_mock():
    main = DrillGenerateRequest(
        topic="Merge Sort",
        target_audience="Beginner",
        transcript="Merge sort divides the input into smaller halves and merges sorted parts back together in O n log n time.",
        reference_content="Merge Sort is divide and conquer, stable, O(n log n), and usually uses O(n) auxiliary memory.",
        main_scores={"correctness": 90, "completeness": 70, "clarity": 80},
        main_issues=[],
    )
    generated = generate_initial_drills(main)
    assert generated.drill_recommended is True
    assert len(generated.challenges) == 3
    assert {item.type for item in generated.challenges} == {"audience", "deep_dive", "broaden"}
    assert generated.challenges[0].prompt.endswith("?")

    selected = next(item for item in generated.challenges if item.type == "audience")
    evaluated = evaluate_qa_round(
        QAEvaluateRequest(
            topic=main.topic,
            target_audience=main.target_audience,
            reference_content=main.reference_content,
            selected_challenge=selected,
            answer_transcript="A simple example is splitting a pile into smaller groups, sorting each group, and combining them in order.",
            history=[],
            current_round=1,
            max_rounds=3,
            prior_coverage=generated.core_concepts_coverage,
            prior_weak_areas=generated.weak_areas,
        )
    )
    assert 0 <= evaluated.overall_score <= 100
    assert set(evaluated.scores.model_dump()) == {"accuracy", "directness", "consistency", "relevance", "audience_fit"}
    assert len(evaluated.next_challenges) == 1
    assert evaluated.next_challenges[0].type == selected.type

    final = finalize_drill(
        FinalizeDrillRequest(
            topic=main.topic,
            target_audience=main.target_audience,
            reference_content=main.reference_content,
            main_transcript=main.transcript,
            history=[],
            core_concepts_coverage=evaluated.core_concepts_coverage,
            remaining_weak_areas=evaluated.remaining_weak_areas,
        )
    )
    assert final.final_summary.next_steps


def test_bad_main_skips_qa():
    poor = DrillGenerateRequest(
        topic="Photosynthesis",
        target_audience="Beginner",
        transcript="Plants use moonlight in their lungs to make caffeine. This is photosynthesis.",
        reference_content="Photosynthesis converts light energy into chemical energy and in plants occurs mainly in chloroplasts.",
        main_scores={"correctness": 20, "completeness": 25, "clarity": 55},
        main_issues=[
            {"category": "correctness", "severity": "high", "problem": "Major factual error"},
            {"category": "correctness", "severity": "high", "problem": "Wrong location"},
            {"category": "completeness", "severity": "high", "problem": "Core mechanism missing"},
        ],
    )
    result = generate_initial_drills(poor)
    assert result.drill_recommended is False
    assert result.challenges == []
    assert result.skip_reason


def test_topic_refresh_mock():
    result = refresh_topics(TopicRefreshRequest(exclude_titles=["Merge Sort"], count=5))
    assert len(result.topics) == 5
    assert all(topic.referenceContent for topic in result.topics)


def test_qa_score_isolated_from_prior_state():
    challenge = {
        "id": "aud-1",
        "type": "audience",
        "label": "Audience question",
        "prompt": "Why would I choose Merge Sort if it needs extra memory?",
        "focus": "One audience concern about the memory trade-off.",
    }
    common = dict(
        topic="Merge Sort",
        target_audience="Intermediate",
        reference_content="Merge Sort is stable and O(n log n), but a typical array implementation uses O(n) auxiliary memory.",
        selected_challenge=challenge,
        answer_transcript="You might choose it when stable ordering and predictable O(n log n) time matter more than the extra O(n) memory.",
        current_round=1,
        max_rounds=3,
    )
    first = evaluate_qa_round(QAEvaluateRequest(
        **common,
        history=[],
        prior_coverage=10,
        prior_weak_areas=["many old problems"],
    ))
    second = evaluate_qa_round(QAEvaluateRequest(
        **common,
        history=[{
            "round_number": 1,
            "challenge_type": "deep_dive",
            "question": "Old question",
            "answer": "Old answer",
            "scores": {"accuracy": 10},
            "feedback": "Old bad result",
        }],
        prior_coverage=95,
        prior_weak_areas=[],
    ))
    assert first.scores == second.scores
    assert first.overall_score == second.overall_score
