# Clarivo local-scoring evaluation dataset

This folder holds the self-recorded, hand-labeled clips used to measure how
accurate the audio/vision analyzers actually are (`../eval_harness.py`). Every
threshold and score weight in `audio_analyzer.py`/`vision_analyzer.py` is
currently hand-tuned with no ground truth behind it — this dataset is what
turns "we think it's accurate" into a measured number, and doubles as the
"kiểm thử định lượng" evidence the AI 2026 Bảng B rubric asks for.

## What to record

Aim for 20-30 short clips (30-90 seconds each), spread across conditions the
real product will see, not just easy cases:

- **Lighting**: normal room light, backlit/dim, harsh side light.
- **Camera distance**: close (face fills frame) and far (full torso visible).
- **Speaking pace**: a few deliberately slow clips, a few fast/rushed ones.
- **Filler density**: some clean speech, some with frequent "um"/"uh".
- **Posture**: good posture, slouched, leaning far to one side.
- **Attention**: looking at camera throughout, looking away/at notes for parts.
- **Content**: some genuinely on-topic explanations, one or two off-topic
  (checks the content evaluator side separately, see the benchmark script
  under `backend/app/`).

It's fine to reuse team members/classmates presenting real topics from
`frontend/src/data/topicLibrary.js` — that keeps the dataset representative of
how the product is actually used, and doubles as demo material.

## How to label a clip

1. Save the video as `clips/<clip_id>.mp4` (or `.webm`/`.mov`).
2. Create `labels/<clip_id>.json` with the same stem, following this schema
   (omit any `ground_truth` field you didn't measure — the harness only
   scores fields that are present):

   ```json
   {
     "clip_id": "clip001",
     "notes": "far camera, backlit, fast talker, one long pause",
     "ground_truth": {
       "transcript": "the exact words spoken, hand-corrected from a first pass",
       "duration_seconds": 42.0,
       "wpm": 128,
       "filler_count": 5,
       "speaking_time_seconds": 34.0,
       "long_pause_count": 2,
       "posture_class": "good",
       "attention_class": "on_camera"
     }
   }
   ```

   - `transcript`: play the clip back and correct the words by hand — this
     also lets audio evaluation skip local ASR entirely (see harness
     docstring), so you don't need OpenVINO Whisper set up just to measure
     pace/pause/filler accuracy.
   - `wpm`: word count in the transcript divided by speaking duration in
     minutes (exclude long silences).
   - `filler_count`: count "um"/"uh"/similar by ear.
   - `speaking_time_seconds`: total time actually talking (stopwatch or
     listen-and-mark).
   - `long_pause_count`: count of pauses you'd subjectively call "long"
     (roughly 2+ seconds).
   - `posture_class`: one of `good` / `leaning` / `slouched`, your best
     subjective call watching the clip.
   - `attention_class`: one of `on_camera` / `mixed` / `off_camera`.

   Leave out any field you're not confident labeling by hand rather than
   guessing — a smaller number of trustworthy labels beats a full set of
   noisy ones.

3. If `librosa` can't decode audio directly from your video container, extract
   a WAV yourself (e.g. `ffmpeg -i clip001.mp4 -vn clip001.wav`) and add
   `"audio_file": "clips/clip001.wav"` to the label JSON — the harness will
   use that file for audio analysis instead of the video.

## Running the evaluation

From `backend/`:

```bash
python -m local_scoring.eval_harness
```

This writes `../eval_reports/latest_report.md` (and a matching `.json`) with
per-metric MAE/accuracy across every labeled clip, plus a per-clip breakdown.
Vision evaluation needs the OpenVINO models set up first
(`python -m local_scoring.setup_delivery_models`); audio evaluation only needs
`librosa` and a labeled transcript.

Keep the report from each tuning pass (rename `latest_report.md` before
re-running, or use `--report-dir`) so you have a real "v1 baseline → v2 tuned"
before/after table for the competition PDF's Evaluation/Iteration sections —
not just a final number.

## What's tracked in git

`clips/` (raw video, can be large) is gitignored; `labels/` (small JSON) is
tracked so the labeling work itself is preserved and reviewable. Generated
reports under `eval_reports/` are also gitignored — commit a copy manually
(e.g. into the competition PDF or a dated snapshot) when you want to keep a
specific before/after result as evidence.
