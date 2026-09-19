"""Regression tests for the speech-activity decision.

The bug these guard against: the percentile noise-floor estimate assumed the
quietest ~18% of frames were always background. Once a fluent presenter filled
more than roughly 82% of the recording with speech, that assumption inverted -
the "noise floor" landed inside speech, the threshold rose above it, and the
whole session was reported as silence. The failure scaled with fluency, so the
best presentations were the ones most likely to be told they had not spoken.
"""

import sys
import types

# The audio DSP path needs no OpenVINO runtime, but keep the stub so these tests
# also pass on a machine where the package happens to be absent.
_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import numpy as np
import pytest

from local_scoring.audio_analyzer import (
    _classify_speech_state,
    _otsu_threshold,
    _speech_activity,
)
from local_scoring.config import AudioConfig
from local_scoring.synthetic_audio import all_clips, build_clip


def _activity(clip):
    return _speech_activity(np.asarray(clip.audio, dtype=np.float32), clip.sample_rate, AudioConfig())


def _state(raw, *, words: int, supplied: bool = True):
    return _classify_speech_state(
        raw, 1.0, AudioConfig(), word_count=words, transcript_supplied=supplied
    )


@pytest.mark.parametrize("ratio", [0.82, 0.88, 0.94, 1.00])
def test_dense_speech_is_not_reported_as_silence(ratio):
    """A presenter who barely pauses must still be measured as speaking."""
    blocks, total = 6, 60.0
    speech_block = total * ratio / blocks
    silence_block = (total - total * ratio) / max(1, blocks - 1)
    timeline = []
    for i in range(blocks):
        timeline.append(("speech", speech_block))
        if i < blocks - 1 and silence_block > 0:
            timeline.append(("silence", silence_block))

    clip = build_clip(f"dense_{int(ratio * 100)}", timeline, seed=int(ratio * 1000))
    raw = _activity(clip)

    expected = clip.speech_seconds
    assert raw["speaking_time_seconds"] == pytest.approx(expected, abs=1.0), (
        f"{ratio:.0%} speech density measured as {raw['speaking_time_seconds']:.2f}s "
        f"of {expected:.2f}s"
    )
    assert _state(raw, words=int(expected * 2.4)) == "SPEECH_DETECTED"


def test_quiet_microphone_is_still_scored():
    """Low gain is not inaudibility: -60 dBFS at 24 dB SNR is analysable.

    An absolute -48 dBFS peak gate used to void these recordings entirely even
    though the speech/background separation was excellent.
    """
    clip = build_clip(
        "quiet_mic",
        [("silence", 1.0), ("speech", 8.0), ("silence", 2.0), ("speech", 8.0), ("silence", 1.0)],
        speech_dbfs=-60.0,
        noise_dbfs=-84.0,
        seed=99,
    )
    raw = _activity(clip)
    assert raw["speaking_time_seconds"] == pytest.approx(16.0, abs=0.5)
    assert raw["speech_snr_db"] > 12.0
    assert _state(raw, words=38) == "SPEECH_DETECTED"


def test_silence_only_stays_no_speech():
    clip = build_clip("silence_only", [("silence", 12.0)], seed=5)
    raw = _activity(clip)
    assert raw["vad_mode"] == "unimodal_no_background"
    # No transcript evidence -> must not be scored, whatever the frame mask said.
    assert _state(raw, words=0, supplied=False) == "NO_SPEECH_DETECTED"
    assert _state(raw, words=0, supplied=True) == "NO_SPEECH_DETECTED"


def test_too_short_speech_stays_no_speech():
    clip = build_clip(
        "too_short", [("silence", 1.0), ("speech", 1.0), ("silence", 1.0)], seed=6
    )
    raw = _activity(clip)
    assert _state(raw, words=3) == "NO_SPEECH_DETECTED"


def test_pause_structure_is_recovered():
    clip = build_clip(
        "three_pauses",
        [("silence", 0.8), ("speech", 5.0), ("silence", 1.5), ("speech", 5.0),
         ("silence", 3.0), ("speech", 5.0), ("silence", 2.0), ("speech", 5.0), ("silence", 0.8)],
        seed=7,
    )
    raw = _activity(clip)
    cfg = AudioConfig()
    expected = clip.inner_pauses(cfg.silence_min_ms / 1000.0)
    assert len(raw["pause_durations"]) == len(expected)
    assert raw["longest_pause_seconds"] == pytest.approx(max(expected), abs=0.15)


def test_otsu_separates_two_lobes_and_reports_flat_data_as_unimodal():
    two_lobes = np.concatenate([np.full(300, -70.0), np.full(700, -34.0)])
    threshold, separation = _otsu_threshold(two_lobes)
    assert -70.0 < threshold < -34.0
    assert separation == pytest.approx(36.0, abs=1.0)

    one_lobe = np.full(1000, -34.0) + np.random.default_rng(0).normal(0, 0.5, 1000)
    _, flat_separation = _otsu_threshold(one_lobe)
    assert flat_separation < AudioConfig().vad_min_bimodal_separation_db


def test_no_clip_in_the_suite_loses_its_speech():
    """Whole-suite invariant: nothing containing scoreable speech is gated to N/A."""
    cfg = AudioConfig()
    offenders = []
    for clip in all_clips():
        if clip.speech_seconds < cfg.min_speech_seconds_for_scoring:
            continue
        raw = _activity(clip)
        if _state(raw, words=int(clip.speech_seconds * 2.4)) != "SPEECH_DETECTED":
            offenders.append(clip.name)
    assert offenders == []
