"""Synthetic head-orientation sequences with exact attention-event labels.

Why this exists
---------------
Clarivo's camera-attention score is not produced by a model alone. The models
give a per-frame yaw/pitch; everything the user is actually judged on - "you
looked away for 4 seconds", "repeated short glances accumulated into a
warning" - is produced afterwards by calibration, thresholding, hysteresis and
the temporal run logic in ``vision_analyzer``. None of that logic had a test.

Those stages are pure geometry over a sequence of angles, so they can be
measured exactly without OpenVINO, without the ~200 MB of Open Model Zoo
weights, and without a webcam: generate an angle sequence with known look-away
episodes and check which episodes the pipeline reports.

What this does and does not measure
-----------------------------------
DOES measure: baseline/camera-bias calibration, the engaged/slight/off-axis
decision, sustained-duration and repeat-window event rules, detection latency,
and robustness to per-frame jitter and short detector dropouts.

Does NOT measure: whether ``head-pose-estimation-adas-0001`` reports the right
angle for a real face. That is model accuracy and needs labelled recordings
(``eval_harness.py``). A perfect score here means the decision layer is sound
given correct angles, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class OrientationSequence:
    """A sampled head-orientation track plus the episodes that truly occurred."""

    name: str
    #: (yaw_deg, pitch_deg) per sample, or None where no face was detected
    samples: tuple[tuple[float, float] | None, ...]
    sample_fps: float
    #: (start_seconds, end_seconds) of every true look-away episode
    away_episodes: tuple[tuple[float, float], ...]
    #: the constant camera mounting offset calibration is supposed to recover
    camera_bias_yaw: float = 0.0
    camera_bias_pitch: float = 0.0
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / self.sample_fps

    def episode_frames(self) -> list[tuple[int, int]]:
        return [
            (int(round(a * self.sample_fps)), int(round(b * self.sample_fps)))
            for a, b in self.away_episodes
        ]

    def reportable_episodes(
        self, *, sustain_seconds: float, repeat_window_seconds: float, repeat_count: int
    ) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Split true episodes into ``(reportable, tolerated)``.

        Clarivo deliberately does not report every look-away: a brief, isolated
        glance is normal presenting and is meant to be ignored, while a glance
        that is held long enough, or repeated often enough that brief recoveries
        cannot excuse it, is meant to be reported. Scoring recall against *all*
        episodes would therefore mark the product wrong for behaving exactly as
        designed, so the ground truth encodes that policy.

        A benchmark whose labels follow the specification can only show that the
        implementation matches the specification. Whether the specification
        itself is the right coaching policy is a product question that labelled
        recordings and user feedback have to answer, not this file.
        """
        episodes = sorted(self.away_episodes)
        clustered: set[int] = set()
        for index, (start, _) in enumerate(episodes):
            window = [
                other for other, (other_start, _) in enumerate(episodes[: index + 1])
                if start - other_start <= repeat_window_seconds
            ]
            if len(window) >= max(2, repeat_count):
                # Once a cluster qualifies, every glance inside it is part of the
                # pattern being reported, not just the one that completed it.
                clustered.update(window[-repeat_count:])

        reportable: list[tuple[float, float]] = []
        tolerated: list[tuple[float, float]] = []
        for index, (start, end) in enumerate(episodes):
            if end - start >= sustain_seconds or index in clustered:
                reportable.append((start, end))
            else:
                tolerated.append((start, end))
        return reportable, tolerated


def build_sequence(
    name: str,
    *,
    duration_seconds: float,
    sample_fps: float = 2.0,
    look_away_episodes: tuple[tuple[float, float, float], ...] = (),
    camera_bias_yaw: float = 0.0,
    camera_bias_pitch: float = 0.0,
    jitter_deg: float = 1.5,
    dropout_windows: tuple[tuple[float, float], ...] = (),
    seed: int = 0,
    description: str = "",
    tags: tuple[str, ...] = (),
    away_yaw_threshold: float = 30.0,
) -> OrientationSequence:
    """Build one track.

    ``look_away_episodes`` entries are ``(start_s, end_s, yaw_offset_deg)``.
    ``camera_bias_*`` is a constant mounting offset added to every sample - the
    thing calibration is supposed to remove. ``dropout_windows`` mark spans
    where the face detector found nothing, which the pipeline must treat as a
    short hold rather than an instant "out of frame".

    An episode counts as a true look-away only when its offset actually exceeds
    ``away_yaw_threshold``; smaller offsets are natural glances that the design
    deliberately tolerates, and are not labelled as events.
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration_seconds * sample_fps))
    yaw = np.full(n, camera_bias_yaw, dtype=float)
    pitch = np.full(n, camera_bias_pitch, dtype=float)

    truth: list[tuple[float, float]] = []
    for start, end, offset in look_away_episodes:
        i0 = max(0, int(round(start * sample_fps)))
        i1 = min(n, int(round(end * sample_fps)))
        if i1 <= i0:
            continue
        yaw[i0:i1] += offset
        if abs(offset) >= away_yaw_threshold:
            truth.append((i0 / sample_fps, i1 / sample_fps))

    yaw += rng.normal(0.0, jitter_deg, n)
    pitch += rng.normal(0.0, jitter_deg, n)

    samples: list[tuple[float, float] | None] = [
        (float(yaw[i]), float(pitch[i])) for i in range(n)
    ]
    for start, end in dropout_windows:
        i0 = max(0, int(round(start * sample_fps)))
        i1 = min(n, int(round(end * sample_fps)))
        for i in range(i0, i1):
            samples[i] = None

    return OrientationSequence(
        name=name,
        samples=tuple(samples),
        sample_fps=sample_fps,
        away_episodes=tuple(truth),
        camera_bias_yaw=camera_bias_yaw,
        camera_bias_pitch=camera_bias_pitch,
        description=description,
        tags=tags,
    )


def attention_suite() -> list[OrientationSequence]:
    """Cases the camera-attention rules are supposed to separate."""
    return [
        build_sequence(
            "clean_engaged",
            duration_seconds=60.0,
            seed=1,
            description="looks at the camera throughout - must produce no event",
            tags=("clean",),
        ),
        build_sequence(
            "single_glance_1s",
            duration_seconds=60.0,
            look_away_episodes=((20.0, 21.0, 45.0),),
            seed=2,
            description="one 1 s glance, shorter than the sustain window - must not fire",
            tags=("tolerance",),
        ),
        build_sequence(
            "sustained_look_away_6s",
            duration_seconds=60.0,
            look_away_episodes=((20.0, 26.0, 45.0),),
            seed=3,
            description="one clear 6 s look-away - must fire once",
            tags=("sustained",),
        ),
        build_sequence(
            "two_sustained_episodes",
            duration_seconds=90.0,
            look_away_episodes=((15.0, 21.0, 48.0), (55.0, 62.0, 44.0)),
            seed=4,
            description="two well-separated sustained look-aways",
            tags=("sustained",),
        ),
        build_sequence(
            "repeated_short_glances",
            duration_seconds=60.0,
            look_away_episodes=(
                (10.0, 11.5, 46.0), (13.0, 14.5, 46.0), (16.0, 17.5, 46.0), (19.0, 20.5, 46.0),
            ),
            seed=5,
            description="glances too short individually but clustered - repeat rule should catch them",
            tags=("repeat",),
        ),
        build_sequence(
            "camera_mounted_off_axis",
            duration_seconds=60.0,
            camera_bias_yaw=18.0,
            camera_bias_pitch=-12.0,
            look_away_episodes=((30.0, 36.0, 45.0),),
            seed=6,
            description="camera is mounted off-centre; calibration must not read that as looking away",
            tags=("calibration",),
        ),
        build_sequence(
            "early_look_away_then_centred",
            duration_seconds=90.0,
            camera_bias_yaw=10.0,
            look_away_episodes=((0.0, 18.0, 42.0),),
            seed=7,
            description="starts off-axis, so the calibration window opens on non-representative frames",
            tags=("calibration",),
        ),
        build_sequence(
            "detector_dropouts",
            duration_seconds=60.0,
            dropout_windows=((12.0, 12.5), (25.0, 25.5), (41.0, 41.5)),
            seed=8,
            description="brief face-detector misses while the presenter stays engaged",
            tags=("dropout",),
        ),
        build_sequence(
            "high_jitter_engaged",
            duration_seconds=60.0,
            jitter_deg=6.0,
            seed=9,
            description="noisy angle estimates but genuinely engaged - must not fire",
            tags=("clean", "noise"),
        ),
        build_sequence(
            "long_absence",
            duration_seconds=60.0,
            dropout_windows=((20.0, 32.0),),
            seed=10,
            description="presenter leaves frame for 12 s - presence, not attention",
            tags=("absence",),
        ),
    ]
