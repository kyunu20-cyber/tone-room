"""모든 보정 파라미터의 단일 정의.

각 파라미터의 중립값(neutral)은 "효과 없음"이다. 프리셋은 이 스키마 위에 값을 덮어쓴다.
공간 단위(px) 파라미터는 짧은 변 1080px 기준이고, 실제 해상도에 비례해 스케일된다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParamDef:
    key: str
    group: str
    label: str
    kind: str  # "float" | "bool" | "int"
    neutral: Any
    min: float = 0.0
    max: float = 1.0
    step: float = 0.01
    hint: str = ""


PARAM_DEFS: list[ParamDef] = [
    # MASTER
    ParamDef("intensity", "MASTER", "Look intensity", "float", 1.0, 0.0, 1.5, 0.01, "전체 효과 강도(0 = 원본, 1 = 프리셋 그대로, 1.5 = 더 강하게)"),
    # IPHONE LOOK
    ParamDef("hdr_tonemap", "IPHONE LOOK", "HDR tone mapping", "float", 0.0, 0.0, 1.0, 0.01, "주변 밝기 기준으로 암부는 올리고 명부는 눌러 스마트 HDR처럼"),
    ParamDef("vibrance", "IPHONE LOOK", "Vibrance", "float", 0.0, -1.0, 1.0, 0.01, "채도 낮은 색만 올림, 피부는 보호"),
    ParamDef("deyellow", "IPHONE LOOK", "Yellow cast removal", "float", 0.0, 0.0, 1.0, 0.01, "전구 조명 누런기 제거: 중간톤·명부를 중립으로, 노란 피부는 혈색 쪽으로"),
    ParamDef("noise_reduction", "IPHONE LOOK", "Noise reduction", "float", 0.0, 0.0, 1.0, 0.01, "웹캠·저조도 자글거림 완화(윤곽 보존)"),
    ParamDef("sharpness", "IPHONE LOOK", "Detail", "float", 0.0, 0.0, 1.0, 0.01, "윤곽 위주 선명도. 노이즈 많은 영상은 낮게"),
    # COLOR
    ParamDef("contrast", "COLOR", "Contrast", "float", 0.0, 0.0, 1.0, 0.01, "필름 S-커브 대비"),
    ParamDef("saturation", "COLOR", "Saturation", "float", 1.0, 0.0, 2.0, 0.01, "채도 배율"),
    ParamDef("gamma", "COLOR", "Gamma", "float", 1.0, 0.6, 1.6, 0.01, "1보다 크면 중간톤이 밝아짐"),
    ParamDef("shadow_compression", "COLOR", "Shadow compression", "float", 0.0, 0.0, 1.0, 0.01, "암부 토 압축"),
    ParamDef("highlight_rolloff", "COLOR", "Highlight roll-off", "float", 0.0, 0.0, 1.0, 0.01, "명부 숄더 롤오프"),
    ParamDef("cel_color", "COLOR", "Cel color response", "float", 0.0, 0.0, 1.0, 0.01, "셀 물감 색 경향(하늘 청록·녹색 올리브·빨강 깊게)"),
    ParamDef("split_toning", "COLOR", "Split toning", "float", 0.0, 0.0, 1.0, 0.01, "암부 청록·명부 따뜻하게"),
    ParamDef("warmth", "COLOR", "Warmth", "float", 0.0, -1.0, 1.0, 0.01, "색온도"),
    ParamDef("tint", "COLOR", "Tint", "float", 0.0, -1.0, 1.0, 0.01, "+ 녹색 / - 마젠타"),
    ParamDef("skin_protect", "COLOR", "Skin protection", "float", 0.8, 0.0, 1.0, 0.01, "피부 영역의 색 변화 억제"),
    # TEXTURE
    ParamDef("grain_strength", "TEXTURE", "Grain strength", "float", 0.0, 0.0, 1.0, 0.01),
    ParamDef("grain_size", "TEXTURE", "Grain size", "float", 1.0, 0.5, 3.0, 0.05, "입자 크기(px)"),
    ParamDef("grain_color", "TEXTURE", "Grain chroma", "float", 0.0, 0.0, 1.0, 0.01, "0이면 모노크롬"),
    ParamDef("grain_temporal", "TEXTURE", "Grain temporal coherence", "float", 0.0, 0.0, 1.0, 0.01, "인접 프레임 입자 상관"),
    ParamDef("softness", "TEXTURE", "Optical softness", "float", 0.0, 0.0, 1.0, 0.01, "윤곽은 유지하고 미세 디테일만 약화"),
    ParamDef("halation", "TEXTURE", "Halation", "float", 0.0, 0.0, 1.0, 0.01, "밝은 영역 붉은 확산"),
    # ANALOG
    ParamDef("gate_weave", "ANALOG", "Gate weave", "float", 0.0, 0.0, 1.0, 0.01),
    ParamDef("weave_frequency", "ANALOG", "Weave frequency", "float", 0.6, 0.1, 3.0, 0.05, "Hz"),
    ParamDef("misregistration", "ANALOG", "Chromatic misregistration", "float", 0.0, 0.0, 1.0, 0.01),
    ParamDef("bloom_strength", "ANALOG", "Highlight bloom", "float", 0.0, 0.0, 1.0, 0.01),
    ParamDef("bloom_threshold", "ANALOG", "Bloom threshold", "float", 0.8, 0.5, 1.0, 0.01),
    ParamDef("bloom_radius", "ANALOG", "Bloom radius", "float", 18.0, 2.0, 60.0, 1.0, "px"),
    ParamDef("film_aging", "ANALOG", "Film aging", "float", 0.0, 0.0, 1.0, 0.01, "페이드·블랙 리프트"),
    # MOTION
    ParamDef("cadence_12fps", "MOTION", "12 FPS animation simulation", "bool", False, hint="24fps 컨테이너에서 2프레임마다 반복"),
    # SHOT MATCHING
    ParamDef("shot_matching", "SHOT MATCHING", "Auto shot matching", "bool", True),
    ParamDef("shot_match_strength", "SHOT MATCHING", "Shot match strength", "float", 0.7, 0.0, 1.0, 0.01),
    ParamDef("target_exposure", "SHOT MATCHING", "Target exposure", "float", 0.42, 0.25, 0.6, 0.01, "목표 휘도 중앙값"),
    ParamDef("target_contrast", "SHOT MATCHING", "Target contrast", "float", 0.22, 0.12, 0.32, 0.01, "목표 휘도 표준편차"),
    ParamDef("target_saturation", "SHOT MATCHING", "Target saturation", "float", 0.32, 0.15, 0.55, 0.01, "목표 평균 채도"),
    # MISC
    ParamDef("seed", "MISC", "Random seed", "int", 1995, 0, 999999, 1),
]

DEFS_BY_KEY = {d.key: d for d in PARAM_DEFS}
NEUTRAL: dict[str, Any] = {d.key: d.neutral for d in PARAM_DEFS}


def normalize(values: dict[str, Any] | None) -> dict[str, Any]:
    """중립값 위에 값을 덮어쓰고 범위를 강제한다. 모르는 키는 버린다."""
    out = dict(NEUTRAL)
    for k, v in (values or {}).items():
        d = DEFS_BY_KEY.get(k)
        if d is None or v is None:
            continue
        if d.kind == "bool":
            out[k] = bool(v)
        elif d.kind == "int":
            out[k] = int(min(max(int(v), d.min), d.max))
        else:
            out[k] = float(min(max(float(v), d.min), d.max))
    return out


# intensity가 곱해지는 "효과량" 파라미터(임계값·반경·주파수·크기·보호 같은 설정값은 제외)
SCALED_BY_INTENSITY = ("contrast", "saturation", "gamma", "shadow_compression", "highlight_rolloff", "cel_color",
                       "split_toning", "warmth", "tint", "grain_strength", "grain_color", "softness", "halation",
                       "gate_weave", "misregistration", "bloom_strength", "film_aging",
                       "hdr_tonemap", "vibrance", "noise_reduction", "sharpness", "deyellow")


def effective(values: dict[str, Any]) -> dict[str, Any]:
    """intensity를 반영한 실제 처리값. 각 효과를 중립값에서 얼마나 벗어나게 할지에 intensity를 곱한다."""
    p = normalize(values)
    k = p["intensity"]
    if k != 1.0:
        for key in SCALED_BY_INTENSITY:
            d = DEFS_BY_KEY[key]
            v = d.neutral + (p[key] - d.neutral) * k
            p[key] = float(min(max(v, d.min), d.max))
    return p


def params_hash(values: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(normalize(values), sort_keys=True).encode()).hexdigest()[:16]


def schema() -> list[dict[str, Any]]:
    return [d.__dict__ for d in PARAM_DEFS]


@dataclass
class ExportSettings:
    resolution: str = "original"  # original | 1080p | 4k
    fps: str = "original"  # original | 23.976 | 24 | 30
    codec: str = "h264"  # h264 | h265
    quality: str = "high"  # standard | high | maximum
    output_dir: str = ""
    upscale: str = "sharp"  # standard | sharp | ai  (출력이 원본보다 클 때만 의미 있음)
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict | None) -> "ExportSettings":
        d = d or {}
        s = cls(
            resolution=d.get("resolution", "original"),
            fps=str(d.get("fps", "original")),
            codec=d.get("codec", "h264"),
            quality=d.get("quality", "high"),
            output_dir=d.get("output_dir", "") or "",
            upscale=d.get("upscale", "sharp") or "sharp",
        )
        if s.resolution not in ("original", "1080p", "4k"):
            raise ValueError(f"지원하지 않는 해상도: {s.resolution}")
        if s.fps not in ("original", "23.976", "24", "30"):
            raise ValueError(f"지원하지 않는 프레임레이트: {s.fps}")
        if s.codec not in ("h264", "h265"):
            raise ValueError(f"지원하지 않는 코덱: {s.codec}")
        if s.upscale not in ("standard", "sharp", "ai"):
            raise ValueError(f"지원하지 않는 업스케일 방식: {s.upscale}")
        if s.quality not in ("standard", "high", "maximum"):
            raise ValueError(f"지원하지 않는 품질: {s.quality}")
        return s
