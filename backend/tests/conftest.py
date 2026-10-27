"""합성 테스트 영상(ffmpeg lavfi)으로 실제 파이프라인을 검증한다."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_DATA = tempfile.mkdtemp(prefix="eva95-test-")
os.environ["EVA95_DATA"] = _DATA  # eva95 임포트 전에 설정(테스트가 실제 data/를 건드리지 않게)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eva95.probe import ffmpeg_bin  # noqa: E402


def ff(*args: str) -> None:
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", *args], check=True)


SRC = "testsrc2=s={s}:r={r}:d={d}"


@pytest.fixture(scope="session")
def media(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("media")
    m = {
        "land": d / "land.mp4",
        "portrait": d / "portrait.mov",
        "silent": d / "silent.mp4",
        "vfr": d / "vfr.mp4",
        "unicode": d / "여행 클립 ①.mp4",
        "dark": d / "dark.mp4",
        "bright": d / "bright.mp4",
        "truncated": d / "truncated.mp4",
        "garbage": d / "garbage.mkv",
    }
    sine = ["-f", "lavfi", "-i", "sine=f=440:d={d}"]
    common = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
    ff("-f", "lavfi", "-i", SRC.format(s="640x360", r=30, d=2), *[a.format(d=2) for a in sine], *common, str(m["land"]))
    ff("-f", "lavfi", "-i", SRC.format(s="360x640", r=30, d=2), *[a.format(d=2) for a in sine], *common, str(m["portrait"]))
    ff("-f", "lavfi", "-i", SRC.format(s="640x360", r=25, d=2), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(m["silent"]))
    # 앞 1초는 30fps, 뒤는 15fps 간격 → 가변 프레임레이트
    ff("-f", "lavfi", "-i", SRC.format(s="640x360", r=30, d=3), *[a.format(d=3) for a in sine],
       "-vf", "setpts='if(lt(N,30),N/30,1+(N-30)/15)/TB'", "-fps_mode", "vfr", *common, str(m["vfr"]))
    ff("-f", "lavfi", "-i", SRC.format(s="640x360", r=24, d=2), *[a.format(d=2) for a in sine], *common, str(m["unicode"]))
    ff("-f", "lavfi", "-i", SRC.format(s="640x360", r=30, d=2), "-vf", "lutrgb=r=val*0.45:g=val*0.45:b=val*0.5",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(m["dark"]))
    ff("-f", "lavfi", "-i", SRC.format(s="640x360", r=30, d=2), "-vf", "lutrgb=r=val*0.8+40:g=val*0.8+38:b=val*0.75+30",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(m["bright"]))
    m["truncated"].write_bytes(m["land"].read_bytes()[:3000])
    m["garbage"].write_bytes(os.urandom(50000))
    return m
