"""Whether a recording carries speech at all, judged from the waveform.

Every check the analyzer had could be satisfied by something that is not
speech, and on the web path a transcript is always supplied - so
``transcript_evidence`` waved the rest through. A pure 140 Hz sine came back
from the deployed backend as SPEECH_DETECTED at 58% confidence, scored 37.5,
with two filler words "detected" in it.

A transcript is evidence that somebody wrote words. It is not evidence that
this waveform contains them, so the two tests here cannot be overridden by one.

Thresholds come from measurement over the project's own synthetic speech suite,
with about half the headroom left as margin because a false reject costs the
user their entire voice report:

    speech (22 cases)      modulation >= 0.100, separation >= 2.51 dB
    pure tones / hum / music   modulation 0.000
    white noise            separation 0.43 dB, SNR 0.25 dB
"""

import sys
import types

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import numpy as np
import pytest

from local_scoring.audio_analyzer import (
    _classify_speech_state,
    _speech_activity,
    _syllable_modulation_index,
)
from local_scoring.config import AudioConfig
from local_scoring.synthetic_audio import all_clips

SR = 16000
CFG = AudioConfig()
TRANSCRIPT_WORDS = 17  # comfortably over min_words_as_speech_evidence


def _seconds(count: float) -> np.ndarray:
    return np.arange(int(SR * count)) / SR


def _verdict(signal) -> str:
    raw = _speech_activity(np.asarray(signal, dtype=np.float32), SR, CFG)
    raw.pop("speech_frame_mask", None)
    raw.pop("frame_seconds", None)
    # The hard case: a transcript is present, as it always is on the web.
    return _classify_speech_state(
        raw, 1.0, CFG, word_count=TRANSCRIPT_WORDS, transcript_supplied=True
    )


# --------------------------------------------------------------- measurement

def test_a_pure_tone_has_no_syllable_modulation():
    t = _seconds(20)
    assert _syllable_modulation_index(0.3 * np.sin(2 * np.pi * 140 * t), SR) < 0.01


def test_real_speech_cases_all_clear_the_threshold():
    """The margin that matters: rejecting speech costs the whole voice report."""
    worst = min(
        _syllable_modulation_index(clip.audio, SR)
        for clip in all_clips()
        if "silence_only" not in clip.name
    )
    assert worst >= CFG.min_syllable_modulation_index * 4.0, (
        f"least-modulated speech case is {worst:.3f}, too close to the "
        f"{CFG.min_syllable_modulation_index} threshold"
    )


def test_silence_is_zero_rather_than_undefined():
    assert _syllable_modulation_index(np.zeros(SR * 5), SR) == 0.0


def test_a_clip_too_short_to_measure_returns_zero():
    assert _syllable_modulation_index(np.ones(100), SR) == 0.0


# ------------------------------------------------------------------ verdicts

@pytest.mark.parametrize("clip", [c for c in all_clips() if "silence_only" not in c.name
                                  and "very_short" not in c.name],
                         ids=lambda c: c.name)
def test_every_speech_case_is_still_accepted(clip):
    assert _verdict(clip.audio) == "SPEECH_DETECTED"


@pytest.mark.parametrize(("name", "make"), [
    ("pure_tone_140hz", lambda t: 0.3 * np.sin(2 * np.pi * 140 * t)),
    ("pure_tone_440hz", lambda t: 0.3 * np.sin(2 * np.pi * 440 * t)),
    ("slow_hum", lambda t: 0.3 * np.sin(2 * np.pi * 140 * t) * (1 + 0.3 * np.sin(2 * np.pi * 0.3 * t))),
    ("music_like_pulse", lambda t: 0.3 * np.sin(2 * np.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * t))),
    ("silence", lambda t: np.zeros_like(t)),
])
def test_held_sounds_are_refused_even_with_a_transcript(name, make):
    assert _verdict(make(_seconds(20))) == "NO_SPEECH_DETECTED"


@pytest.mark.parametrize("level", [0.1, 0.01])
def test_steady_noise_is_accepted_and_that_is_the_intended_trade(level):
    """Noise is NOT refused, on purpose.

    Modulation cannot tell it from speech - noise scores 0.245, above most real
    speech - and the separation/SNR pair that did reject it also rejects
    continuous speech with no pauses, which has no background to stand out
    from. Spectral flatness was measured as an alternative and does not
    separate them either: speech reaches 0.549 against white noise at 0.562.

    So a recording of nothing but a fan is scored. That is the deliberate half
    of the trade: refusing a talk somebody actually gave is the worse mistake,
    and nobody submits a fan as their presentation.
    """
    rng = np.random.default_rng(0)
    assert _verdict(level * rng.standard_normal(SR * 20)) == "SPEECH_DETECTED"


def test_noise_is_indistinguishable_from_speech_by_modulation():
    """Pins the measurement behind that trade, so it is not re-litigated blind."""
    rng = np.random.default_rng(0)
    noise = 0.1 * rng.standard_normal(SR * 20)
    assert _syllable_modulation_index(noise, SR) > CFG.min_syllable_modulation_index


def test_a_transcript_cannot_turn_a_tone_into_speech():
    """The specific hole this closes: on the web a transcript is always there."""
    tone = 0.3 * np.sin(2 * np.pi * 140 * _seconds(20))
    raw = _speech_activity(np.asarray(tone, dtype=np.float32), SR, CFG)
    raw.pop("speech_frame_mask", None)
    raw.pop("frame_seconds", None)
    with_transcript = _classify_speech_state(raw, 1.0, CFG, word_count=500, transcript_supplied=True)
    without = _classify_speech_state(raw, 1.0, CFG, word_count=0, transcript_supplied=False)
    assert with_transcript == without == "NO_SPEECH_DETECTED"


def test_the_index_is_published_for_the_report():
    """Reported so a refusal can be explained rather than just asserted."""
    raw = _speech_activity(np.asarray(0.3 * np.sin(2 * np.pi * 140 * _seconds(5)),
                                      dtype=np.float32), SR, CFG)
    assert "syllable_modulation_index" in raw
