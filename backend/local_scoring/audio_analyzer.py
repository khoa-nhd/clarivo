from __future__ import annotations

import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import librosa
import numpy as np

from .config import AudioConfig
from .device_utils import fallback_chain
from .utils import clamp, piecewise_linear, safe_mean, safe_std


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return float(default)
    try:
        value = float(val)
    except (ValueError, TypeError):
        return float(default)
    return value if math.isfinite(value) else float(default)


def _extract_text(result: Any) -> str:
    texts = getattr(result, "texts", None)
    if texts:
        return str(texts[0]).strip()
    text = getattr(result, "text", None)
    if text:
        return str(text).strip()
    return str(result).strip()


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"(?u)\b[^\W_]+(?:['’-][^\W_]+)*\b", text.lower())


def _count_words(text: str) -> int:
    return len(_word_tokens(text))


def _collapse_pathological_repetitions(text: str, max_repeat: int = 3) -> tuple[str, int, int]:
    """Collapse only clearly pathological consecutive identical words.

    We preserve up to ``max_repeat`` copies so real stutters/fillers are still visible,
    but a Whisper loop such as "uh uh uh ..." hundreds of times can no longer destroy
    WPM/filler metrics.
    """
    words = _word_tokens(text)
    if not words:
        return text.strip(), 0, 0

    longest = 1
    cur = 1
    for i in range(1, len(words)):
        if words[i] == words[i - 1]:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 1

    removed = 0
    # Keep punctuation/normal wording everywhere except repeated single-word loops.
    word = r"[^\W_]+(?:['’-][^\W_]+)*"
    patt = re.compile(
        rf"(?iu)\b(?P<w>{word})\b(?P<tail>(?:[\s,.;:!?\-]+(?P=w)\b){{{max_repeat},}})"
    )

    def repl(m: re.Match[str]) -> str:
        nonlocal removed
        run_words = _word_tokens(m.group(0))
        removed += max(0, len(run_words) - max_repeat)
        return " ".join([m.group("w")] * max_repeat)

    cleaned = patt.sub(repl, text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, removed, longest



def _collapse_repeated_phrases(
    text: str, *, max_phrase_words: int = 6, max_occurrences: int = 2
) -> tuple[str, int]:
    """Remove pathological repeated multi-word hallucinations.

    Whisper can repeat an entire prompt-like sentence rather than repeating one
    token, so the old consecutive-word guard missed it. We look for a repeated
    n-gram of 3..N words occurring at least max_occurrences+1 times and keep at
    most max_occurrences copies. This is intentionally conservative: common
    content words may repeat, but a long identical phrase repeated many times is
    overwhelmingly likely to be an ASR loop.
    """
    words = _word_tokens(text)
    if len(words) < max_phrase_words * (max_occurrences + 1):
        return text, 0

    best = None
    max_n = min(max_phrase_words, max(3, len(words) // (max_occurrences + 1)))
    for n in range(max_n, 2, -1):
        found = None
        for i in range(0, len(words) - n + 1):
            gram = tuple(w.lower() for w in words[i:i+n])
            # scan non-overlapping phrase occurrences
            positions = []
            j = i
            while j <= len(words) - n:
                if tuple(w.lower() for w in words[j:j+n]) == gram:
                    positions.append(j)
                    j += n
                else:
                    j += 1
            if len(positions) >= max_occurrences + 1:
                found = (n, positions, gram)
                break
        if found:
            best = found
            break

    if best is None:
        return text, 0

    n, positions, gram = best
    # Keep the first max_occurrences copies, remove later copies.
    keep_until = set()
    for pos in positions[:max_occurrences]:
        keep_until.update(range(pos, pos+n))
    remove_ranges = []
    for pos in positions[max_occurrences:]:
        remove_ranges.append((pos, pos+n))

    new_words = []
    removed = 0
    i = 0
    remove_map = {j for a,b in remove_ranges for j in range(a,b)}
    while i < len(words):
        if i in remove_map:
            removed += 1
            i += 1
            continue
        new_words.append(words[i])
        i += 1
    cleaned = " ".join(new_words).strip()
    return cleaned, removed

def _count_fillers(text: str, fillers: tuple[str, ...]) -> tuple[int, dict[str, int]]:
    """Count fillers robustly, including elongated spellings from ASR.

    Exact-token counting missed forms such as ``ummm``/``uhhhh``.  We first
    consume canonical regexes for non-lexical fillers, then count any remaining
    literal filler phrases.  Boundaries keep ordinary content words safe.
    """
    lower = re.sub(r"\s+", " ", text.lower()).strip()
    counts: Counter[str] = Counter()

    canonical_patterns = (
        ("um", r"(?<!\w)u+m+(?!\w)"),
        ("uh", r"(?<!\w)u+h+(?!\w)"),
        ("erm", r"(?<!\w)e+r+m*(?!\w)"),
        ("hmm", r"(?<!\w)h+m+(?!\w)"),
        ("uhm", r"(?<!\w)u+h+m+(?!\w)"),
        ("ờ", r"(?<!\w)ờ+m*(?!\w)"),
        ("ừ", r"(?<!\w)ừ+m*(?!\w)"),
        ("à", r"(?<!\w)à+(?!\w)"),
    )
    consumed = lower
    for label, patt in canonical_patterns:
        matches = list(re.finditer(patt, consumed, flags=re.UNICODE))
        if matches:
            counts[label] += len(matches)
            consumed = re.sub(patt, " ", consumed, flags=re.UNICODE)

    # Multi-word or uncommon literals not covered by the canonical patterns.
    canonical_labels = {x[0] for x in canonical_patterns}
    for filler in sorted(set(fillers), key=len, reverse=True):
        if filler.lower() in canonical_labels:
            continue
        patt = r"(?<!\w)" + re.escape(filler.lower()) + r"(?!\w)"
        n = len(re.findall(patt, consumed, flags=re.UNICODE))
        if n:
            counts[filler] += n
            consumed = re.sub(patt, " ", consumed, flags=re.UNICODE)
    return int(sum(counts.values())), dict(counts)

def _runs(mask: np.ndarray) -> list[tuple[bool, int, int]]:
    if len(mask) == 0:
        return []
    out: list[tuple[bool, int, int]] = []
    s = 0
    cur = bool(mask[0])
    for i in range(1, len(mask)):
        v = bool(mask[i])
        if v != cur:
            out.append((cur, s, i))
            s, cur = i, v
    out.append((cur, s, len(mask)))
    return out


def _smooth(mask: np.ndarray, frame_seconds: float) -> np.ndarray:
    mask = mask.copy()
    for speech, s, e in _runs(mask):
        if not speech and s > 0 and e < len(mask) and (e - s) * frame_seconds < 0.15:
            mask[s:e] = True
    for speech, s, e in _runs(mask):
        if speech and (e - s) * frame_seconds < 0.12:
            mask[s:e] = False
    return mask


def _merge_sample_regions(
    regions: list[tuple[int, int]], *, sr: int, gap_seconds: float, pad_seconds: float, n_samples: int
) -> list[tuple[int, int]]:
    if not regions:
        return []
    gap = int(gap_seconds * sr)
    pad = int(pad_seconds * sr)
    merged: list[list[int]] = []
    for s, e in regions:
        if not merged or s - merged[-1][1] > gap:
            merged.append([s, e])
        else:
            merged[-1][1] = max(merged[-1][1], e)
    out = []
    for s, e in merged:
        s = max(0, s - pad)
        e = min(n_samples, e + pad)
        if e - s >= int(0.20 * sr):
            out.append((s, e))
    return out


def _split_long_regions(regions: list[tuple[int, int]], *, sr: int, max_seconds: float) -> list[tuple[int, int]]:
    max_len = max(1, int(max_seconds * sr))
    out: list[tuple[int, int]] = []
    for s, e in regions:
        cur = s
        while e - cur > max_len:
            out.append((cur, cur + max_len))
            cur += max_len
        if e - cur >= int(0.20 * sr):
            out.append((cur, e))
    return out


def _detect_vowel_prolongation(
    audio: np.ndarray,
    sr: int,
    speech_regions: list[tuple[int, int]],
    *,
    min_duration_seconds: float = 0.8,
) -> dict[str, Any]:
    """Conservatively flag sustained vowel-like acoustic runs.

    This is an acoustic heuristic, not a phoneme recognizer. It identifies contiguous
    voiced/vowel-like runs inside known speech regions using low ZCR, low spectral
    flatness, and continuous energy. A maximum of one candidate is counted per speech
    region so long normal words do not inflate filler counts.
    """
    if len(audio) == 0 or not speech_regions:
        return {
            "implicit_filler_count": 0,
            "implicit_filler_durations_seconds": [],
            "implicit_filler_source": "none",
        }

    frame_len = max(64, int(0.025 * sr))
    hop = max(32, int(0.010 * sr))
    candidates: list[float] = []

    for start, end in speech_regions:
        if end <= start:
            continue
        segment = np.asarray(audio[start:end], dtype=np.float32)
        if len(segment) < int(min_duration_seconds * sr):
            continue

        try:
            zcr = librosa.feature.zero_crossing_rate(
                segment,
                frame_length=min(frame_len, len(segment)),
                hop_length=min(hop, max(1, frame_len)),
                center=False,
            )[0]
            flatness = librosa.feature.spectral_flatness(
                y=segment,
                n_fft=max(128, min(1024, frame_len * 4)),
                hop_length=min(hop, max(1, frame_len)),
                center=False,
            )[0]
            rms = librosa.feature.rms(
                y=segment,
                frame_length=min(frame_len, len(segment)),
                hop_length=min(hop, max(1, frame_len)),
                center=False,
            )[0]
        except Exception:
            continue

        n = min(len(zcr), len(flatness), len(rms))
        if n == 0:
            continue

        zcr = zcr[:n]
        flatness = flatness[:n]
        rms = rms[:n]
        rms_median = float(np.median(rms))
        energy_floor = max(rms_median * 0.70, 1e-5)
        vowel_like = (
            (zcr <= 0.12)
            & (flatness <= 0.35)
            & (rms >= energy_floor)
        )

        runs = _runs(vowel_like)
        qualifying = [
            (b - a) * (hop / max(sr, 1))
            for is_active, a, b in runs
            if is_active
            and (b - a) * (hop / max(sr, 1)) >= float(min_duration_seconds)
        ]
        if qualifying:
            # One conservative candidate per speech region.
            candidates.append(min(max(qualifying), 3.0))

    return {
        "implicit_filler_count": len(candidates),
        "implicit_filler_durations_seconds": [round(x, 3) for x in candidates],
        "implicit_filler_source": "acoustic_voiced_prolongation_heuristic",
    }


def _speech_activity(audio: np.ndarray, sr: int, cfg: AudioConfig) -> dict[str, Any]:
    """Detect speech/pauses with a gain-independent adaptive threshold.

    Older versions clipped the speech threshold to about -52 dBFS. On a quiet
    Windows microphone whose *speech* itself arrives near -70 dBFS, that made
    almost the whole recording look silent. v7 estimates both the noise floor and
    upper speech energy from this recording and chooses a threshold between them.
    """
    frame_len = max(1, int(sr * cfg.frame_ms / 1000))
    if len(audio) < frame_len:
        audio = np.pad(audio, (0, frame_len - len(audio)))
    rms = librosa.feature.rms(y=audio, frame_length=frame_len, hop_length=frame_len, center=False)[0]
    db = librosa.amplitude_to_db(np.maximum(rms, 1e-8), ref=1.0)

    if len(db):
        noise_floor = float(np.percentile(db, cfg.vad_noise_percentile))
        speech_ref = float(np.percentile(db, cfg.vad_speech_percentile))
        dynamic = max(0.0, speech_ref - noise_floor)
        margin = float(np.clip(dynamic * 0.48, cfg.vad_min_margin_db, cfg.vad_max_margin_db))
        threshold = noise_floor + margin
        # Only protect against numerical floor/near-clipping extremes; do NOT impose
        # a normal-microphone threshold such as -52 dBFS.
        threshold = float(np.clip(threshold, -78.0, -18.0))
    else:
        noise_floor, speech_ref, threshold = -80.0, -70.0, -74.0

    frame_seconds = frame_len / sr
    speech = _smooth(db > threshold, frame_seconds)

    duration = float(len(audio) / sr)
    speaking = float(np.sum(speech) * frame_seconds)
    pauses: list[float] = []
    runs = _runs(speech)
    sample_regions: list[tuple[int, int]] = []
    for i, (is_speech, s0, e0) in enumerate(runs):
        if is_speech:
            sample_regions.append((s0 * frame_len, min(len(audio), e0 * frame_len)))
            continue
        if i == 0 or i == len(runs) - 1:
            continue
        gap = (e0 - s0) * frame_seconds
        if gap >= cfg.silence_min_ms / 1000:
            pauses.append(float(gap))

    sample_regions = _merge_sample_regions(
        sample_regions, sr=sr, gap_seconds=cfg.asr_merge_gap_seconds,
        pad_seconds=cfg.asr_chunk_padding_seconds, n_samples=len(audio),
    )
    sample_regions = _split_long_regions(sample_regions, sr=sr, max_seconds=cfg.asr_chunk_seconds)

    speech_idx = np.flatnonzero(speech)
    if speech_idx.size:
        active_start = float(speech_idx[0] * frame_seconds)
        active_end = float(min(duration, (speech_idx[-1] + 1) * frame_seconds))
        active_duration = max(frame_seconds, active_end - active_start)
    else:
        active_start = active_end = 0.0
        active_duration = 0.0
    active_speaking_ratio = speaking / active_duration if active_duration > 0 else 0.0

    speech_db = db[speech] if np.any(speech) else np.array([], dtype=float)
    win_frames = max(1, int(cfg.analysis_window_seconds / frame_seconds))
    densities = [
        float(np.mean(speech[s0:s0 + win_frames]))
        for s0 in range(0, len(speech), win_frames)
        if len(speech[s0:s0 + win_frames]) >= 2
    ]

    avg_speech_db = safe_mean(speech_db.tolist(), speech_ref if len(db) else -80.0)
    pause_time = float(sum(pauses))
    normal_pauses = [p for p in pauses if p <= cfg.normal_pause_max_seconds]
    long_pauses = [p for p in pauses if cfg.long_pause_seconds <= p < cfg.very_long_pause_seconds]
    very_long_pauses = [p for p in pauses if p >= cfg.very_long_pause_seconds]
    excessive_pause_time = float(sum(max(0.0, p - cfg.normal_pause_max_seconds) for p in pauses))
    return {
        "duration_seconds": duration,
        "active_duration_seconds": active_duration,
        "active_start_seconds": active_start,
        "active_end_seconds": active_end,
        "speaking_time_seconds": speaking,
        "silence_time_seconds": max(0.0, duration - speaking),
        "speaking_ratio": speaking / duration if duration else 0.0,
        "active_speaking_ratio": active_speaking_ratio,
        "pause_durations": pauses,
        "pause_time_seconds": pause_time,
        "excessive_pause_time_seconds": excessive_pause_time,
        "normal_pause_count": len(normal_pauses),
        "long_pause_count": len(long_pauses) + len(very_long_pauses),
        "very_long_pause_count": len(very_long_pauses),
        "average_pause_seconds": safe_mean(pauses),
        "median_pause_seconds": float(np.median(pauses)) if pauses else 0.0,
        "longest_pause_seconds": max(pauses, default=0.0),
        "noise_floor_dbfs": noise_floor,
        "speech_reference_dbfs": speech_ref,
        "speech_threshold_dbfs": threshold,
        "audio_dynamic_range_db": max(0.0, speech_ref - noise_floor),
        "average_volume_dbfs": avg_speech_db,
        "speech_snr_db": max(0.0, avg_speech_db - noise_floor),
        "volume_stability_db_std": safe_std(speech_db.tolist()),
        "peak_amplitude": float(np.max(np.abs(audio))) if len(audio) else 0.0,
        "clipping_ratio": float(np.mean(np.abs(audio) >= 0.985)) if len(audio) else 0.0,
        "speech_density_window_std": safe_std(densities),
        "asr_regions_samples": sample_regions,
    }

def _classify_speech_state(raw: dict[str, Any], text_reliability: float, cfg: AudioConfig) -> str:
    """Classify meaningful target speech conservatively.

    The recorder cannot truly separate a nearby speaker from the target without a
    dedicated speaker-identification model.  v17 therefore uses a strict evidence
    gate: enough sustained speech, enough speech/noise separation, and adequate peak
    level are required before any audio score is allowed.
    """
    duration = float(raw.get("duration_seconds", 0.0) or 0.0)
    speaking = float(raw.get("speaking_time_seconds", 0.0) or 0.0)
    active_ratio = float(raw.get("active_speaking_ratio", 0.0) or 0.0)
    snr = float(raw.get("speech_snr_db", 0.0) or 0.0)
    peak = float(raw.get("peak_amplitude", 0.0) or 0.0)
    peak_dbfs = 20.0 * math.log10(max(peak, 1e-8))

    if duration <= 0.0:
        return "NO_SPEECH_DETECTED"
    if speaking < cfg.min_speech_seconds_for_scoring:
        return "NO_SPEECH_DETECTED"
    if active_ratio < cfg.min_active_speaking_ratio_for_scoring:
        return "NO_SPEECH_DETECTED"
    if snr < cfg.min_speech_snr_db_for_scoring:
        return "NO_SPEECH_DETECTED"
    if peak_dbfs < cfg.min_speech_peak_dbfs_for_scoring:
        return "NO_SPEECH_DETECTED"
    if text_reliability < 0.50 and active_ratio < 0.35:
        return "NO_SPEECH_DETECTED"
    return "SPEECH_DETECTED"


def _apply_domain_corrections(text: str, language: str, cfg: AudioConfig) -> tuple[str, int]:
    """Apply conservative exact phrase corrections for common academic ASR confusions."""
    if not text or not str(language or "").lower().startswith("en"):
        return text, 0
    cleaned = text
    count = 0
    for src, dst in cfg.academic_phrase_corrections_en:
        patt = re.compile(r"(?<!\w)" + re.escape(src) + r"(?!\w)", re.IGNORECASE)
        cleaned, n = patt.subn(dst, cleaned)
        count += int(n)
    return cleaned, count


def _build_whisper_prompt(language: str, cfg: AudioConfig) -> str | None:
    """Vocabulary-only prompt; avoids instructional prompt leakage."""
    if str(language or "").lower().startswith("en"):
        terms = ", ".join(cfg.academic_vocabulary_en)
        return f"Presentation vocabulary: {terms}."
    return None


def _dedupe_overlap_text(parts: list[str], max_overlap_words: int = 12) -> str:
    output: list[str] = []
    for part in parts:
        words = re.findall(r"\S+", str(part).strip())
        if not words:
            continue
        if not output:
            output.extend(words)
            continue
        max_n = min(max_overlap_words, len(output), len(words))
        overlap = 0
        for n in range(max_n, 0, -1):
            left = [re.sub(r"[^\w']+", "", x).lower() for x in output[-n:]]
            right = [re.sub(r"[^\w']+", "", x).lower() for x in words[:n]]
            if left == right:
                overlap = n
                break
        output.extend(words[overlap:])
    return " ".join(output).strip()


def _transcription_windows(
    speech_regions: list[tuple[int, int]], *, sr: int, n_samples: int,
    max_seconds: float, overlap_seconds: float
) -> list[tuple[int, int]]:
    """Build long continuous overlapping windows from first to last speech."""
    if not speech_regions:
        return []
    first = min(s for s, _ in speech_regions)
    last = max(e for _, e in speech_regions)
    max_len = max(1, int(max_seconds * sr))
    overlap = max(0, int(overlap_seconds * sr))
    windows: list[tuple[int, int]] = []
    start = first
    while start < last:
        end = min(n_samples, start + max_len)
        if end - start >= int(2.0 * sr):
            windows.append((start, end))
        if end >= last:
            break
        next_start = max(start + int(1.0 * sr), end - overlap)
        if next_start <= start:
            break
        start = next_start
    return windows


def _language_kw(language: str) -> dict[str, Any]:
    if language and language.lower() not in {"auto", "none", ""}:
        return {"language": language if language.startswith("<|") else f"<|{language}|>"}
    return {}


def _generate_whisper(pipe: Any, audio: np.ndarray, *, language: str, duration: float, cfg: AudioConfig) -> Any:
    max_tokens = int(max(96, min(1024, duration * cfg.asr_max_tokens_per_second + 48)))
    quality_kwargs: dict[str, Any] = {
        "task": "transcribe",
        "return_timestamps": True,
        "max_new_tokens": max_tokens,
        "repetition_penalty": cfg.asr_repetition_penalty,
        "no_repeat_ngram_size": cfg.asr_no_repeat_ngram_size,
        "do_sample": False,
        **_language_kw(language),
    }
    prompt = _build_whisper_prompt(language, cfg)
    if prompt:
        quality_kwargs["initial_prompt"] = prompt
    try:
        return pipe.generate(audio.astype(np.float32).tolist(), **quality_kwargs)
    except Exception as exc:
        # Some older OpenVINO GenAI builds may reject one of the generic decoding
        # controls. Retry once with the minimal Whisper arguments instead of failing.
        msg = str(exc).lower()
        if any(k in msg for k in ("repetition", "ngram", "initial_prompt", "generation config", "unexpected")):
            minimal = {
                "task": "transcribe",
                "return_timestamps": True,
                "max_new_tokens": max_tokens,
                **_language_kw(language),
            }
            return pipe.generate(audio.astype(np.float32).tolist(), **minimal)
        raise


def transcribe_openvino(
    audio: np.ndarray,
    model_dir: str | Path,
    *,
    device: str,
    language: str,
    cache_dir: str | Path,
    sr: int,
    speech_regions: list[tuple[int, int]],
    cfg: AudioConfig,
) -> tuple[str, str, list[dict[str, Any]], float, str, dict[str, Any]]:
    """Transcribe long continuous windows with light overlap and robust cleanup."""
    if not speech_regions:
        return "", "", [], 0.0, "NO_SPEECH", {
            "hallucination_suspected": False,
            "repetition_removed_words": 0,
            "longest_identical_word_run": 0,
            "raw_word_count": 0,
            "clean_word_count": 0,
            "vad_chunk_count": 0,
            "repeated_phrase_removed_words": 0,
        "domain_correction_count": 0,
            "domain_correction_count": 0,
        }

    import openvino_genai as ov_genai

    start = time.perf_counter()
    model_dir = Path(model_dir)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    windows = _transcription_windows(
        speech_regions,
        sr=sr,
        n_samples=len(audio),
        max_seconds=cfg.asr_chunk_seconds,
        overlap_seconds=0.8,
    )

    last_error: Exception | None = None
    candidates = fallback_chain(device)
    if device.upper() == "NPU" and "CPU" in candidates:
        candidates = ["NPU", "CPU"] + [d for d in candidates if d not in {"NPU", "CPU"}]

    for current in candidates:
        try:
            try:
                pipe = ov_genai.WhisperPipeline(
                    str(model_dir), current, CACHE_DIR=str(cache_dir / "whisper_final")
                )
            except Exception:
                pipe = ov_genai.WhisperPipeline(str(model_dir), current)

            raw_parts: list[str] = []
            segments: list[dict[str, Any]] = []
            per_window_words: list[int] = []

            for s0, e0 in windows:
                chunk = audio[s0:e0]
                chunk_start = s0 / sr
                chunk_duration = len(chunk) / sr
                result = _generate_whisper(
                    pipe, chunk, language=language, duration=chunk_duration, cfg=cfg
                )
                chunk_text = _extract_text(result)
                if chunk_text:
                    raw_parts.append(chunk_text)
                    per_window_words.append(_count_words(chunk_text))

                chunks = getattr(result, "chunks", None) or []
                if chunks:
                    for c in chunks:
                        try:
                            segments.append({
                                "start": round(chunk_start + float(c.start_ts), 3),
                                "end": round(chunk_start + float(c.end_ts), 3),
                                "text": str(c.text).strip(),
                            })
                        except Exception:
                            continue
                elif chunk_text:
                    segments.append({
                        "start": round(chunk_start, 3),
                        "end": round(chunk_start + chunk_duration, 3),
                        "text": chunk_text,
                    })

            raw_text = _dedupe_overlap_text(raw_parts)
            raw_text = re.sub(
                r"(?i)(?:do not add fillers that are not audible\.?\s*)+", " ", raw_text
            ).strip()

            corrected_text, domain_corrections = _apply_domain_corrections(raw_text, language, cfg)
            corrected_text, phrase_removed = _collapse_repeated_phrases(
                corrected_text,
                max_phrase_words=getattr(cfg, "max_repeated_phrase_words", 6),
                max_occurrences=getattr(cfg, "max_repeated_phrase_occurrences", 2),
            )
            cleaned, removed, longest_run = _collapse_pathological_repetitions(
                corrected_text, max_repeat=cfg.max_consecutive_same_word
            )

            raw_words = _count_words(raw_text)
            clean_words = _count_words(cleaned)
            audio_minutes = max(len(audio) / sr / 60.0, 1e-6)
            raw_wpm = raw_words / audio_minutes
            removed_total = int(removed + phrase_removed)
            removed_ratio = removed_total / max(raw_words, 1)

            quality = {
                "hallucination_suspected": bool(
                    longest_run >= 6
                    or raw_wpm > cfg.hallucination_wpm_threshold
                    or removed_ratio > 0.12
                    or phrase_removed > 12
                ),
                "repetition_removed_words": int(removed),
                "longest_identical_word_run": int(longest_run),
                "raw_word_count": int(raw_words),
                "clean_word_count": int(clean_words),
                "raw_wpm": round(raw_wpm, 2),
                "cleanup_removed_ratio": round(removed_ratio, 4),
                "vad_chunk_count": len(windows),
                "repeated_phrase_removed_words": int(phrase_removed),
                "domain_correction_count": int(domain_corrections),
                "window_word_counts": per_window_words,
            }
            if current != device.upper():
                print(f"      ASR fallback: {device.upper()} -> {current}")
            return cleaned, raw_text, segments, time.perf_counter() - start, current, quality
        except Exception as exc:
            last_error = exc
            print(f"      ASR failed on {current}: {type(exc).__name__}. Trying fallback...")

    assert last_error is not None
    raise RuntimeError(f"Whisper failed on all candidate devices: {last_error}") from last_error


def _segment_pace(segments: list[dict[str, Any]], cfg: AudioConfig) -> tuple[list[float], float]:
    vals: list[float] = []
    for seg in segments:
        dur = float(seg.get("end", 0)) - float(seg.get("start", 0))
        cleaned, _, _ = _collapse_pathological_repetitions(
            str(seg.get("text", "")), max_repeat=cfg.max_consecutive_same_word
        )
        words = _count_words(cleaned)
        if dur >= 1.0 and words > 0:
            wpm = words / (dur / 60.0)
            # Do not let a clearly hallucinated segment destroy pace stability.
            if wpm <= cfg.hallucination_wpm_threshold:
                vals.append(wpm)
    if len(vals) < 2:
        return vals, 0.0
    mean = float(np.mean(vals))
    return vals, float(np.std(vals) / max(mean, 1e-6))


def _text_reliability(*, transcript_supplied: bool, asr_quality: dict[str, Any], language: str, metrics: dict[str, Any]) -> float:
    """Evidence-based reliability of transcript-derived metrics.

    This is a heuristic quality estimate, not a token log-probability because the
    OpenVINO pipeline used here does not expose a stable per-token logprob API.
    It deliberately has no hardcoded 72% floor.
    """
    if transcript_supplied:
        return 1.0
    raw_words = max(1, int(asr_quality.get("raw_word_count", 0) or 0))
    cleaned_words = max(0, int(asr_quality.get("clean_word_count", metrics.get("word_count", 0)) or 0))
    removed = max(0, int(asr_quality.get("repetition_removed_words", 0) or 0))
    removed_ratio = removed / raw_words
    speaking = float(metrics.get("speaking_time_seconds", 0.0) or 0.0)
    active_ratio = float(metrics.get("active_speaking_ratio", 0.0) or 0.0)
    articulation = float(metrics.get("articulation_wpm", 0.0) or 0.0)
    # Evidence components.
    duration_e = float(np.clip(speaking / 45.0, 0.0, 1.0))
    word_e = float(np.clip(cleaned_words / max(12.0, speaking * 2.2), 0.0, 1.0))
    density_e = 1.0 if 70 <= articulation <= 240 else (0.55 if 50 <= articulation <= 280 else 0.15)
    repetition_e = float(np.clip(1.0 - removed_ratio * 2.2, 0.0, 1.0))
    vad_e = float(np.clip(active_ratio / 0.72, 0.0, 1.0))
    if asr_quality.get("hallucination_suspected"):
        repetition_e *= 0.25
    domain_corrections = int(asr_quality.get("domain_correction_count", 0) or 0)
    domain_e = float(np.exp(-0.10 * min(domain_corrections, 12)))
    rel = (
        0.23*duration_e + 0.23*word_e + 0.18*density_e +
        0.18*repetition_e + 0.10*vad_e + 0.08*domain_e
    )
    if cleaned_words < 6 and speaking > 10:
        rel *= 0.65
    # No artificial 70/72 floor or ceiling. The value is entirely derived from
    # evidence terms above; the upper bound only enforces the probability domain.
    return float(clamp(rel, 0.0, 1.0))

def _pace_score(wpm: float, language: str) -> float:
    """Presentation pace scale with 90+ reserved for a narrow strong range."""
    lang = str(language or "auto").lower()
    if lang.startswith("vi"):
        pts=[(0,0),(90,30),(115,52),(135,72),(150,84),(165,91),(190,94),(205,91),(220,84),(240,72),(265,54),(300,30),(350,0)]
    else:
        pts=[(0,0),(70,22),(90,45),(105,64),(115,77),(125,87),(135,93),(155,94),(165,89),(175,82),(190,70),(205,56),(230,32),(270,0)]
    return piecewise_linear(wpm,pts)


def _scores(m: dict[str, Any], *, language: str, text_reliability: float) -> dict[str, Any]:
    speech_state = str(m.get("speech_state", "SPEECH_DETECTED"))
    if speech_state == "NO_SPEECH_DETECTED":
        return {
            "pace": None,
            "filler": None,
            "pause": None,
            "pause_control": None,
            "volume": None,
            "audibility": None,
            "volume_stability": None,
            "pace_stability": None,
            "fluency": None,
            "text_metric_reliability": round(100 * float(text_reliability), 1),
            "filler_metric_reliability": round(100 * float(m.get("filler_metric_reliability", text_reliability)), 1),
            "score_confidence": 0.0,
            "pace_used_in_overall": False,
            "fillers_used_in_overall": False,
            "pace_influence_weight": 0.0,
            "filler_influence_weight": 0.0,
            "overall": None,
            "audio_status": "N/A (No speech detected)",
        }

    pace = _pace_score(float(m["wpm"]), language)
    filler_reliability = float(m.get("filler_metric_reliability", text_reliability))
    # v6: filler scoring is intentionally stricter. Even 2-3 fillers/minute is
    # noticeable in a presentation, while zero fillers is excellent but not a magic 100.
    filler = piecewise_linear(float(m["fillers_per_minute"]), [(0,100),(.5,92),(1,88),(2,78),(3,68),(4,58),(5,48),(7,32),(10,15),(15,0)])

    # Pause control: setup silence is excluded. A genuine no-speech recording is
    # neutral rather than penalized for being silent.
    active_duration = max(float(m.get("active_duration_seconds", m.get("duration_seconds", 0.0))), 1e-6)
    speech_state = str(m.get("speech_state", "SPEECH_DETECTED"))
    if speech_state == "NO_SPEECH_DETECTED":
        pause = None
        excessive_ratio = 0.0
        longest = 0.0
        very_long = 0.0
    else:
        active_ratio = float(m.get("active_speaking_ratio", m.get("speaking_ratio", 0.0)))
        ratio_score = piecewise_linear(active_ratio, [(0,0),(.35,22),(.50,52),(.60,70),(.68,84),(.75,90),(.85,90),(.92,82),(.97,68),(1.0,55)])
        excessive_ratio = float(m.get("excessive_pause_time_seconds", 0.0)) / active_duration
        excessive_score = piecewise_linear(excessive_ratio, [(0,94),(.025,92),(.06,84),(.10,72),(.16,56),(.25,32),(.40,0)])
        longest = float(m.get("longest_pause_seconds", 0.0))
        longest_score = piecewise_linear(longest, [(0,92),(2.5,92),(4,86),(5,78),(7,62),(10,40),(15,18),(22,0)])
        very_long = float(m.get("very_long_pause_count", 0.0))
        minutes = max(active_duration / 60.0, 1e-6)
        very_long_rate = very_long / minutes
        repetition_score = piecewise_linear(very_long_rate, [(0,94),(.5,88),(1,78),(2,60),(4,32),(7,0)])
        pause = clamp(.36*ratio_score + .34*excessive_score + .18*longest_score + .12*repetition_score)

    # Cross-metric anti-gaming constraints.
    actual_wpm = _safe_float(m.get("wpm"), 0.0)
    min_filler_wpm = max(1.0, _safe_float(m.get("min_filler_wpm", 40.0), 40.0))
    pace_score_before_cross = float(pace)

    # 1) Abnormally slow speaking is itself a delivery issue; do not allow zero
    # transcript fillers to completely hide that problem.
    filler_wpm_factor = min(1.0, actual_wpm / min_filler_wpm)
    if actual_wpm < min_filler_wpm:
        filler = float(filler) * filler_wpm_factor

    if pace_score_before_cross < 30.0:
        if pause is not None:
            pause = min(float(pause), 35.0)
        filler = float(filler) * (pace_score_before_cross / 100.0)

    # 2) Voice Activity Ratio (VAR) is based on waveform/VAD, not transcript.
    duration = max(0.0, _safe_float(m.get("duration_seconds"), 0.0))
    speaking_time = max(0.0, _safe_float(m.get("speaking_time_seconds"), 0.0))
    var = speaking_time / duration if duration > 0.0 else 0.0
    dead_silence_warning = bool(
        speech_state == "SPEECH_DETECTED" and var < 0.40
    )
    if pause is not None and dead_silence_warning:
        pause *= 0.50

    # 3) Expose the derived evidence for report/feedback.
    m["actual_wpm_for_cross_metric"] = actual_wpm
    m["minimum_filler_wpm"] = min_filler_wpm
    m["filler_wpm_factor"] = filler_wpm_factor
    m["pace_score_before_cross_metric"] = pace_score_before_cross
    m["voice_activity_ratio"] = var
    m["abnormal_dead_silence"] = dead_silence_warning
    m["cross_metric_pace_cap_triggered"] = bool(pace_score_before_cross < 30.0)
    m["cross_metric_min_wpm_triggered"] = bool(actual_wpm < min_filler_wpm)

    # Absolute dBFS varies wildly between microphones.  SNR is therefore the main
    # audibility signal; absolute level and clipping are secondary guards.
    snr = float(m.get("speech_snr_db", 0.0))
    snr_score = piecewise_linear(snr, [(0,12),(6,38),(12,66),(18,84),(24,93),(35,96),(45,96)])
    avg_db = float(m.get("average_volume_dbfs", -80.0))
    level_score = piecewise_linear(avg_db, [(-70,0),(-55,18),(-45,45),(-38,68),(-32,84),(-26,92),(-12,92),(-6,65),(0,8)])
    clipping = float(m.get("clipping_ratio", 0.0))
    clip_score = piecewise_linear(clipping, [(0,96),(.0005,94),(.002,86),(.01,55),(.03,18),(.08,0)])
    volume = clamp(.72*snr_score + .10*level_score + .18*clip_score)

    vol_std = float(m.get("volume_stability_db_std", 0.0))
    volume_stability = piecewise_linear(vol_std, [(0,88),(2,92),(5,90),(8,82),(11,70),(15,54),(22,28),(30,0)])

    pace_cv = float(m.get("segment_pace_cv", 0.0))
    if len(m.get("segment_wpm_samples", [])) >= 3 and pace_cv > 0:
        pace_stability = piecewise_linear(pace_cv, [(0,88),(.10,92),(.18,88),(.28,78),(.40,64),(.60,38),(1.0,0)])
        pace_stability_rel = max(.45, text_reliability)
    else:
        density_std = float(m.get("speech_density_window_std", 0.0))
        pace_stability = piecewise_linear(density_std, [(0,88),(.08,92),(.15,88),(.22,80),(.30,68),(.42,44),(.60,0)])
        pace_stability_rel = 1.0

    # Reliability-weighted average: inaccurate local transcription can no longer
    # dominate the final score.  When the web transcript is supplied later,
    # text_reliability becomes 1.0 and WPM/filler regain their full intended weight.
    components = [
        (volume, 0.30, 1.0),
        (pause, 0.27, 0.0 if pause is None else 1.0),
        (volume_stability, 0.08, 1.0),
        (pace, 0.18, text_reliability),
        (filler, 0.10, filler_reliability),
        (pace_stability, 0.07, pace_stability_rel),
    ]
    num = sum(score * weight * rel for score, weight, rel in components if score is not None)
    den = sum(weight * rel for score, weight, rel in components if score is not None)
    overall = clamp(num / max(den, 1e-6))
    fluency = None if pause is None else clamp((.65*pause + .35*filler) if filler_reliability >= .70 else pause)

    # Confidence measures evidence quality, not presentation quality. v5 had a
    # built-in ~70-point floor; v6 starts low and grows only with enough speech,
    # usable SNR and trustworthy text.
    duration_conf = piecewise_linear(active_duration, [(0,0.0),(5,.22),(15,.48),(30,.68),(60,.82),(120,.90),(240,.94)])
    signal_conf = piecewise_linear(snr, [(-5,.10),(0,.20),(6,.42),(12,.65),(18,.82),(24,.90),(35,.94)])
    speech_evidence = piecewise_linear(float(m.get("speaking_time_seconds",0.0)), [(0,0.0),(5,.25),(15,.55),(30,.75),(60,.88),(120,.94)])
    score_confidence = clamp(100 * (0.45*duration_conf + 0.30*signal_conf + 0.15*speech_evidence + 0.10*text_reliability), 0, 96)
    pace_used = bool(text_reliability >= 0.50)
    filler_used = bool(filler_reliability >= 0.50)
    raw_scores = {
        "pace": pace,
        "filler": filler,
        "pause": pause,
        "pause_control": pause,
        "volume": volume,
        "audibility": volume,
        "volume_stability": volume_stability,
        "pace_stability": pace_stability,
        "fluency": fluency,
        "text_metric_reliability": 100*text_reliability,
        "filler_metric_reliability": 100*filler_reliability,
        "score_confidence": score_confidence,
        "pace_used_in_overall": pace_used,
        "fillers_used_in_overall": filler_used,
        "pace_influence_weight": float(0.18 * text_reliability if pace_used else 0.0),
        "filler_influence_weight": float(0.10 * filler_reliability if filler_used else 0.0),
        "overall": overall,
    }
    out: dict[str, Any] = {}
    for k, v in raw_scores.items():
        if isinstance(v, bool) or v is None:
            out[k] = v
        elif k in {"pace_influence_weight", "filler_influence_weight"}:
            out[k] = round(float(v), 4)
        else:
            out[k] = round(float(v), 1)
    return out

def _feedback(m: dict[str, Any], s: dict[str, float]) -> list[str]:
    out: list[str] = []
    text_rel = float(m.get("text_metric_reliability", 1.0))
    wpm = float(m.get("wpm", 0.0) or 0.0)
    if m.get("speech_state") == "NO_SPEECH_DETECTED":
        return ["No clear speech was detected; pause and silence were not penalized."]
    if text_rel >= 0.55:
        if wpm < 110:
            out.append(f"Speaking pace is relatively slow ({wpm:.0f} WPM); speed up slightly if the explanation feels drawn out.")
        elif wpm > 180:
            out.append(f"Speaking pace is relatively fast ({wpm:.0f} WPM); slow down around important ideas.")
        else:
            out.append(f"Speaking pace is within a broad presentation range ({wpm:.0f} WPM).")

        fpm = float(m["fillers_per_minute"])
        filler_rel = float(m.get("filler_metric_reliability", text_rel))
        # Filler feedback is stricter than semantic-transcript feedback. Local Whisper
        # can normalize hesitation sounds, so we only make a concrete filler claim
        # when filler-specific reliability is high. External/web transcript = 1.0.
        if filler_rel >= 0.75 and fpm >= 2.5:
            top = sorted(m["filler_words"].items(), key=lambda kv: kv[1], reverse=True)[:3]
            if top:
                out.append("Repeated non-lexical fillers were detected: " + ", ".join(f"{w}×{n}" for w,n in top) + ".")
    else:
        out.append("Transcript-derived pace/filler metrics have limited confidence in this local run; final web transcript should replace them when available.")

    if m.get("filler_guard_triggered"):
        out.append("ASR repetition was detected; filler metrics were guarded against an implausible transcription loop.")
    if m.get("abnormal_dead_silence"):
        out.append("Abnormal dead silence was detected: more than 60% of the recording contained no active speech.")
    if m.get("cross_metric_pace_cap_triggered"):
        out.append("Very slow speaking pace was severe enough to cap pause-control and filler scores so slow delivery could not hide behind clean filler counts.")
    if m.get("implicit_filler_count", 0):
        out.append(
            f"{int(m['implicit_filler_count'])} prolonged vowel-like hesitation(s) were detected acoustically."
        )
    if float(m.get("excessive_pause_time_seconds", 0.0)) > max(2.0, 0.05*float(m.get("duration_seconds",0.0))):
        out.append(f"Some silent gaps were long enough to interrupt flow; longest pause was {m['longest_pause_seconds']:.1f} s.")
    if s["volume"] < 65:
        out.append("Speech audibility is weak relative to the background noise; reduce noise or keep the microphone closer and stable.")
    if float(m["clipping_ratio"]) > 0.002:
        out.append("Audio clipping was detected; reduce mic gain or move farther away.")
    if s["pace_stability"] < 60:
        out.append("Delivery rhythm changes a lot across the session; review whether those changes are intentional.")
    return out[:6]

def analyze_audio(
    audio_path: str | Path,
    *,
    whisper_model_dir: str | Path,
    device: str,
    language: str,
    cache_dir: str | Path,
    transcript: str | None = None,
    cfg: AudioConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or AudioConfig()
    transcript_supplied = transcript is not None
    total_start = time.perf_counter()
    audio, sr = librosa.load(str(audio_path), sr=cfg.sample_rate, mono=True)

    t0 = time.perf_counter()
    raw = _speech_activity(audio, sr, cfg)
    feature_seconds = time.perf_counter() - t0
    speech_regions = raw.pop("asr_regions_samples", [])

    segments: list[dict[str, Any]] = []
    asr_seconds = 0.0
    asr_used_device = "SKIPPED"
    transcript_raw = transcript or ""
    asr_quality: dict[str, Any] = {
        "hallucination_suspected": False,
        "repetition_removed_words": 0,
        "longest_identical_word_run": 0,
        "raw_word_count": _count_words(transcript_raw),
        "clean_word_count": _count_words(transcript_raw),
        "vad_chunk_count": len(speech_regions),
        "repeated_phrase_removed_words": 0,
        "domain_correction_count": 0,
    }

    preliminary_no_speech = (
        float(raw.get("speaking_time_seconds", 0.0)) < cfg.min_speech_seconds_for_scoring
        or float(raw.get("active_speaking_ratio", 0.0)) < cfg.min_active_speaking_ratio_for_scoring
        or float(raw.get("speech_snr_db", 0.0)) < cfg.min_speech_snr_db_for_scoring
    )
    if transcript is None and not preliminary_no_speech:
        transcript, transcript_raw, segments, asr_seconds, asr_used_device, asr_quality = transcribe_openvino(
            audio,
            whisper_model_dir,
            device=device,
            language=language,
            cache_dir=cache_dir,
            sr=sr,
            speech_regions=speech_regions,
            cfg=cfg,
        )
    elif transcript is None and preliminary_no_speech:
        transcript = ""
        transcript_raw = ""
        segments = []
        asr_seconds = 0.0
        asr_used_device = "SKIPPED_NO_SPEECH"
        asr_quality.update({
            "hallucination_suspected": False,
            "raw_word_count": 0,
            "clean_word_count": 0,
            "skipped_for_no_speech": True,
        })
    else:
        # Clarivo web deliberately keeps Cloudflare Whisper + the user's edited
        # transcript as the source of truth. Phase 20's local ASR/domain-rewrite
        # path is not used for web sessions. We retain only conservative repetition
        # guards for metric stability; they never overwrite the transcript shown in UI.
        domain_corrections = 0
        transcript, phrase_removed = _collapse_repeated_phrases(
            transcript,
            max_phrase_words=getattr(cfg, "max_repeated_phrase_words", 6),
            max_occurrences=getattr(cfg, "max_repeated_phrase_occurrences", 2),
        )
        transcript, removed, longest = _collapse_pathological_repetitions(
            transcript, max_repeat=cfg.max_consecutive_same_word
        )
        asr_quality.update(
            {
                "repetition_removed_words": removed,
                "longest_identical_word_run": longest,
                "raw_word_count": _count_words(transcript_raw),
                "clean_word_count": _count_words(transcript),
                "hallucination_suspected": longest >= 6,
                "repeated_phrase_removed_words": int(phrase_removed),
                "domain_correction_count": int(domain_corrections),
            }
        )

    implicit_filler = _detect_vowel_prolongation(
        audio,
        sr,
        speech_regions,
        min_duration_seconds=cfg.prolonged_vowel_seconds,
    )

    word_count = _count_words(transcript or "")
    session_duration_min = max(raw["duration_seconds"] / 60.0, 1e-6)
    duration_min = max(raw.get("active_duration_seconds", raw["duration_seconds"]) / 60.0, 1e-6)
    speaking_min = max(raw["speaking_time_seconds"] / 60.0, 1e-6)

    filler_count_transcript, filler_words_raw = _count_fillers(transcript or "", cfg.filler_words)
    discourse_count, discourse_markers = _count_fillers(transcript or "", cfg.discourse_markers)
    implicit_count = int(implicit_filler.get("implicit_filler_count", 0))
    filler_count_raw = int(
        filler_count_transcript
        + round(implicit_count * float(cfg.prolonged_vowel_equivalent_fillers))
    )

    # Physical plausibility guard: even if ASR loops, a 30 s clip cannot reasonably
    # contain hundreds of distinct hesitation events. We cap only when the ASR quality
    # detector already sees a suspicious transcript or the count is extreme.
    max_plausible_fillers = max(4, int(raw["duration_seconds"] * cfg.filler_guard_per_second))
    filler_guard = bool(
        filler_count_raw > max_plausible_fillers
        and (asr_quality.get("hallucination_suspected") or filler_count_raw > max_plausible_fillers * 2)
    )
    filler_count = min(filler_count_raw, max_plausible_fillers) if filler_guard else filler_count_raw
    filler_words = dict(filler_words_raw)
    if implicit_count > 0:
        filler_words["[prolonged_vowel]"] = implicit_count
    if filler_guard and filler_count_raw > 0:
        scale = filler_count / filler_count_raw
        filler_words = {k: int(round(v * scale)) for k, v in filler_words.items() if int(round(v * scale)) > 0}

    seg_wpms, seg_cv = _segment_pace(segments, cfg)
    global_wpm = word_count / duration_min
    # Segment timestamps can be noisy, so use them only as a small correction when
    # several plausible samples agree with the global active-span estimate.
    plausible_seg = [x for x in seg_wpms if 55 <= x <= 280]
    robust_wpm = global_wpm
    if len(plausible_seg) >= 3:
        med = float(np.median(plausible_seg))
        if 0.60*global_wpm <= med <= 1.65*max(global_wpm,1e-6):
            robust_wpm = 0.80*global_wpm + 0.20*med

    metrics = {
        **raw,
        "word_count": word_count,
        "wpm": robust_wpm,
        "wpm_global_active_span": global_wpm,
        "session_wpm_including_setup_silence": word_count / session_duration_min,
        "articulation_wpm": word_count / speaking_min,
        "filler_count": filler_count,
        "filler_count_transcript": int(filler_count_transcript),
        "implicit_filler_count": int(implicit_count),
        "implicit_filler_durations_seconds": implicit_filler.get("implicit_filler_durations_seconds", []),
        "implicit_filler_source": implicit_filler.get("implicit_filler_source", "none"),
        "fillers_per_minute": filler_count / duration_min,
        "filler_words": filler_words,
        "filler_count_before_guard": filler_count_raw,
        "filler_guard_triggered": filler_guard,
        "discourse_marker_count": discourse_count,
        "discourse_markers": discourse_markers,
        "segment_wpm_samples": [round(x,1) for x in seg_wpms],
        "segment_pace_cv": seg_cv,
        "min_filler_wpm": float(cfg.min_filler_wpm),
        "prolonged_vowel_seconds": float(cfg.prolonged_vowel_seconds),
    }
    metrics.pop("pause_durations", None)
    for k, v in list(metrics.items()):
        if isinstance(v, float):
            metrics[k] = round(v, 4)

    text_reliability = _text_reliability(
        transcript_supplied=transcript_supplied,
        asr_quality=asr_quality,
        language=language,
        metrics=metrics,
    )
    metrics["text_metric_source"] = "external_transcript" if transcript_supplied else "openvino_whisper"
    metrics["text_metric_reliability"] = round(text_reliability, 3)
    metrics["pace_metric_reliability"] = round(text_reliability, 3)
    metrics["speech_state"] = _classify_speech_state(raw, text_reliability, cfg)
    metrics["no_speech_detected"] = metrics["speech_state"] == "NO_SPEECH_DETECTED"
    metrics["audio_status"] = (
        "N/A (No speech detected)" if metrics["no_speech_detected"] else "SPEECH_DETECTED"
    )
    if metrics["no_speech_detected"]:
        metrics["longest_pause_seconds"] = 0.0
        metrics["long_pause_count"] = 0
        metrics["very_long_pause_count"] = 0
        metrics["excessive_pause_time_seconds"] = 0.0
    metrics["domain_correction_count"] = int(asr_quality.get("domain_correction_count", 0) or 0)
    if metrics["no_speech_detected"]:
        metrics.update({
            "word_count": 0,
            "wpm": None,
            "wpm_global_active_span": None,
            "session_wpm_including_setup_silence": None,
            "articulation_wpm": None,
            "filler_count": 0,
            "filler_count_transcript": 0,
            "implicit_filler_count": 0,
            "implicit_filler_durations_seconds": [],
            "implicit_filler_source": "none",
            "fillers_per_minute": None,
            "filler_words": {},
            "filler_count_before_guard": 0,
            "filler_guard_triggered": False,
            "discourse_marker_count": 0,
            "discourse_markers": {},
            "segment_wpm_samples": [],
            "segment_pace_cv": 0.0,
        })
    # Filler confidence is intentionally stricter than ordinary transcript confidence
    # because Whisper can normalize hesitation sounds even when semantic text is good.
    filler_rel = 1.0 if transcript_supplied else text_reliability * (
        0.85 if not asr_quality.get("hallucination_suspected") else 0.30
    )
    metrics["filler_metric_reliability"] = round(float(filler_rel),3)
    metrics["transcript_confidence_method"] = "evidence-based ASR quality heuristic (no token logprob available in current OpenVINO pipeline)"
    scores = _scores(metrics, language=language, text_reliability=text_reliability)
    if metrics["speech_state"] == "NO_SPEECH_DETECTED":
        scores["pace_used_in_overall"] = False
        scores["fillers_used_in_overall"] = False
        scores["pace_influence_weight"] = 0.0
        scores["filler_influence_weight"] = 0.0
    total = time.perf_counter() - total_start
    return {
        "audio_score": scores["overall"],
        "metrics": metrics,
        "scores": scores,
        "feedback": _feedback(metrics, scores),
        "transcript": transcript or "",
        "transcript_raw": transcript_raw,
        "transcript_segments": segments,
        "asr_quality": asr_quality,
        "benchmark": {
            "feature_analysis_seconds": round(feature_seconds,3),
            "asr_seconds": round(asr_seconds,3),
            "total_audio_analysis_seconds": round(total,3),
            "audio_realtime_factor_x": round(raw["duration_seconds"] / max(total,1e-6), 2),
            "asr_requested_device": device,
            "asr_used_device": asr_used_device,
        },
    }
