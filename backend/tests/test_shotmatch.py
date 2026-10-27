import numpy as np

from eva95.grade import LUMA, Grader
from eva95.presets import get_preset
from eva95.probe import probe
from eva95.shotmatch import analyze_clip, analyze_frames, compute_correction, correction_for
from eva95.video_io import grab_frame

P = get_preset("eva95_original_tv")["params"]


def corrected_median(info, strength=1.0):
    st = analyze_clip(info, 6)
    p = {**P, "shot_match_strength": strength, "grain_strength": 0, "gate_weave": 0}
    fr = grab_frame(info, 1.0, 360)
    out = Grader(p, fr.shape[1], fr.shape[0], 30, correction_for(st, p)).process(fr, 0)
    y0 = (fr.astype(np.float32) / 255) @ LUMA
    y1 = (out.astype(np.float32) / 255) @ LUMA
    return float(np.median(y0)), float(np.median(y1)), float((y0 > 0.98).mean()), float((y1 > 0.98).mean())


def test_shot_matching_converges_different_exposures(media):
    d0, d1, _, _ = corrected_median(probe(media["dark"]))
    b0, b1, bc0, bc1 = corrected_median(probe(media["bright"]))
    assert abs(b1 - d1) < abs(b0 - d0) * 0.7, (d0, d1, b0, b1)


def test_strength_zero_equals_off(media):
    info = probe(media["dark"])
    st = analyze_clip(info, 4)
    fr = grab_frame(info, 0.5, 360)
    h, w = fr.shape[:2]
    off = Grader({**P, "shot_matching": False}, w, h, 30).process(fr, 0)
    zero = Grader({**P, "shot_match_strength": 0.0}, w, h, 30, correction_for(st, P)).process(fr, 0)
    assert np.abs(off.astype(int) - zero.astype(int)).max() <= 1


def test_no_highlight_clipping_or_shadow_crush():
    # 이미 밝고 하이라이트가 많은 장면: 노출을 올리지 말아야 함
    stats = {"median": 0.30, "p1": 0.02, "p995": 0.99, "channel_p995": [0.99, 0.99, 0.99], "std": 0.15,
             "saturation": 0.3, "wb_means": [0.5, 0.5, 0.5], "skin_mean": None}
    c = compute_correction(stats)
    assert max(c["gains"]) <= 1.0 + 1e-6
    lo = stats["p1"] * float(np.mean(c["gains"]))
    assert c["pivot"] + (lo - c["pivot"]) * c["contrast"] >= 0.0


def test_white_scene_not_greyed():
    stats = {"median": 0.75, "p1": 0.3, "p995": 0.97, "channel_p995": [0.97] * 3, "std": 0.15,
             "saturation": 0.1, "wb_means": [0.7, 0.7, 0.7], "skin_mean": None}
    c = compute_correction(stats)
    assert stats["p995"] * min(c["gains"]) >= 0.87  # 흰색이 흰색으로 남음


def test_skin_hue_protected_under_color_cast():
    rng = np.random.default_rng(0)
    frame = np.full((120, 160, 3), (110, 120, 170), np.uint8)  # 파란 조명
    frame[30:90, 50:110] = (205, 150, 120)  # 피부
    frame = np.clip(frame + rng.normal(0, 3, frame.shape), 0, 255).astype(np.uint8)
    c = compute_correction(analyze_frames([frame]))
    assert "피부색 보호로 화이트밸런스 약화" in c["notes"] or max(c["wb"]) / min(c["wb"]) < 1.12


def test_correction_constant_over_time():
    """프레임마다 같은 보정(노출 출렁임 없음): 같은 입력은 프레임 번호와 무관하게 같은 결과."""
    st = {"median": 0.2, "p1": 0.02, "p995": 0.6, "channel_p995": [0.6] * 3, "std": 0.1, "saturation": 0.2,
          "wb_means": [0.3, 0.3, 0.35], "skin_mean": None}
    frame = np.full((90, 160, 3), 70, np.uint8)
    g = Grader({**P, "grain_strength": 0, "gate_weave": 0}, 160, 90, 30, compute_correction(st))
    outs = [g.process(frame, i) for i in (0, 50, 500)]
    assert all(np.array_equal(outs[0], o) for o in outs[1:])
