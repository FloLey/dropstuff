"""Phase 1: E1 audio analysis."""
from __future__ import annotations

from kaika.core.analyze import analyze
from kaika.core.score import Score


def test_frame_count_matches_fps(track_wav):
    fps = 24
    score = analyze(track_wav, fps=fps)
    expected = score.audio.duration_s * fps
    # one row per video frame, within a couple of frames of duration*fps
    assert abs(score.n_frames - expected) <= 3
    assert score.audio.hop_length == round(score.audio.sr / fps)


def test_tempo_detected(track_wav):
    score = analyze(track_wav, fps=24)
    # beat tracking can land on an octave; accept 120 or its common multiples
    assert any(abs(score.tempo_bpm - t) < 6 for t in (60, 120, 240))
    assert len(score.beats) >= 4


def test_low_onsets_present(track_wav):
    score = analyze(track_wav, fps=24)
    # kicks every 0.5s over 4s -> several low-band onsets
    assert len(score.onsets["low"]) >= 4
    assert all(0.0 <= e.mag <= 1.0 for e in score.onsets["low"])


def test_onsets_are_precise_not_noisy(track_wav):
    """HPSS + strict peak picking: counts must stay near the real event counts
    (8 kicks, 8 hats), not balloon — every onset spawns a visual source."""
    score = analyze(track_wav, fps=24)
    assert len(score.onsets["low"]) <= 14      # was 23 before HPSS
    assert 5 <= len(score.onsets["high"]) <= 12
    # mid-track kicks land on the beat grid (±1 frame)
    times = [e.t for e in score.onsets["low"]]
    for expected in (0.5, 1.0, 1.5, 2.0, 2.5):
        assert any(abs(t - expected) < 0.06 for t in times), expected


def test_bands_normalised(track_wav):
    score = analyze(track_wav, fps=24)
    for f in score.frames:
        assert abs(sum(f.bands) - 1.0) < 1e-3 or sum(f.bands) == 0.0
        assert 0.0 <= f.rms <= 1.0


def test_sections_cover_track(track_wav):
    score = analyze(track_wav, fps=24)
    assert len(score.sections) >= 2
    assert score.sections[0].start == 0.0
    assert abs(score.sections[-1].end - score.audio.duration_s) < 0.1
    # sections are contiguous
    for a, b in zip(score.sections, score.sections[1:]):
        assert abs(a.end - b.start) < 1e-6


def test_json_roundtrip(track_wav, tmp_path):
    score = analyze(track_wav, fps=24)
    p = tmp_path / "score.json"
    score.to_json(p)
    again = Score.from_json(p)
    assert again.tempo_bpm == score.tempo_bpm
    assert again.n_frames == score.n_frames
    assert again.sections[0].label == score.sections[0].label
