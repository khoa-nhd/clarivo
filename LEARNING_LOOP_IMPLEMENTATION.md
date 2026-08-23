# Learning Loop implementation map

## Added UI
- Topic Library with prepared Topic Profiles
- Task Description + Pre-study Keywords
- Recommended Audience with user override
- Auto-loaded reference context
- A/B/C Interactive Drill cards
- 30–60 second Q&A microphone recorder + editable transcript
- 5 Q&A score bars
- Challenge history
- Coverage progress
- Manual Finish button
- Dynamic stopping state
- Final Learning Summary
- Q&A / coverage progress in the Session Queue

## Added backend
- `POST /api/drills/generate`
- `POST /api/drills/evaluate`
- `POST /api/drills/finalize`
- Separate structured Q&A evaluator schema
- Single-focus prompt constraint
- Main transcript + reference + challenge + Q&A answer + challenge history grounding
- Hard maximum rounds safety guard
- Coverage / weak-area updates
- Final summary generation

## Main Evaluator remains unchanged
The existing seven-criterion Main Evaluator remains the same engine. Initial drills are generated in a separate AI call after the main result is available.

## Seed Topic Library
The build ships with starter profiles for Merge Sort, Least Squares, Photosynthesis, P-value, and Decision Trees. These are implementation seed data and can be expanded in `frontend/src/data/topicLibrary.js` without changing the evaluator architecture.
