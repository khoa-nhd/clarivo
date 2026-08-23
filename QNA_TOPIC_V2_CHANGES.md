# Clarivo Q&A + Topic Library v2

This build implements the requested learning-loop refinements on top of the existing Clarivo Content / Voice / Visual pipeline.

## Q&A scoring isolation

The current Q&A score is computed in a dedicated first AI call using only:

- topic
- selected audience
- reference content (Accuracy grounding only)
- the selected Q&A question
- the current Q&A answer

It does **not** receive the main presentation transcript, main scores, prior weak areas, prior coverage, or previous Q&A history.

`Consistency` now means **internal consistency of the current answer**, not consistency with the main presentation.

A second AI call updates coverage, weak areas, stopping, and the next challenge. Previous history is allowed only in this second call.

## Overall after Q&A

The UI stores a score snapshot after every Q&A round:

- `mainOverall`: mean of the 7 Main Evaluator scores
- `qaAverage`: mean of Q&A overall scores completed so far
- `overallDelta`: 20% of `(qaAverage - mainOverall)`, capped to `-8 ... +8`
- `overallAfterQA = mainOverall + overallDelta`

This keeps the full presentation as the primary score while allowing Q&A to visibly improve or reduce the learning overall.

## Same-type replacement

The challenge grid always aims to keep one question per type:

- A — Audience question
- B — Deep dive
- C — Broaden

When the user answers A, only A is replaced with a new Audience question. B and C remain unchanged. The same rule applies to B and C.

## Audience-question style

Audience questions are validated to sound like real listener questions. They must end with `?` and cannot start with instructor-style commands such as `Explain`, `Describe`, `Analyze`, `Discuss`, `Define`, `Tell me`, or `Give me`.

## Skip Q&A for a severely flawed main explanation

The backend deterministically skips follow-up generation when the main explanation is not ready for useful probing. Current conservative guard:

- Correctness <= 45, or
- mean Main Evaluator score <= 45, or
- 3+ high-severity issues, or
- Correctness <= 55 and Completeness <= 40

The UI shows **Revise before Q&A** instead of inventing follow-up questions.

## Refresh Topic Library

New endpoint:

`POST /api/topics/refresh`

The Topic Library now has a **Refresh topics** button. Cloudflare/Qwen generates a fresh set of grounded Topic Profiles with:

- title
- domain
- difficulty
- recommended audience
- task description
- 3–5 pre-study keywords
- reference content

The refreshed set is saved in browser `localStorage` so it survives refreshes.
