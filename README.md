# Clarivo — Learning Loop + Content + Delivery

Clarivo now supports the complete practice loop:

**Topic Library → Main Presentation → Editable Whisper Transcript → Content / Voice / Visual Analysis → A/B/C Interactive Drills → 5-Criterion Q&A Evaluation → Coverage / Dynamic Stopping → Final Learning Summary.**

The existing seven-criterion Main Evaluator remains unchanged. The new drill system is a separate layer above it.

## Quick start
Read:
- `RUN_LEARNING_LOOP_WINDOWS.md` — exact Windows commands
- `LEARNING_LOOP_IMPLEMENTATION.md` — feature and architecture map

## Frontend starter library
Edit `frontend/src/data/topicLibrary.js` to add or change prepared topics.

## Backend drill endpoints
- `POST /api/drills/generate`
- `POST /api/drills/evaluate`
- `POST /api/drills/finalize`

## Q&A criteria
- Accuracy
- Directness
- Consistency
- Relevance
- Audience Fit

Default `DRILL_MAX_ROUNDS=3`.

## Q&A / Topic Library v2 update

See `QNA_TOPIC_V2_CHANGES.md` for the isolated Q&A scorer, Overall after Q&A, same-type challenge replacement, audience-style questions, main-quality Q&A guard, and refreshable Topic Library.

# Final public package
