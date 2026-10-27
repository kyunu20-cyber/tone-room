import cv2
import numpy as np

from eva95.grade import Grader, skin_mask
from eva95.params import NEUTRAL, normalize
from eva95.presets import BUILTIN_ORDER, get_preset


def scene(h=360, w=640, seed=0):
    """그라디언트 + 도형 + 텍스처가 있는 결정적 테스트 이미지."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([x / w, y / h, 0.5 + 0.3 * np.sin(x / 23)], -1)
    img += rng.normal(0, 0.02, img.shape)
    img = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    cv2.rectangle(img, (100, 80), (260, 240), (230, 230, 230), -1)
    cv2.circle(img, (450, 200), 70, (20, 20, 30), -1)
    cv2.putText(img, "EVA95", (300, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 40, 40), 3)
    return img


def edge_map(img):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))


def test_neutral_is_identity():
    img = scene()
    out = Grader(NEUTRAL, 640, 360, 30).process(img, 5)
    assert np.array_equal(out, img)


def test_deterministic_and_frame_varying_grain():
    img = scene()
    p = {"grain_strength": 0.6}
    a = Grader(p, 640, 360, 30).process(img, 10)
    b = Grader(p, 640, 360, 30).process(img, 10)
    c = Grader(p, 640, 360, 30).process(img, 11)
    assert np.array_equal(a, b)
    assert np.abs(a.astype(int) - c.astype(int)).mean() > 0.5


def test_presets_preserve_structure():
    """화풍을 바꾸지 않는다: 모든 내장 프리셋에서 윤곽 구조가 원본과 강하게 상관돼야 한다."""
    img = scene()
    e0 = edge_map(img).ravel()
    for pid in BUILTIN_ORDER:
        p = get_preset(pid)["params"]
        out = Grader(p, 640, 360, 30).process(img, 3)
        r = np.corrcoef(e0, edge_map(out).ravel())[0, 1]
        assert r > 0.8, (pid, r)
        # 평균 색이 크게 틀어지지 않음(보정 범위)
        assert np.abs(out.astype(float).mean((0, 1)) - img.astype(float).mean((0, 1))).max() < 30, pid


def test_grain_is_luminance_aware():
    img = np.zeros((360, 640, 3), np.uint8)
    img[:, :320] = 8      # 거의 검정
    img[:, 320:] = 128    # 중간톤
    out = Grader({"grain_strength": 1.0}, 640, 360, 30).process(img, 1).astype(float)
    assert out[:, 330:].std() > out[:, :310].std() * 1.4


def test_weave_is_subtle_and_smooth():
    p = get_preset("eva95_original_tv")["params"]
    g = Grader(p, 1920, 1080, 24)
    offs = np.array([g.weave_offset(i) for i in range(240)])
    assert np.abs(offs).max() < 0.5  # 기본값: 0.5px 미만
    assert np.abs(np.diff(offs, axis=0)).max() < 0.1  # 프레임 간 급변 없음(0.1px 미만)


def test_bloom_does_not_overpower():
    img = scene()
    p = normalize({"bloom_strength": 1.0, "bloom_threshold": 0.5, "bloom_radius": 60})
    out = Grader(p, 640, 360, 30).process(img, 0).astype(float)
    assert out.mean() - img.astype(float).mean() < 40
    assert (out[260:300, 480:600] < 255).any()


def test_misregistration_default_subpixel():
    img = scene()
    p = normalize({"misregistration": get_preset("eva95_original_tv")["params"]["misregistration"]})
    out = Grader(p, 640, 360, 30).process(img, 0).astype(float)
    assert np.abs(out - img).mean() < 1.5


def test_skin_mask_and_protection():
    skin = np.full((64, 64, 3), (205, 150, 120), np.uint8)  # 전형적 피부톤
    sky = np.full((64, 64, 3), (90, 140, 210), np.uint8)
    assert skin_mask(skin).mean() > 0.8
    assert skin_mask(sky).mean() < 0.1
    img = np.hstack([skin, sky])
    p = normalize({"cel_color": 1.0, "saturation": 1.5, "skin_protect": 1.0})
    out = Grader(p, 128, 64, 30).process(img, 0)
    hsv0 = cv2.cvtColor(img.astype(np.float32) / 255, cv2.COLOR_RGB2HSV)
    hsv1 = cv2.cvtColor(out.astype(np.float32) / 255, cv2.COLOR_RGB2HSV)
    skin_ds = abs(hsv1[:, :64, 1].mean() - hsv0[:, :64, 1].mean())
    sky_ds = abs(hsv1[:, 64:, 1].mean() - hsv0[:, 64:, 1].mean())
    assert skin_ds < sky_ds * 0.5
    assert abs(hsv1[:, :64, 0].mean() - hsv0[:, :64, 0].mean()) < 3


def test_intensity_scales_effect():
    img = scene()
    p = get_preset("eva95_original_tv")["params"]
    zero = Grader({**p, "intensity": 0.0, "shot_matching": False}, 640, 360, 30).process(img, 2)
    assert np.abs(zero.astype(int) - img.astype(int)).max() <= 1  # 0이면 원본
    d1 = np.abs(Grader({**p, "intensity": 1.0}, 640, 360, 30).process(img, 2).astype(int) - img).mean()
    d15 = np.abs(Grader({**p, "intensity": 1.5}, 640, 360, 30).process(img, 2).astype(int) - img).mean()
    assert d15 > d1 > 0
