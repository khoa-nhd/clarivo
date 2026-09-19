# Clarivo AI benchmarks

Every accuracy or performance claim about Clarivo should be reproducible from
this file. Commands run from `backend/`.

## What each benchmark can and cannot tell you

Clarivo's AI has two distinct layers, and they need different evidence:

| Layer | Example | Measured by | Needs |
|---|---|---|---|
| **Decision logic** | Is this frame speech? Is this look-away reportable? | `vad_benchmark`, `cv_temporal_benchmark` | nothing but NumPy/librosa |
| **Model accuracy** | Does the head-pose model report the right angle for a real face? | `eval_harness` | labelled recordings + OpenVINO models |
| **Semantic judgement** | Does the evaluator agree with a human rater? | `content_eval_benchmark` | labelled transcripts + an API key |
| **Hardware** | How fast is each model on CPU/GPU/NPU? | `device_benchmark` | Intel hardware + OpenVINO |

The first row runs anywhere and is fully deterministic, because the generators
place every speech region and every look-away episode themselves, so the labels
are exact. **A perfect score there does not mean the product is accurate** - it
means the logic sitting on top of the models is sound given correct model
output. The other three rows are what establish real-world accuracy, and they
need data that cannot be committed to the repository.

## 1. Speech activity / VAD (no setup required)

```bash
python -m local_scoring.vad_benchmark
```

Frame-level precision/recall/F1 for the speech decision, plus error on the
metrics the user sees (speaking time, pause count, longest pause) across
24 synthetic clips spanning speech density, microphone gain, SNR, pause
structure and degenerate inputs.

Reproduce the before/after for the Otsu threshold change:

```bash
python -m local_scoring.vad_benchmark --json local_scoring/eval_reports/vad_after.json --compare local_scoring/eval_reports/vad_baseline.json
```

`vad_baseline.json` was produced by running the same clips through the
`audio_analyzer.py` committed at the previous revision.

The number that matters most is **clips with speech wrongly reported as
silent**: that verdict blanks every voice score, so it costs the user the whole
report rather than a few points.

## 2. Camera-attention event logic (no setup required)

```bash
python -m local_scoring.cv_temporal_benchmark
```

Event-level precision/recall/F1 for look-away detection over 10 synthetic
orientation tracks, plus detection latency and camera mounting-bias recovery
error.

Before/after for the calibration and hysteresis changes, from one code path:

```bash
python -m local_scoring.cv_temporal_benchmark --pre-fix-config --json /tmp/before.json
python -m local_scoring.cv_temporal_benchmark --compare /tmp/before.json
```

`--pre-fix-config` sets `gaze_calibration_use_full_session=False` and
`orientation_hysteresis_points=0.0`, which is exactly the prior behaviour - the
comparison needs no checkout of an old revision.

Ground truth here follows the product's own tolerance policy: a brief isolated
glance is *meant* to be ignored, so it is labelled "tolerated" and firing on it
counts as a false alarm. This benchmark can therefore show the implementation
matches the specification; whether the specification is the right coaching
policy is a product question for real recordings and user feedback.

## 3. Real recordings - audio and vision accuracy

```bash
python -m local_scoring.eval_harness --selftest    # logic check, no data needed
python -m local_scoring.eval_harness               # needs labelled clips
```

Needs self-recorded clips in `local_scoring/eval_data/clips/` with labels in
`local_scoring/eval_data/labels/`. See `local_scoring/eval_data/README.md` for
the schema. **No clips are currently recorded**, so no real-world accuracy
figure exists for the models themselves. This is the largest remaining gap.

## 4. Content evaluator agreement with a human rater

```bash
python -m app.content_eval_benchmark --selftest    # logic check, no API calls
python -m app.content_eval_benchmark               # needs labelled cases + key
```

Needs labelled transcripts in `app/eval_data/content/` and
`AI_PROVIDER=cloudflare` with credentials. **No cases are currently labelled**,
so the LLM rubric has no measured agreement with a human rater.

## 5. OpenVINO device and precision

```bash
python -m local_scoring.device_benchmark
python -m local_scoring.device_benchmark --devices CPU GPU NPU --iterations 100
```

Per model: which device it *actually* compiled onto after fallback, the
precision the runtime reports, compile time, cold inference, and warm
mean/median/p95/p99 latency plus throughput and RSS growth.

Run this before repeating any claim about device or precision. Two traps it
exists to catch:

- A model that silently fell back from NPU to CPU is indistinguishable from one
  that ran on NPU unless you ask the runtime which device it used.
- The CPU plugin executes FP16 IR by converting to FP32 or bf16. An FP16 file
  does not mean FP16 arithmetic on CPU.

### Measured results

Intel Core Ultra 7 255H (CPU + Intel Graphics iGPU + Intel AI Boost NPU),
OpenVINO 2026.4, 30 warm iterations after 5 warm-up runs:

| Model | Device | Compiled precision | Compile (s) | Cold (ms) | Mean (ms) | p95 (ms) | p99 (ms) | FPS |
|---|---|---|---|---|---|---|---|---|
| face_detection | CPU | float32 | 0.31 | 15.0 | 10.48 | 13.47 | 14.15 | 95 |
| face_detection | GPU | float16 | 5.83 | 13.9 | 3.13 | 5.29 | 6.76 | 319 |
| face_detection | NPU | float16 | 1.66 | 124.5 | 3.65 | 4.29 | 4.38 | 274 |
| head_pose | CPU | float32 | 0.11 | 2.6 | 1.12 | 1.52 | 1.72 | 892 |
| head_pose | GPU | float16 | 1.36 | 6.1 | 0.97 | 1.56 | 1.64 | 1027 |
| head_pose | NPU | float16 | 0.55 | 12.7 | 0.85 | 0.99 | 1.50 | 1172 |
| facial_landmarks | CPU | float32 | 1.21 | 5.9 | 3.03 | 4.02 | 5.15 | 330 |
| facial_landmarks | GPU | float16 | 10.02 | 16.1 | 4.95 | 7.65 | 7.95 | 202 |
| facial_landmarks | NPU | float16 | 3.03 | 11.7 | 2.71 | 3.02 | 3.06 | 368 |
| gaze_estimation | CPU | float32 | 0.19 | 4.1 | 3.46 | 4.68 | 5.26 | 289 |
| gaze_estimation | GPU | float16 | 1.66 | 4.6 | 1.24 | 2.20 | 2.29 | 807 |
| gaze_estimation | NPU | float16 | 0.58 | 10.7 | 1.39 | 2.37 | 3.34 | 718 |

What this shows:

- **No silent fallback.** All 12 combinations compiled onto the requested
  device, so the device claims in the docs are accurate on this machine.
- **The FP16 caveat is real and measurable.** CPU reports `float32` for every
  model, *including* the FP16-INT8 landmarks model. Only GPU and NPU report
  `float16`. A precision claim must therefore name the device.
- **NPU has the tightest tails.** For face detection, NPU p99 is 4.38 ms versus
  GPU 6.76 ms, despite a slightly higher mean - better for a per-frame pipeline.
- **NPU cold start is expensive.** 124.5 ms for the first face-detection
  inference versus 13.9 ms on GPU. Noticeable on very short clips.
- **GPU compile is the slowest** (10.0 s for landmarks alone, ~19 s for all
  four). Production sets `CACHE_DIR` via `device_utils.create_core`, so this is
  paid once and then cached; the benchmark deliberately does not cache so the
  cost is visible.

Model precisions as fetched by `setup_delivery_models.py`:

| Model | Downloaded precision |
|---|---|
| `face-detection-retail-0004` | FP16 |
| `head-pose-estimation-adas-0001` | FP16 |
| `facial-landmarks-35-adas-0002` | FP16-INT8 |
| `gaze-estimation-adas-0002` | FP16 |
| `yolo26s-pose` | exported to OpenVINO with `half=True` (FP16) |

These are what the download URLs and the export call specify, which is
verifiable from the source. Whether each one *executes* at that precision on a
given device is what `device_benchmark` reports.

## 6. Regression tests

```bash
python -m pytest tests -q
```

`tests/test_audio_vad.py`, `tests/test_vision_temporal.py` and
`tests/test_vision_duration.py` pin the specific failures that were fixed, so a
future change to a threshold or a scoring curve that reintroduces them fails in
CI rather than in front of a user.

## 7. Vision pipeline cost

Measured on the same machine, synthetic clips, warm OpenVINO cache, all models
on GPU, `sample_fps = 2.0`. "Before" reproduces the old loop exactly by making
`grab()` perform a full `read()` and discard the frame.

| Clip | Configuration | Total (s) | Decode (s) | Decode % | Pose (s) | Pose % | Realtime |
|---|---|---|---|---|---|---|---|
| 640x480, 22 s | before | 3.48 | 0.543 | 18.6% | 2.04 | 69.9% | 6.33x |
| 640x480, 22 s | after | 3.40 | 0.195 | 7.0% | 2.27 | 81.9% | 6.47x |
| 1280x720, 60 s | before | 10.64 | 5.980 | 59.7% | 3.23 | 32.3% | 5.64x |
| 1280x720, 60 s | after | **6.48** | **1.279** | 21.7% | 3.67 | 62.3% | **9.26x** |

- Skipping decode on non-sampled frames cuts decode time by 64% at 640x480 and
  **79% at 720p**. The end-to-end gain depends on resolution: only 2% on the
  small clip, but **39%** on the realistic one, because decode cost scales with
  pixels while pose cost scales only with sampled frames.
- **YOLO pose is the dominant cost after the fix** (62-82% of the loop), not
  decode. Halving its frequency with `pose_every_n_samples=2` gives a further
  28% (6.48 s -> 4.70 s at 720p), at the price of half the posture and gesture
  samples. That trade-off has not been measured for accuracy, so the default is
  left at 1; measuring it against real labelled clips is the natural next step.
