"""EVA-95 SHOT MATCHING.

클립의 첫 프레임과 대표 프레임을 분석해 노출·화이트밸런스·대비·채도를 프리셋 목표값 쪽으로 맞추는
클립 단위 고정 보정값을 만든다. 프레임마다 다시 계산하지 않으므로 노출이 출렁이지 않는다.
보정은 Grader의 LUT 첫 단계(게인 → 피벗 대비)와 채도 배율로 적용된다.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .grade import LUMA, skin_mask
from .probe import VideoInfo
from .video_io import grab_frame

ANALYSIS_SHORT = 360


def sample_times(duration: float, n: int) -> list[float]:
    if n <= 1 or duration <= 0.2:
        return [0.0]
    return [0.0] + [duration * (0.05 + 0.9 * i / (n - 2)) for i in range(n - 1)]


def crop_bars(f: np.ndarray, thresh: int = 12) -> np.ndarray:
    """레터박스·필러박스(가장자리의 거의 검은 행·열)를 잘라낸다. 화면 대부분이 어두워도 내용은 남긴다."""
    rows = np.flatnonzero(f.max(axis=(1, 2)) > thresh)
    cols = np.flatnonzero(f.max(axis=(0, 2)) > thresh)
    if len(rows) < f.shape[0] * 0.1 or len(cols) < f.shape[1] * 0.1:
        return f  # 전체가 어두운 장면은 그대로 분석
    return f[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def analyze_frames(frames: list[np.ndarray]) -> dict:
    """uint8 RGB 프레임 목록 → 통계. 검은 띠는 빼고 화면 내용만 본다."""
    frames = [crop_bars(f) for f in frames]
    lit_frames = [f for f in frames if f.mean() > 8]  # 페이드인·암전 프레임 제외
    frames = lit_frames or frames
    rgb = np.concatenate([f.reshape(-1, 3) for f in frames]).astype(np.float32) / 255.0
    skin = np.concatenate([skin_mask(f).reshape(-1) for f in frames])
    y = rgb @ LUMA
    mx, mn = rgb.max(axis=1), rgb.min(axis=1)
    sat = np.where(mx > 1e-4, (mx - mn) / np.maximum(mx, 1e-4), 0)
    lit = y > 0.06

    # 화이트밸런스: 피부·클리핑·극단 휘도를 빼고, 무채색에 가까운 픽셀 우선(gray-world 변형)
    base = (skin < 0.3) & (y > 0.15) & (y < 0.85) & (mx < 0.97)
    neutral = base & (sat < 0.35)
    wb_px = rgb[neutral] if neutral.sum() > 500 else rgb[base] if base.sum() > 500 else rgb
    skin_px = rgb[skin > 0.6]

    per_frame_median = [float(np.median(f.reshape(-1, 3).astype(np.float32) @ LUMA) / 255.0) for f in frames]
    return {
        "frames": len(frames),
        "median": float(np.median(y)),
        "p1": float(np.percentile(y, 1)),
        "p995": float(np.percentile(y, 99.5)),
        "channel_p995": [float(np.percentile(rgb[:, c], 99.5)) for c in range(3)],
        "std": float(y.std()),
        "saturation": float(sat[lit].mean()) if lit.any() else 0.0,
        "clip_high": float((y > 0.98).mean()),
        "clip_low": float((y < 0.02).mean()),
        "wb_means": [float(v) for v in wb_px.mean(axis=0)],
        "skin_mean": [float(v) for v in skin_px.mean(axis=0)] if len(skin_px) > 200 else None,
        "skin_fraction": float((skin > 0.6).mean()),
        "frame_medians": per_frame_median,
    }


def analyze_clip(info: VideoInfo, n: int = 12) -> dict:
    frames = [grab_frame(info, t, ANALYSIS_SHORT) for t in sample_times(info.duration, n)]
    return analyze_frames(frames)


def _hue(rgb: np.ndarray) -> float:
    px = np.clip(np.asarray(rgb, dtype=np.float32).reshape(1, 1, 3), 0, 1)
    return float(cv2.cvtColor(px, cv2.COLOR_RGB2HSV)[0, 0, 0])


def compute_correction(stats: dict, target_exposure: float = 0.42, target_contrast: float = 0.22,
                       target_saturation: float = 0.32) -> dict:
    """통계 → 보정값(강도 100% 기준). 하이라이트 클리핑·섀도 뭉개짐·피부색 이동을 제한한다."""
    med = max(stats["median"], 1e-3)
    notes: list[str] = []

    # 1) 노출 게인
    g = float(np.clip(target_exposure / med, 0.6, 1.8))
    if g > 1:
        cap = max(1.0, 0.97 / max(stats["p995"], 1e-3))
        if g > cap:
            notes.append("하이라이트 보호로 노출 상승 제한")
        g = min(g, cap)
    elif g < 1:
        # 흰 벽·하늘이 많은 장면에서 흰색이 회색으로 탁해지지 않게: 하이라이트는 0.88 이상 유지
        floor = min(1.0, 0.88 / max(stats["p995"], 1e-3))
        if g < floor:
            notes.append("흰색 보존으로 노출 하강 제한")
        g = max(g, floor)

    # 2) 화이트밸런스(부분 적용, 휘도 보존)
    m = np.maximum(np.array(stats["wb_means"], dtype=np.float64), 1e-3)
    wb = np.clip((m.mean() / m) ** 0.6, 0.88, 1.14)
    wb /= wb @ LUMA
    if stats.get("skin_mean"):
        skin = np.array(stats["skin_mean"])
        shift = abs((_hue(skin * wb) - _hue(skin) + 180) % 360 - 180)
        if shift > 4.0:  # 피부색이 4° 이상 돌면 WB를 그만큼 약화
            wb = wb ** (4.0 / shift)
            wb /= wb @ LUMA
            notes.append("피부색 보호로 화이트밸런스 약화")

    gains = g * wb
    worst = max(p * k for p, k in zip(stats["channel_p995"], gains))
    if worst > 0.985 and g > 1:  # 채널별로도 클리핑이 늘지 않게
        gains *= max(0.985 / worst, 1 / g)

    # 3) 대비(피벗 = 목표 노출)
    eff_g = float(gains @ LUMA)
    piv = target_exposure
    # 대비는 올리는 쪽 위주. 이미 강한 대비를 깎으면 프리셋 효과가 상쇄되므로 최대 8%까지만 낮춘다
    c = float(np.clip(target_contrast / max(stats["std"] * eff_g, 1e-3), 0.92, 1.25))
    if c > 1:
        lo = stats["p1"] * eff_g
        if piv - lo > 1e-3 and piv + (lo - piv) * c < 0.004:
            c = max(1.0, (piv - 0.004) / (piv - lo))
            notes.append("섀도 보호로 대비 제한")
        hi = stats["p995"] * eff_g
        if hi - piv > 1e-3 and piv + (hi - piv) * c > 0.975:
            c = max(1.0, min(c, (0.975 - piv) / (hi - piv)))
            notes.append("하이라이트 보호로 대비 제한")

    # 4) 채도
    s = float(np.clip(target_saturation / max(stats["saturation"], 1e-3), 0.9, 1.25))

    return {
        "gains": [float(v) for v in gains],
        "contrast": c,
        "saturation": s,
        "pivot": piv,
        "exposure_ev": math.log2(max(eff_g, 1e-6)),
        "wb": [float(v) for v in wb],
        "notes": notes,
    }


def correction_for(stats: dict, params: dict) -> dict:
    return compute_correction(stats, params["target_exposure"], params["target_contrast"], params["target_saturation"])
