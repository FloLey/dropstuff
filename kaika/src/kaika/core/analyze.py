"""E1 — Audio analysis.  audio file -> Score (score.json).

Offline, full-track analysis with librosa. The hop length is locked to the
target video framerate so every video frame gets exactly one row of audio
data with no interpolation. Because ``sr / fps`` is not always an integer
(e.g. 44100 / 24 = 1837.5), the hop is rounded and the per-frame timestamps
are recomputed from real time, which bounds the drift to a fraction of a frame.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import librosa

from .score import Score, AudioInfo, Event, FrameData, Section

N_FFT = 2048
LOW_HZ = 150.0
HIGH_HZ = 4000.0


def _normalise(x: np.ndarray) -> np.ndarray:
    """Scale to 0..1 by max, robust to all-zero input."""
    x = np.asarray(x, dtype=np.float64)
    peak = float(np.max(x)) if x.size else 0.0
    return x / peak if peak > 1e-12 else np.zeros_like(x)


def _band_onsets(S_band: np.ndarray, sr: int, hop: int) -> List[Event]:
    """Detect onsets within a single frequency band's magnitude spectrogram."""
    if S_band.shape[0] == 0:
        return []
    env = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S_band, ref=np.max),
                                       sr=sr, hop_length=hop)
    if env.max() <= 0:
        return []
    frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop,
                                        backtrack=False)
    if len(frames) == 0:
        return []
    times = librosa.frames_to_time(frames, sr=sr, hop_length=hop)
    mags = _normalise(env[frames])
    return [Event(t=float(t), mag=float(m)) for t, m in zip(times, mags)]


def _label_sections(boundaries_t: List[float], duration: float,
                    energies: List[float]) -> List[Section]:
    """Heuristic labelling: ends are intro/outro, the rest build/drop by energy."""
    sections: List[Section] = []
    n = len(boundaries_t) - 1
    e_norm = _normalise(np.array(energies)) if energies else np.array([])
    for i in range(n):
        start, end = boundaries_t[i], boundaries_t[i + 1]
        e = float(e_norm[i]) if i < len(e_norm) else 0.0
        if i == 0:
            label = "intro"
        elif i == n - 1:
            label = "outro"
        elif e >= 0.66:
            label = "drop"
        elif e >= 0.33:
            label = "build"
        else:
            label = "verse"
        sections.append(Section(start=round(start, 3), end=round(end, 3),
                                label=label, energy=round(e, 3)))
    return sections


def analyze(audio_path: str | Path, fps: int = 24,
            target_sr: int | None = None) -> Score:
    """Analyse ``audio_path`` and return a frame-aligned :class:`Score`.

    Parameters
    ----------
    fps : target video framerate; the analysis hop is ``round(sr / fps)``.
    target_sr : optional resample rate. Pick one that divides evenly by ``fps``
        (e.g. 48000 for 24 fps) to eliminate hop rounding drift entirely.
    """
    y, sr = librosa.load(str(audio_path), sr=target_sr, mono=True)
    duration = float(len(y) / sr)
    hop = int(round(sr / fps))

    # Single STFT drives every frame-aligned feature.
    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=hop))
    n = S.shape[1]
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)

    rms = _normalise(librosa.feature.rms(S=S)[0])
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)[0]

    low_mask = freqs < LOW_HZ
    high_mask = freqs > HIGH_HZ
    mid_mask = ~low_mask & ~high_mask
    band_low = S[low_mask].sum(0)
    band_mid = S[mid_mask].sum(0)
    band_high = S[high_mask].sum(0)
    band_tot = band_low + band_mid + band_high + 1e-9
    frames = [
        FrameData(
            rms=round(float(rms[i]), 4),
            centroid_hz=round(float(centroid[i]), 1),
            bands=[round(float(band_low[i] / band_tot[i]), 4),
                   round(float(band_mid[i] / band_tot[i]), 4),
                   round(float(band_high[i] / band_tot[i]), 4)],
        )
        for i in range(n)
    ]

    # Tempo + beats.
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop)
    tempo_bpm = float(np.atleast_1d(tempo)[0])
    onset_env = librosa.onset.onset_strength(S=S, sr=sr, hop_length=hop)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    beat_strength = _normalise(onset_env[beat_frames]) if len(beat_frames) else np.array([])
    beats = [Event(t=round(float(t), 3), mag=round(float(s), 3))
             for t, s in zip(beat_times, beat_strength)]

    onsets = {
        "low": _band_onsets(S[low_mask], sr, hop),
        "mid": _band_onsets(S[mid_mask], sr, hop),
        "high": _band_onsets(S[high_mask], sr, hop),
    }

    # Structural sections via agglomerative clustering on chroma+mfcc.
    sections = _segment(y, sr, hop, S, rms, duration)

    return Score(
        audio=AudioInfo(sr=int(sr), duration_s=round(duration, 3), fps=fps,
                        hop_length=hop),
        tempo_bpm=round(tempo_bpm, 2),
        beats=beats,
        onsets=onsets,
        frames=frames,
        sections=sections,
    )


def _segment(y, sr, hop, S, rms, duration) -> List[Section]:
    """Boundaries from agglomerative clustering, ~one section per 25s."""
    k = max(2, min(8, int(round(duration / 25.0)) + 1))
    chroma = librosa.feature.chroma_stft(S=S ** 2, sr=sr)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=hop, n_mfcc=13)
    # Align feature lengths to the chroma frame count.
    m = min(chroma.shape[1], mfcc.shape[1], len(rms))
    feat = np.vstack([chroma[:, :m], mfcc[:, :m]])
    try:
        bound_frames = librosa.segment.agglomerative(feat, k)
    except Exception:
        bound_frames = np.linspace(0, m - 1, k + 1).astype(int)
    bound_frames = np.unique(np.concatenate([[0], bound_frames, [m]]))
    bound_t = librosa.frames_to_time(bound_frames, sr=sr, hop_length=hop).tolist()
    bound_t[0] = 0.0
    bound_t[-1] = duration
    energies = []
    for i in range(len(bound_t) - 1):
        f0 = bound_frames[i]
        f1 = max(f0 + 1, bound_frames[i + 1])
        energies.append(float(np.mean(rms[f0:f1])) if f1 <= len(rms) else 0.0)
    return _label_sections(bound_t, duration, energies)
