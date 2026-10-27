"""앱 아이콘(packaging/TONEROOM.icns) 생성. 검은 바탕에 필름 한 칸, 암부 청록 → 명부 크림빛 그라데이션(스플릿 토닝).
외부 이미지 라이브러리 없이 numpy로 그린 뒤 macOS sips·iconutil로 icns를 만든다."""
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

import numpy as np

N = 1024
HERE = Path(__file__).parent


def mask_rounded(x0, y0, x1, y1, r):
    yy, xx = np.mgrid[0:N, 0:N]
    cx = np.clip(xx, x0 + r, x1 - r)
    cy = np.clip(yy, y0 + r, y1 - r)
    return ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r) & (xx >= x0) & (xx <= x1) & (yy >= y0) & (yy <= y1)


def png(path, rgba):
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    img = np.zeros((N, N, 4), np.uint8)
    img[mask_rounded(100, 100, 924, 924, 185)] = (14, 14, 16, 255)  # macOS 아이콘 격자에 맞춘 여백
    # 필름 한 칸: 왼쪽 아래(암부) 청록 → 오른쪽 위(명부) 크림
    frame = mask_rounded(200, 300, 824, 724, 36)
    yy, xx = np.mgrid[0:N, 0:N]
    t = np.clip(((xx - 200) / 624 * 0.7 + (724 - yy) / 424 * 0.3), 0, 1)[..., None]
    shadow, highlight = np.array([28, 92, 104]), np.array([246, 224, 184])
    grad = (shadow * (1 - t) + highlight * t).astype(np.uint8)
    img[frame, :3] = grad[frame]
    img[frame, 3] = 255
    # 필름 구멍(위·아래)
    for x in range(232, 800, 72):
        for y0 in (196, 762):
            img[mask_rounded(x, y0, x + 40, y0 + 62, 10)] = (236, 236, 232, 255)

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base.png"
        png(base, img)
        iconset = Path(tmp) / "TONEROOM.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(size * scale), str(size * scale), str(base), "--out", str(iconset / name)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "TONEROOM.icns")], check=True)
        png(HERE / "icon.png", img)
    print(HERE / "TONEROOM.icns")


if __name__ == "__main__":
    main()
