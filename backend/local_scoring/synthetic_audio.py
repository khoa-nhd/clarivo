"""Deterministic synthetic speech/silence clips with frame-level ground truth.

Why this exists
---------------
Clarivo's voice metrics (speaking time, pause count/length, WPM, filler rate,
SNR) all sit downstream of one binary decision: *is this frame speech?*  That
decision had no test of any kind, so a regression in it was invisible until it
reached a user as "N/A (No speech detected)".

Real labelled recordings are the gold standard and live in ``eval_data/``
(see ``eval_harness.py``).  They are, however, slow to collect and cannot be
committed to the repository.  These synthetic clips fill the gap *for the
decision logic only*: because the generator places every speech and silence
region itself, the frame-level labels are exact, so precision/recall/F1 are
exact too - no human labelling error, no ambiguity about where a pause starts.

What this does and does not measure
-----------------------------------
DOES measure: threshold selection, hysteresis/smoothing, run segmentation,
pause classification, and their behaviour across speech density, microphone
gain and SNR.  These are the parts that actually broke.

Does NOT measure: real acoustic phenomena - room reverberation, plosives,
breath noise, codec artefacts, overlapping talkers, or accent effects.  A clip
here is a harmonic stack with a syllable-rate envelope, not a person.  Good
scores here are a necessary, not sufficient, condition; ``eval_harness.py``
against real recordings remains the accuracy authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SAMPLE_RATE = 16000


@dataclass(frozen=True)
class SyntheticClip:
    """One generated clip plus its exact frame-level speech labels."""

    name: str
    audio: np.ndarray
    sample_rate: int
    #: (kind, start_seconds, end_seconds) with kind in {"speech", "silence"}
    regions: tuple[tuple[str, float, float], ...]
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def duration_seconds(self) -> float:
        return len(self.audio) / float(self.sample_rate)

    @property
    def speech_seconds(self) -> float:
        return sum(b - a for kind, a, b in self.regions if kind == "speech")

    def frame_labels(self, frame_seconds: float) -> np.ndarray:
        """Exact per-frame speech mask on the analyzer's own frame grid.

        A frame is labelled speech when its *midpoint* falls inside a speech
        region, which matches how a frame-energy VAD actually decides.
        """
        n = int(len(self.audio) // max(1, int(round(frame_seconds * self.sample_rate))))
        midpoints = (np.arange(n) + 0.5) * frame_seconds
        labels = np.zeros(n, dtype=bool)
        for kind, start, end in self.regions:
            if kind != "speech":
                continue
            labels |= (midpoints >= start) & (midpoints < end)
        return labels

    def inner_pauses(self, min_seconds: float) -> list[float]:
        """Silence regions the analyzer is expected to report as pauses.

        Leading and trailing silence are excluded because they are recording
        set-up, not delivery - the same convention ``_speech_activity`` uses.
        """
        inner = self.regions[1:-1] if len(self.regions) > 2 else ()
        return [b - a for kind, a, b in inner if kind == "silence" and (b - a) >= min_seconds]


def _speech_segment(
    rng: np.random.Generator,
    seconds: float,
    *,
    level_dbfs: float,
    f0: float,
    syllable_rate: float,
) -> np.ndarray:
    """Harmonic stack with a syllable-rate envelope, scaled to a peak level.

    The envelope matters more than the spectrum here: a frame-energy VAD sees
    exactly this modulation, and a constant tone would make the problem
    artificially easy by removing the intra-utterance level dips that cause
    real false negatives.
    """
    n = max(1, int(seconds * SAMPLE_RATE))
    t = np.arange(n) / SAMPLE_RATE
    signal = np.zeros(n, dtype=np.float64)
    for harmonic in range(1, 12):
        signal += (1.0 / harmonic) * np.sin(
            2.0 * np.pi * f0 * harmonic * t + rng.uniform(0.0, 2.0 * np.pi)
        )
    signal *= 0.55 + 0.45 * np.abs(np.sin(2.0 * np.pi * syllable_rate * t))
    signal += 0.05 * rng.standard_normal(n)
    peak = float(np.max(np.abs(signal)))
    if peak > 0:
        signal /= peak
    return signal * (10.0 ** (level_dbfs / 20.0))


def _noise(rng: np.random.Generator, seconds: float, *, level_dbfs: float) -> np.ndarray:
    n = max(1, int(seconds * SAMPLE_RATE))
    x = rng.standard_normal(n)
    peak = float(np.max(np.abs(x)))
    if peak > 0:
        x /= peak
    return x * (10.0 ** (level_dbfs / 20.0))


def build_clip(
    name: str,
    timeline: list[tuple[str, float]],
    *,
    speech_dbfs: float = -26.0,
    noise_dbfs: float = -60.0,
    f0: float = 120.0,
    syllable_rate: float = 4.5,
    seed: int = 0,
    description: str = "",
    tags: tuple[str, ...] = (),
) -> SyntheticClip:
    """Build one clip from a ``[("speech", 6.0), ("silence", 1.2), ...]`` timeline."""
    rng = np.random.default_rng(seed)
    parts: list[np.ndarray] = []
    regions: list[tuple[str, float, float]] = []
    cursor = 0.0
    for kind, seconds in timeline:
        if kind == "speech":
            segment = _speech_segment(
                rng, seconds, level_dbfs=speech_dbfs, f0=f0, syllable_rate=syllable_rate
            )
        else:
            segment = np.zeros(max(1, int(seconds * SAMPLE_RATE)))
        segment = segment + _noise(rng, seconds, level_dbfs=noise_dbfs)
        parts.append(segment)
        regions.append((kind, cursor, cursor + seconds))
        cursor += seconds

    audio = np.concatenate(parts).astype(np.float32)
    return SyntheticClip(
        name=name,
        audio=audio,
        sample_rate=SAMPLE_RATE,
        regions=tuple(regions),
        description=description,
        tags=tags,
    )


def _alternating(total_seconds: float, speech_ratio: float, blocks: int) -> list[tuple[float, float]]:
    speech_total = total_seconds * speech_ratio
    silence_total = total_seconds - speech_total
    speech_block = speech_total / blocks
    gaps = max(1, blocks - 1)
    silence_block = silence_total / gaps if silence_total > 0 else 0.0
    return [(speech_block, silence_block)] * blocks


def density_suite(total_seconds: float = 60.0, blocks: int = 6) -> list[SyntheticClip]:
    """Speech-density sweep.

    This is the axis that broke: a percentile noise-floor estimate silently
    inverts once speech occupies most of the recording, so the *most fluent*
    presenters were the ones misread as silent.
    """
    clips: list[SyntheticClip] = []
    for index, ratio in enumerate([0.30, 0.50, 0.65, 0.75, 0.82, 0.88, 0.94, 1.00]):
        timeline: list[tuple[str, float]] = []
        for i, (speech_block, silence_block) in enumerate(_alternating(total_seconds, ratio, blocks)):
            timeline.append(("speech", speech_block))
            if i < blocks - 1 and silence_block > 0:
                timeline.append(("silence", silence_block))
        clips.append(build_clip(
            f"density_{int(ratio * 100):03d}pct",
            timeline,
            seed=100 + index,
            description=f"{int(ratio * 100)}% of the recording is speech",
            tags=("density",),
        ))
    return clips


def gain_suite() -> list[SyntheticClip]:
    """Microphone-gain sweep at a fixed ~24 dB SNR.

    An adaptive VAD must not depend on the absolute dBFS level, because laptop
    microphone gain varies by tens of dB between machines.
    """
    timeline = [
        ("silence", 1.0), ("speech", 8.0), ("silence", 2.0),
        ("speech", 8.0), ("silence", 1.0),
    ]
    clips = []
    for index, speech_dbfs in enumerate([-12.0, -26.0, -40.0, -54.0, -66.0]):
        clips.append(build_clip(
            f"gain_{abs(int(speech_dbfs)):02d}dbfs",
            timeline,
            speech_dbfs=speech_dbfs,
            noise_dbfs=speech_dbfs - 24.0,
            seed=200 + index,
            description=f"speech peak {speech_dbfs:.0f} dBFS, SNR ~24 dB",
            tags=("gain",),
        ))
    return clips


def snr_suite() -> list[SyntheticClip]:
    """Background-noise sweep at fixed gain."""
    timeline = [
        ("silence", 1.0), ("speech", 8.0), ("silence", 2.5),
        ("speech", 8.0), ("silence", 1.0),
    ]
    clips = []
    for index, snr in enumerate([40.0, 28.0, 20.0, 14.0, 9.0]):
        clips.append(build_clip(
            f"snr_{int(snr):02d}db",
            timeline,
            speech_dbfs=-26.0,
            noise_dbfs=-26.0 - snr,
            seed=300 + index,
            description=f"speech to background separation ~{snr:.0f} dB",
            tags=("snr",),
        ))
    return clips


def pause_suite() -> list[SyntheticClip]:
    """Pause structures the pause-control score is supposed to distinguish."""
    return [
        build_clip(
            "pause_short_natural",
            [("silence", 0.8), ("speech", 6.0), ("silence", 0.9), ("speech", 6.0),
             ("silence", 0.8), ("speech", 6.0), ("silence", 0.8)],
            seed=400,
            description="only short natural breathing pauses",
            tags=("pause",),
        ),
        build_clip(
            "pause_one_long_stall",
            [("silence", 0.8), ("speech", 7.0), ("silence", 6.5), ("speech", 7.0), ("silence", 0.8)],
            seed=401,
            description="one long mid-sentence stall",
            tags=("pause",),
        ),
        build_clip(
            "pause_many_medium",
            [("silence", 0.8), ("speech", 4.0), ("silence", 3.0), ("speech", 4.0),
             ("silence", 3.0), ("speech", 4.0), ("silence", 3.0), ("speech", 4.0), ("silence", 0.8)],
            seed=402,
            description="repeated medium hesitation pauses",
            tags=("pause",),
        ),
    ]


def edge_suite() -> list[SyntheticClip]:
    """Degenerate inputs that must not crash or produce nonsense."""
    return [
        build_clip(
            "edge_silence_only",
            [("silence", 12.0)],
            seed=500,
            description="no speech at all - must stay N/A, never scored",
            tags=("edge",),
        ),
        build_clip(
            "edge_very_short_speech",
            [("silence", 1.0), ("speech", 1.2), ("silence", 1.0)],
            seed=501,
            description="below the minimum-speech gate",
            tags=("edge",),
        ),
        build_clip(
            "edge_long_lead_in",
            [("silence", 20.0), ("speech", 10.0), ("silence", 1.0)],
            seed=502,
            description="long set-up silence before speaking starts",
            tags=("edge",),
        ),
    ]


def all_clips() -> list[SyntheticClip]:
    return [*density_suite(), *gain_suite(), *snr_suite(), *pause_suite(), *edge_suite()]
