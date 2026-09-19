from dataclasses import dataclass


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    frame_ms: int = 30

    # Low-gain friendly adaptive VAD. The threshold is derived from the actual
    # recording instead of assuming a normal laptop mic sits around -30 dBFS.
    silence_min_ms: int = 650
    long_pause_seconds: float = 2.8
    very_long_pause_seconds: float = 5.0
    normal_pause_max_seconds: float = 2.5
    analysis_window_seconds: float = 10.0
    vad_noise_percentile: float = 18.0
    vad_speech_percentile: float = 90.0
    vad_min_margin_db: float = 5.5
    vad_max_margin_db: float = 12.0

    # Frame smoothing. Previously hard-coded inside _smooth(); extracted so the
    # hysteresis can be calibrated against labelled clips instead of edited in
    # scoring code.
    vad_fill_gap_max_seconds: float = 0.15
    vad_drop_blip_max_seconds: float = 0.12

    # Bimodal (Otsu) speech threshold. A frame-energy histogram of real speech
    # has two lobes - speech and background - and the threshold belongs in the
    # valley between them. The previous percentile rule assumed the quiet 18%
    # of frames were always background, which inverts once a fluent presenter
    # fills most of the recording with speech: the "noise floor" estimate lands
    # inside speech and the whole session is read as silence. Otsu finds the
    # valley from the data instead of assuming where it is.
    vad_min_bimodal_separation_db: float = 8.0
    # The threshold may never sit closer than this to the loud (speech) lobe,
    # which bounds the damage if the histogram search is ever misled.
    vad_min_peak_margin_db: float = 8.0
    # Used only when the histogram has a single lobe, i.e. there is no
    # background to separate. Every frame is then treated as active and the
    # speech/no-speech decision is deferred to the SNR and transcript evidence.
    vad_unimodal_floor_margin_db: float = 3.0

    # Conservative speech gate for the final scorer. These are intentionally
    # stricter than the live meter so background/distant speech is not scored.
    min_speech_seconds_for_scoring: float = 1.5
    min_active_speaking_ratio_for_scoring: float = 0.20
    min_speech_snr_db_for_scoring: float = 6.0
    # Absolute level is only a dead-signal guard. Microphone gain varies by tens
    # of dB between laptops, so a quiet but clean recording (e.g. -60 dBFS peak
    # at 24 dB SNR) must still be scored; SNR is the real audibility evidence.
    # The previous -48 dBFS gate silently voided those recordings entirely.
    min_speech_peak_dbfs_for_scoring: float = -72.0
    # A supplied transcript containing real words is direct evidence that
    # speech occurred, which outranks an ambiguous energy histogram.
    min_words_as_speech_evidence: int = 8

    # Strict non-lexical fillers. Elongated forms such as "ummm" and "uhhh"
    # are normalized by the counter so the literal list does not need every form.
    filler_words: tuple[str, ...] = (
        "um", "umm", "uh", "uhh", "erm", "er", "hmm", "hm", "uhm",
        "ờ", "ờm", "ừ", "ừm", "ừmm", "à",
    )
    discourse_markers: tuple[str, ...] = (
        "you know", "i mean", "basically", "actually", "literally",
        "kiểu như", "nói chung",
    )

    # ASR robustness.
    asr_chunk_seconds: float = 27.0
    asr_chunk_padding_seconds: float = 0.20
    asr_merge_gap_seconds: float = 0.45
    asr_max_tokens_per_second: float = 7.0
    asr_repetition_penalty: float = 1.05
    asr_no_repeat_ngram_size: int = 4
    max_consecutive_same_word: int = 3
    max_repeated_phrase_words: int = 6
    max_repeated_phrase_occurrences: int = 2
    hallucination_wpm_threshold: float = 260.0
    filler_guard_per_second: float = 1.0
    min_filler_wpm: float = 40.0
    prolonged_vowel_seconds: float = 0.8
    prolonged_vowel_equivalent_fillers: float = 1.0

    # Domain vocabulary is used only as a small Whisper priming hint and for
    # conservative post-processing. It is never trusted as ground truth.
    academic_vocabulary_en: tuple[str, ...] = (
        "photosynthesis", "chloroplast", "chlorophyll", "carbon dioxide",
        "oxygen", "glucose", "stomata", "mitochondria", "cellular respiration",
        "ecosystem", "algorithm", "regression", "classification", "neural network",
        "machine learning", "computer vision", "openvino",
    )
    academic_phrase_corrections_en: tuple[tuple[str, str], ...] = (
        ("small shrimp rope", "chloroplast"),
        ("small shrimp ropes", "chloroplasts"),
        ("chloroblast", "chloroplast"),
        ("chloroblasts", "chloroplasts"),
        ("chloral field", "chlorophyll"),
        ("chloral build", "chlorophyll"),
        ("blue colors and option", "glucose and oxygen"),
        ("blue colors and oxygen", "glucose and oxygen"),
        ("four thousand assists", "carbon dioxide"),
        ("4,000 assists", "carbon dioxide"),
    )

    # Overall voice-score component weights. Extracted from inline literals so
    # eval_harness.py can grid-search these against a labeled clip set instead
    # of hand-editing scoring code. Values below reproduce the pre-extraction
    # behavior exactly; do not change them without a benchmark run to justify it.
    weight_volume: float = 0.30
    weight_pause: float = 0.27
    weight_volume_stability: float = 0.08
    weight_pace: float = 0.18
    weight_filler: float = 0.10
    weight_pace_stability: float = 0.07


@dataclass
class VisionConfig:
    sample_fps: float = 2.0
    pose_every_n_samples: int = 1
    face_confidence: float = 0.42
    pose_confidence: float = 0.20
    pose_imgsz: int = 512

    # Camera attention remains calibrated + smoothed.
    gaze_calibration_samples: int = 10
    # Estimate the camera's fixed mounting offset from the most central, most
    # stable samples anywhere in the recording rather than only from its opening
    # seconds. Set False to restore the old opening-window behaviour.
    gaze_calibration_use_full_session: bool = True
    gaze_baseline_yaw_clip_deg: float = 15.0
    gaze_baseline_pitch_clip_deg: float = 12.0
    # v8 uses a continuous head-orientation score rather than a hard binary cutoff.
    # These thresholds are retained for diagnostics/preview categories only.
    yaw_forward_deg: float = 22.0
    pitch_forward_deg: float = 17.0
    screen_downward_pitch_tolerance_deg: float = 24.0
    screen_yaw_tolerance_deg: float = 26.0  # diagnostic; large yaw is never clipped in scoring
    # Eye gaze may legitimately differ from head pose, but an extreme
    # disagreement means the eye ROI is untrustworthy for that frame and the
    # analyzer falls back to head pose. 45.0 is the value that was actually in
    # force: analyze_video applied max(config, 45.0), so the previous 35.0
    # default was unreachable. Recorded here as the real default rather than
    # silently changing detection behaviour.
    gaze_head_disagreement_limit_deg: float = 45.0
    gaze_max_relative_yaw_deg: float = 55.0
    yaw_direct_deg: float = 11.0
    pitch_direct_deg: float = 9.0

    # Orientation banding. These were inline literals in _calibrated_gaze_states.
    orientation_direct_score: float = 88.0
    orientation_engaged_score: float = 72.0
    orientation_slight_score: float = 62.0
    # Schmitt-trigger margin, in score points: leaving a band costs this many
    # more points than entering it. Prevents a presenter sitting near a boundary
    # from flickering between bands and fragmenting one look-away into several.
    orientation_hysteresis_points: float = 6.0
    look_away_grace_seconds: float = 1.6
    away_grace_seconds: float = 0.9
    face_soft_decay_seconds: float = 1.5
    attention_hold_frames: int = 3

    # v9 posture: structural geometry, not "first frames = perfect posture".
    # Warm-up establishes only a whole-body lean reference for diagnostics.
    posture_calibration_samples: int = 5
    posture_min_keypoint_conf: float = 0.24
    shoulder_delta_good_deg: float = 10.0  # retained for backward compatibility
    torso_delta_good_deg: float = 11.0     # retained for backward compatibility
    roll_delta_good_deg: float = 12.0      # retained for backward compatibility
    head_offset_delta_good: float = 0.15   # retained for backward compatibility
    posture_reliable_quality: float = 0.34
    posture_min_reliable_frames: int = 5

    # Gesture v7: smooth keypoints and use hysteresis so detector jitter is not
    # misclassified as constant hand movement. Gesture stays informational only.
    gesture_min_keypoint_conf: float = 0.18
    gesture_motion_threshold_norm: float = 0.075
    gesture_release_threshold_norm: float = 0.045
    gesture_ema_alpha: float = 0.38
    gesture_start_frames: int = 2
    gesture_release_frames: int = 2
    gesture_event_cooldown_frames: int = 3
    gesture_min_reliable_frames: int = 6

    # Temporal event rules. These decide when a momentary reading becomes a
    # reported event, and they were previously written as bare literals inside
    # analyze_video - the exact values a calibration run needs to sweep. The
    # defaults reproduce the previous behaviour; change them only with a
    # cv_temporal_benchmark.py run to justify it.
    #
    # An event fires when a state is either held continuously for its sustain
    # window, or repeats often enough inside the repeat window that resetting
    # the timer with brief recoveries cannot hide it.
    gaze_sustain_seconds: float = 2.5
    gaze_repeat_window_seconds: float = 10.0
    gaze_repeat_count: int = 3
    head_turn_sustain_seconds: float = 3.5
    head_turn_repeat_window_seconds: float = 10.0
    head_turn_repeat_count: int = 3
    head_turn_yaw_deg: float = 32.0
    head_turn_pitch_deg: float = 25.0
    posture_violation_sustain_seconds: float = 4.0
    posture_violation_repeat_window_seconds: float = 10.0
    posture_violation_repeat_count: int = 3
    posture_violation_score_threshold: float = 65.0
    posture_good_score_threshold: float = 75.0
    posture_bad_score_threshold: float = 55.0
    posture_hold_max_seconds: float = 3.0
    away_repeat_window_seconds: float = 10.0
    away_repeat_count: int = 3

    # Overall vision-score component weights (v8: camera_attention already folds
    # in presence/engagement, so these three are not double-counted). Extracted
    # from inline literals so eval_harness.py can calibrate against labeled clips;
    # values reproduce pre-extraction behavior exactly.
    attention_weight: float = 0.60
    head_stability_weight: float = 0.15
    posture_weight: float = 0.25


@dataclass
class RealtimeConfig:
    realtime_vision_fps: float = 2.0
    realtime_pose_every_n_vision: int = 1

    # v8 prioritizes pace accuracy over update frequency. Every update re-decodes
    # one longer rolling context window; filler is intentionally NOT shown live.
    realtime_asr_interval_seconds: float = 8.0
    realtime_asr_chunk_seconds: float = 28.0
    realtime_asr_min_chunk_seconds: float = 14.0
    realtime_wpm_window_seconds: float = 28.0
    realtime_wpm_min_window_seconds: float = 14.0
    realtime_wpm_history: int = 3

    # Realtime mic calibration. Normal speaking should sit near the middle of the
    # meter, not near 70-100%. The baseline is learned from detected speech frames.
    realtime_volume_calibration_seconds: float = 3.5
    realtime_silence_dbfs: float = -80.0
    realtime_long_pause_seconds: float = 2.8
    audio_queue_max_chunks: int = 64

    # Camera attention / warnings.
    look_away_warning_seconds: float = 2.2
    posture_warning_seconds: float = 3.0
    warning_clear_seconds: float = 1.2
    posture_good_score: float = 72.0
