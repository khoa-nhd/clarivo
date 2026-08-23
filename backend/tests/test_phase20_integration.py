import sys
import types

# The score logic can be tested without loading OpenVINO runtime.
ov = types.ModuleType('openvino')
ov.Core = object
sys.modules.setdefault('openvino', ov)

from local_scoring.audio_analyzer import _scores, _detect_vowel_prolongation
from app.local_delivery import _compact_audio, _compact_vision


def test_phase20_cross_metric_slow_pace_caps_pause_and_filler():
    metrics = {
        'wpm': 20.0,
        'fillers_per_minute': 0.0,
        'active_duration_seconds': 20.0,
        'duration_seconds': 50.0,
        'speaking_time_seconds': 20.0,
        'active_speaking_ratio': 0.30,
        'excessive_pause_time_seconds': 0.0,
        'longest_pause_seconds': 0.0,
        'very_long_pause_count': 0,
        'speech_snr_db': 20.0,
        'average_volume_dbfs': -24.0,
        'clipping_ratio': 0.0,
        'volume_stability_db_std': 4.0,
        'segment_pace_cv': 0.12,
        'speech_density_window_std': 0.08,
        'filler_metric_reliability': 1.0,
        'speech_state': 'SPEECH_DETECTED',
    }
    scores = _scores(metrics, language='en', text_reliability=1.0)
    assert scores['pace'] < 30
    assert scores['pause_control'] <= 35
    assert metrics['cross_metric_pace_cap_triggered'] is True


def test_phase20_empty_audio_filler_helper_is_safe():
    import numpy as np
    out = _detect_vowel_prolongation(np.zeros(0, dtype='float32'), 16000, [])
    assert out['implicit_filler_count'] == 0


def test_phase20_compact_payload_surfaces_new_audio_metrics():
    audio = {
        'audio_score': 81.0,
        'scores': {
            'pace': 83.0,
            'pause_control': 76.0,
            'audibility': 88.0,
            'volume_stability': 84.0,
            'pace_stability': 79.0,
            'fluency': 75.0,
            'filler': 70.0,
            'filler_metric_reliability': 100.0,
            'text_metric_reliability': 100.0,
            'score_confidence': 90.0,
        },
        'metrics': {
            'speech_state': 'SPEECH_DETECTED',
            'wpm': 142.0,
            'filler_count': 3,
            'filler_count_transcript': 2,
            'implicit_filler_count': 1,
            'implicit_filler_source': 'acoustic_voiced_prolongation_heuristic',
            'fillers_per_minute': 1.4,
            'voice_activity_ratio': 0.72,
            'cross_metric_pace_cap_triggered': False,
            'filler_guard_triggered': False,
        },
        'feedback': [],
    }
    payload = _compact_audio(audio, 1.2)
    assert payload['schema_version'] == 'clarivo-web-audio-phase20'
    assert payload['voice']['implicit_filler_count'] == 1
    assert payload['voice']['filler_count_transcript'] == 2
    assert payload['voice']['voice_activity_ratio'] == 0.72


def test_phase20_compact_payload_surfaces_temporal_vision_flags():
    vision = {
        'vision_score': 78.0,
        'scores': {
            'camera_attention': 75.0,
            'presence': 84.0,
            'engagement': 74.0,
            'head_stability': 80.0,
            'posture': 72.0,
            'gesture': None,
            'score_confidence': 86.0,
        },
        'metrics': {
            'gaze_repeat_triggered': True,
            'gaze_repeat_episode_count': 3,
            'head_turn_repeat_triggered': False,
            'posture_repeat_triggered': True,
            'gesture_level': 'SOME MOVEMENT',
            'gesture_activity_percent': 26.0,
            'gesture_event_count': 4,
            'gesture_reliable': True,
        },
        'feedback': [],
    }
    payload = _compact_vision(vision, 2.4)
    assert payload['schema_version'] == 'clarivo-web-vision-phase20'
    assert payload['visual']['gaze_repeat_triggered'] is True
    assert payload['visual']['posture_repeat_triggered'] is True
    assert payload['visual']['gesture_level'] == 'SOME MOVEMENT'
