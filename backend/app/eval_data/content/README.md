# Content-evaluator benchmark dataset

Labeled transcripts for `../../content_eval_benchmark.py`, which checks how
closely the Qwen content evaluator's 7 scores agree with a human rater on the
same transcript. This is the semantic-side counterpart to
`local_scoring/eval_data/` (audio/vision).

## How to build cases

15-20 cases is a reasonable target. Reuse real session transcripts (your own
recorded practice sessions, or transcripts you write by hand to hit specific
cases) rather than inventing artificial ones — a benchmark is only useful if
it reflects real usage:

- A few genuinely strong explanations (should score high across the board).
- A few with a clear factual error (should score low on `correctness`).
- A few that skip an important step (`jumped_steps` should catch it).
- A few pitched at the wrong `target_audience` (too advanced for Beginner, or
  overly simplified for Expert).
- A few with no examples at all (`examples` should score low).

For each, save `<case_id>.json` in this folder:

```json
{
  "case_id": "merge_sort_beginner_01",
  "topic": "Explain Merge Sort",
  "target_audience": "Beginner",
  "reference_content": "optional grounding text, same field as Topic Library",
  "transcript": "the presenter's transcript, exactly as the evaluator would receive it",
  "human_scores": {
    "correctness": 80, "completeness": 70, "logical_flow": 75,
    "clarity": 85, "examples": 60, "jumped_steps": 90, "audience_fit": 80
  }
}
```

Rate `human_scores` yourself (or better, have 2 people rate and average) using
the same rubric the product shows the user: correctness, completeness,
logical_flow, clarity, examples, jumped_steps, audience_fit — all 0-100. Omit
any field you're not confident rating; the benchmark only compares fields
that are present.

## Running

From `backend/`, with a real API key configured (`AI_PROVIDER=cloudflare`
and the Cloudflare credentials the product already uses):

```bash
python -m app.content_eval_benchmark
```

`AI_PROVIDER=mock` (the default with no credentials) will run the same
pipeline end-to-end but against fixed placeholder scores — useful only to
smoke-test the harness itself, not to measure real accuracy.

This writes `../eval_reports/latest_content_report.md` (+ `.json`) with a
per-metric MAE/Pearson-r table and a per-case breakdown. Keep a copy from
each prompt/rubric iteration so you have a real before/after comparison for
the competition PDF, the same way `local_scoring/eval_data/README.md`
describes for the audio/vision side.
