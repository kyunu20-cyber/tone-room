"""프레임 보정 파이프라인(아이폰 룩 + EVA-95 룩).

화풍은 바꾸지 않는다. 형태·디테일을 재구성하는 연산(양자화, 포스터라이즈, 페인팅 스무딩)은 없고,
색·톤·필름 질감만 다룬다. 모든 난수는 (seed, frame_index)로 고정해 미리보기와 최종 렌더가 같다.
"""
from __future__ import annotations

import math
import threading
from collections import OrderedDict

import cv2
import numpy as np

from .params import effective

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


_HUE_STEPS = 4  # 0.25° 단위 LUT
_hue_tables: dict[tuple[float, float], np.ndarray] = {}


def _hue_window(h: np.ndarray, center: float, width: float) -> np.ndarray:
    """색상 h(0~360) 주변 가우시안 창. 지수 계산 대신 LUT 조회."""
    t = _hue_tables.get((center, width))
    if t is None:
        x = np.arange(360 * _HUE_STEPS + 1, dtype=np.float64) / _HUE_STEPS
        d = np.abs((x - center + 180.0) % 360.0 - 180.0)
        t = _hue_tables[(center, width)] = np.exp(-0.5 * (d / width) ** 2).astype(np.float32)
    return t[(h * _HUE_STEPS).astype(np.int32)]


def skin_mask(frame_u8: np.ndarray) -> np.ndarray:
    """YCrCb 범위 기반 부드러운 피부 마스크(0~1). 1/4 해상도에서 계산 후 확대."""
    h, w = frame_u8.shape[:2]
    small = cv2.resize(frame_u8, (max(1, w // 4), max(1, h // 4)), interpolation=cv2.INTER_AREA)
    ycc = cv2.cvtColor(small, cv2.COLOR_RGB2YCrCb).astype(np.float32)
    y, cr, cb = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    m = (_smoothstep(cr, 133, 142) * (1 - _smoothstep(cr, 168, 178))
         * _smoothstep(cb, 80, 88) * (1 - _smoothstep(cb, 124, 132)) * _smoothstep(y, 40, 70))
    m = cv2.GaussianBlur(m, (0, 0), 1.5)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)


def build_luts(p: dict, shot: dict | None) -> np.ndarray:
    """픽셀 단위 연산(샷매칭 게인·대비, WB, 감마, 토/숄더, S-커브, 에이징)을 채널별 256 LUT 하나로 합친다."""
    x = np.arange(256, dtype=np.float64) / 255.0
    luts = np.empty((3, 256), dtype=np.float32)
    aging, warm, tint, dy = p["film_aging"], p["warmth"], p["tint"], p["deyellow"]
    chan_gain = np.array([1 + 0.07 * warm + 0.04 * aging, 1 + 0.05 * tint, 1 - 0.07 * warm - 0.05 * aging])
    for c in range(3):
        y = x.copy()
        if shot:
            y = y * shot["gains"][c]
            piv = shot.get("pivot", 0.42)
            y = piv + (y - piv) * shot["contrast"]
        y = np.clip(y * chan_gain[c], 0, 1)
        if p["gamma"] != 1.0:
            y = np.power(y, 1.0 / p["gamma"])
        a = p["shadow_compression"] * 0.35
        if a > 0:  # 토: f(0)=0, f(1)=1, 암부 압축
            y = y * y * (1 + a) / (y + a)
        a = p["highlight_rolloff"] * 0.35
        if a > 0:  # 숄더: 토를 뒤집어 명부를 부드럽게 눌러줌
            z = 1 - y
            y = 1 - z * z * (1 + a) / (z + a)
        k = p["contrast"] * 0.9
        if k > 0:
            y = y + (y * y * (3 - 2 * y) - y) * k
        st = p["split_toning"]
        if st > 0:  # 암부 → 청록, 명부 → 따뜻하게(채널별 가산, 중간톤은 거의 그대로)
            sh, hi = (1 - y) ** 2 * y * 4, y ** 2 * (1 - y) * 4
            y = y + st * np.array([-0.05 * sh + 0.035 * hi, 0.012 * sh + 0.012 * hi, 0.07 * sh - 0.04 * hi])[c]
        if dy > 0:  # 전구 조명 캐스트는 중간톤·명부에 몰려 있으므로 암부는 덜 건드림
            y = y + dy * _smoothstep(y, 0.12, 0.6) * (-0.065, -0.012, 0.13)[c] * (1.15 - y)
        lift = 0.07 * aging
        y = lift + y * (1 - lift - 0.03 * aging)
        luts[c] = np.clip(y, 0, 1)
    return luts


class Grader:
    def __init__(self, params: dict, width: int, height: int, fps: float, shot: dict | None = None):
        self.p = effective(params)
        self.w, self.h, self.fps = width, height, float(fps) or 24.0
        self.scale = min(width, height) / 1080.0
        self.shot = shot if (shot and self.p["shot_matching"]) else None
        if self.shot:  # 강도는 분석 결과 원본에 적용
            self.shot = scale_correction(self.shot, self.p["shot_match_strength"])
        self.luts = build_luts(self.p, self.shot)
        self.identity_lut = np.allclose(self.luts, np.arange(256) / 255.0, atol=1e-6)
        rs = np.random.default_rng(self.p["seed"] + 7)
        self.weave_phase = rs.uniform(0, 2 * math.pi, 6)
        self._noise_cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 단계

    def _color(self, f: np.ndarray, src: np.ndarray) -> np.ndarray:
        p = self.p
        sat = p["saturation"] * (self.shot["saturation"] if self.shot else 1.0) * (1 - 0.25 * p["film_aging"])
        cel, vib, dy = p["cel_color"], p["vibrance"], p["deyellow"]
        if abs(sat - 1) < 1e-4 and cel <= 0 and vib == 0 and dy <= 0:
            return f
        hsv = cv2.cvtColor(f, cv2.COLOR_RGB2HSV)  # float32: H 0~360, S/V 0~1
        H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        protect = skin_mask(src) * p["skin_protect"]
        S_new = S * sat
        if vib != 0:  # 채도 낮은 색일수록 크게, 이미 진한 색은 거의 그대로
            S_new = S_new * (1 + 0.6 * vib * (1 - S_new) ** 2)
        if cel > 0:
            gate = _smoothstep(S, 0.04, 0.18) * (1 - protect)  # 무채색·피부는 건드리지 않음
            wb = _hue_window(H, 210, 32) * gate   # 하늘·파랑 → 청록 쪽
            wg = _hue_window(H, 110, 35) * gate   # 녹색 → 올리브 쪽, 약간 차분하게
            wr = _hue_window(H, 0, 16) * gate     # 빨강 → 깊게
            dh = (195 - H) * 0.35 * cel * wb + (85 - H) * 0.3 * cel * wg
            H = (H + dh) % 360.0
            S_new = S_new * (1 + 0.14 * cel * wb - 0.1 * cel * wg + 0.15 * cel * wr)
            V = V * (1 - 0.05 * cel * wr)
        S = S_new + (S - S_new) * protect * 0.7
        if dy > 0:  # 노랑 계열 채도를 낮추고, 누렇게 뜬 피부(약 30°)는 혈색 쪽(약 20°)으로
            gate = _smoothstep(S, 0.05, 0.2)
            wy, ws = _hue_window(H, 52, 16) * gate, _hue_window(H, 31, 9) * gate
            H = (H - 10 * dy * ws) % 360.0
            S = S * (1 - 0.4 * dy * wy - 0.15 * dy * ws)
        hsv = np.stack([H, np.clip(S, 0, 1), np.clip(V, 0, 1)], axis=-1)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)

    def _denoise(self, frame: np.ndarray) -> np.ndarray:
        """uint8 입력의 자글거림 완화. 휘도는 윤곽 보존 필터, 색 노이즈는 크로마만 블러."""
        n = self.p["noise_reduction"]
        if n <= 0:
            return frame
        sig = max(0.6, 1.6 * self.scale)
        out = cv2.bilateralFilter(frame, 0, 6 + 22 * n, sig)
        ycc = cv2.cvtColor(out, cv2.COLOR_RGB2YCrCb)
        ycc[..., 1:] = cv2.GaussianBlur(ycc[..., 1:], (0, 0), sig * (1 + 1.5 * n))
        out = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2RGB)
        return cv2.addWeighted(out, min(1.0, 0.4 + 0.6 * n), frame, 1 - min(1.0, 0.4 + 0.6 * n), 0)

    def _hdr(self, f: np.ndarray) -> np.ndarray:
        """국소 톤매핑: 주변 밝기(base)가 어두우면 올리고 밝으면 누른다. 디테일(f/base)은 그대로."""
        s = self.p["hdr_tonemap"]
        if s <= 0:
            return f
        y = np.clip(f @ LUMA, 1e-4, 1)
        base = 0.65 * self._downblur(y, 24 * self.scale) + 0.35 * y  # 일부 원래 휘도를 섞어 헤일로 억제
        lift = 0.55 * s * base * (1 - base) ** 2  # 암부 리프트(중간톤 이상은 거의 그대로)
        comp = 0.5 * s * _smoothstep(base, 0.55, 1.0) * (base - 0.55)  # 명부 압축
        t = base + lift - comp
        gain = np.clip(t / np.maximum(base, 1e-4), 0.75, 2.2)
        return f * gain[..., None]

    def _sharpen(self, f: np.ndarray, edges: np.ndarray) -> np.ndarray:
        s = self.p["sharpness"]
        if s <= 0:
            return f
        blur = cv2.GaussianBlur(f, (0, 0), 0.9 * max(self.scale, 0.5))
        return f + (f - blur) * (0.9 * s * (0.25 + 0.75 * edges))[..., None]  # 평탄부(노이즈)는 약하게

    def _edges(self, f: np.ndarray) -> np.ndarray:
        y = f @ LUMA
        gx = cv2.Sobel(y, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(y, cv2.CV_32F, 0, 1, ksize=3)
        e = np.clip(cv2.magnitude(gx, gy) * 3.0, 0, 1)
        return cv2.GaussianBlur(e, (0, 0), 1.2 * max(self.scale, 0.5))

    def _softness(self, f: np.ndarray, edges: np.ndarray) -> np.ndarray:
        s = self.p["softness"]
        if s <= 0:
            return f
        blur = cv2.GaussianBlur(f, (0, 0), (0.5 + 1.1 * s) * self.scale)
        amt = (s * 0.65) * (1 - 0.75 * edges)  # 윤곽(얼굴선 등)은 유지
        return f + (blur - f) * amt[..., None]

    def _downblur(self, img: np.ndarray, sigma: float) -> np.ndarray:
        """1/4 해상도에서 블러 후 원래 크기로(블룸·할레이션용, 넓은 반경을 싸게)."""
        sw, sh = max(1, self.w // 4), max(1, self.h // 4)
        small = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), max(0.5, sigma / 4))
        return cv2.resize(small, (self.w, self.h), interpolation=cv2.INTER_LINEAR)

    def _bloom_halation(self, f: np.ndarray) -> np.ndarray:
        p = self.p
        if p["bloom_strength"] <= 0 and p["halation"] <= 0:
            return f
        y = f @ LUMA
        if p["bloom_strength"] > 0:
            th = p["bloom_threshold"]
            mask = np.clip((y - th) / max(1 - th, 1e-3), 0, 1) ** 1.5
            b = self._downblur(f * mask[..., None], p["bloom_radius"] * self.scale)
            b = np.clip(b * p["bloom_strength"] * 0.9, 0, 0.6)  # 상한: 화면을 덮지 않게
            f = 1 - (1 - f) * (1 - b)
        if p["halation"] > 0:
            hi = np.clip((y - 0.7) / 0.3, 0, 1) ** 2
            hal = self._downblur(hi, 10 * self.scale) * p["halation"]
            f = f.copy()
            f[..., 0] += hal * 0.18
            f[..., 1] += hal * 0.04
        return f

    def _shift(self, ch: np.ndarray, dx: float, dy: float) -> np.ndarray:
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(ch, m, (self.w, self.h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

    def _misregistration(self, f: np.ndarray, edges: np.ndarray) -> np.ndarray:
        d = self.p["misregistration"] * 0.9 * self.scale
        if d <= 0:
            return f
        wgt = 0.35 + 0.65 * edges  # 경계 부근에서만 또렷하게
        out = f.copy()
        for c, sx in ((0, d), (2, -d)):
            moved = self._shift(np.ascontiguousarray(f[..., c]), sx, 0.35 * sx)
            out[..., c] = f[..., c] + (moved - f[..., c]) * wgt
        return out

    def _noise(self, index: int, shape: tuple[int, int], gs: float) -> np.ndarray:
        with self._lock:
            hit = self._noise_cache.get(index)
        if hit is not None:
            return hit
        h, w = shape
        gh, gw = max(2, int(round(h / gs))), max(2, int(round(w / gs)))
        rng = np.random.default_rng([self.p["seed"], index & 0xFFFFFFFF])
        n = rng.standard_normal((gh, gw), dtype=np.float32)
        if (gh, gw) != (h, w):
            n = cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC if gs > 1 else cv2.INTER_AREA)
        n = cv2.GaussianBlur(n, (0, 0), 0.45 * max(gs, 0.6))  # 둥근 입자 모양
        n /= max(float(n[::7, ::7].std()), 1e-6)
        with self._lock:
            self._noise_cache[index] = n
            while len(self._noise_cache) > 6:
                self._noise_cache.popitem(last=False)
        return n

    def _grain(self, f: np.ndarray, index: int) -> np.ndarray:
        p = self.p
        amp = p["grain_strength"] * 0.075
        if amp <= 0:
            return f
        gs = max(0.5, p["grain_size"] * self.scale)
        n = self._noise(index, (self.h, self.w), gs)
        a = p["grain_temporal"] * 0.8
        if a > 0:
            n = (n + a * self._noise(index - 1, (self.h, self.w), gs)) / math.sqrt(1 + a * a)
        y = np.clip(f @ LUMA, 0, 1)
        weight = 0.3 + 0.7 * (4 * y * (1 - y))  # 중간톤에서 가장 강하고 극단에서 약함
        out = f + (amp * weight * n)[..., None]
        if p["grain_color"] > 0:
            rng = np.random.default_rng([p["seed"] + 1, index & 0xFFFFFFFF])
            # 색 입자: 저해상도 3채널 노이즈에서 평균을 빼 색 성분만
            ch, cw = max(2, int(self.h / (gs * 2))), max(2, int(self.w / (gs * 2)))
            cn = rng.standard_normal((ch, cw, 3), dtype=np.float32)
            cn -= cn.mean(axis=2, keepdims=True)
            cn = cv2.resize(cn, (self.w, self.h), interpolation=cv2.INTER_CUBIC)
            out += cn * (amp * p["grain_color"] * 0.6) * weight[..., None]
        return out

    def weave_offset(self, index: int) -> tuple[float, float]:
        amp = self.p["gate_weave"] * 1.5 * self.scale
        if amp <= 0:
            return 0.0, 0.0
        t, fq, ph = index / self.fps, self.p["weave_frequency"], self.weave_phase
        tau = 2 * math.pi * fq * t
        dx = 0.62 * math.sin(tau + ph[0]) + 0.28 * math.sin(2.31 * tau + ph[1]) + 0.10 * math.sin(5.17 * tau + ph[2])
        dy = 0.62 * math.sin(0.83 * tau + ph[3]) + 0.28 * math.sin(1.97 * tau + ph[4]) + 0.10 * math.sin(4.3 * tau + ph[5])
        return amp * dx, amp * 0.6 * dy

    def _weave(self, f: np.ndarray, index: int) -> np.ndarray:
        dx, dy = self.weave_offset(index)
        if dx == 0 and dy == 0:
            return f
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(f, m, (self.w, self.h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

    # ------------------------------------------------------------ 전체

    def process(self, frame: np.ndarray, index: int) -> np.ndarray:
        """uint8 RGB(h,w,3) → uint8 RGB. index는 출력 프레임 번호."""
        if frame.shape[:2] != (self.h, self.w):
            frame = cv2.resize(frame, (self.w, self.h), interpolation=cv2.INTER_AREA)
        frame = self._denoise(frame)
        if self.identity_lut:
            f = frame.astype(np.float32) * (1 / 255.0)
        else:
            f = np.empty(frame.shape, dtype=np.float32)
            for c in range(3):
                f[..., c] = self.luts[c][frame[..., c]]
        f = self._hdr(f)
        f = self._color(f, frame)
        need_edges = self.p["softness"] > 0 or self.p["misregistration"] > 0 or self.p["sharpness"] > 0
        edges = self._edges(f) if need_edges else None
        f = self._softness(f, edges)
        f = self._sharpen(f, edges)
        f = self._bloom_halation(f)
        f = self._misregistration(f, edges)
        f = self._grain(f, index)
        f = self._weave(f, index)
        return (np.clip(f, 0, 1) * 255.0 + 0.5).astype(np.uint8)


def scale_correction(c: dict, k: float) -> dict:
    """샷매칭 보정량에 강도 k(0~1)를 곱한다. 게인은 로그 공간에서 보간."""
    return {
        "gains": [float(g) ** k for g in c["gains"]],
        "contrast": 1 + (c["contrast"] - 1) * k,
        "saturation": 1 + (c["saturation"] - 1) * k,
        "pivot": c.get("pivot", 0.42),
    }
