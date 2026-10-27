"""ffmpeg 설치 확인과 입력 영상 검증."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

SUPPORTED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
STANDARD_FPS = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
                Fraction(50), Fraction(60000, 1001), Fraction(60)]


class VideoError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류."""


def ffmpeg_bin() -> str:
    """앱에 함께 든 ffmpeg(imageio-ffmpeg 정적 빌드)를 먼저, 없으면 시스템 ffmpeg."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 — 패키지가 없거나 바이너리를 못 찾음
        pass
    p = shutil.which("ffmpeg")
    if not p:
        raise VideoError("FFmpeg를 찾을 수 없습니다. 터미널에서 `brew install ffmpeg`로 설치하세요.")
    return p


@dataclass
class VideoInfo:
    path: str
    width: int  # 회전 반영 후 표시 크기
    height: int
    fps: Fraction  # CFR 기준 프레임레이트(VFR이면 가까운 표준값)
    duration: float
    frame_count: int
    codec: str
    pix_fmt: str
    is_vfr: bool
    has_audio: bool
    audio_codec: str | None
    color_matrix: str  # 디코드에 쓸 in_color_matrix
    hdr: str | None  # "hlg" | "pq" | None
    rotation: int

    def to_json(self) -> dict:
        d = asdict(self)
        d["fps"] = float(self.fps)
        d["fps_str"] = f"{self.fps.numerator}/{self.fps.denominator}"
        return d


def snap_fps(f: Fraction) -> Fraction:
    best = min(STANDARD_FPS, key=lambda s: abs(float(s) - float(f)))
    return best if abs(float(best) - float(f)) / float(f) < 0.04 else f.limit_denominator(1001)


def probe(path: str | Path) -> VideoInfo:
    path = Path(path)
    if not path.exists():
        raise VideoError(f"파일이 없습니다: {path.name}")
    if path.suffix.lower() not in SUPPORTED_EXT:
        raise VideoError(f"지원하지 않는 형식입니다({path.suffix}). MP4, MOV, MKV, WEBM만 가능합니다.")
    if path.stat().st_size == 0:
        raise VideoError("빈 파일입니다.")
    # ffprobe 없이 `ffmpeg -i`가 stderr에 찍는 스트림 정보를 읽는다(앱에 ffmpeg 하나만 넣기 위해)
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    v, a, duration, rotation = _parse_info(r.stderr)
    if v is None and a is None:
        raise VideoError(f"영상을 읽을 수 없습니다. 손상됐거나 지원하지 않는 파일입니다. ({_last(r.stderr, path)})")
    if v is None:
        raise VideoError("영상 트랙이 없습니다.")

    w, h = v["width"], v["height"]
    if w <= 0 or h <= 0:
        raise VideoError("영상 크기를 알 수 없습니다. 파일이 손상됐을 수 있습니다.")
    if abs(rotation) % 180 == 90:
        w, h = h, w

    r_rate, avg_rate = v["tbr"], v["fps"]
    base = avg_rate or r_rate
    if base is None:
        raise VideoError("프레임레이트를 알 수 없습니다.")
    is_vfr = bool(r_rate and avg_rate and abs(float(r_rate) - float(avg_rate)) / float(avg_rate) > 0.01)
    fps = snap_fps(base)

    if duration <= 0:
        raise VideoError("영상 길이를 알 수 없습니다. 파일이 손상됐을 수 있습니다.")

    trc = v["trc"]
    hdr = "hlg" if trc == "arib-std-b67" else "pq" if trc == "smpte2084" else None
    cs = v["space"]
    if hdr or cs.startswith("bt2020"):
        matrix = "bt2020"
    elif cs in ("bt709",):
        matrix = "bt709"
    elif cs in ("smpte170m", "bt470bg"):
        matrix = "bt601"
    else:
        matrix = "bt709" if min(w, h) >= 720 else "bt601"

    return VideoInfo(
        path=str(path), width=w, height=h, fps=fps, duration=duration,
        frame_count=max(1, int(round(duration * float(fps)))), codec=v["codec"],
        pix_fmt=v["pix_fmt"], is_vfr=is_vfr, has_audio=a is not None, audio_codec=a, color_matrix=matrix, hdr=hdr, rotation=rotation,
    )


_STREAM = re.compile(r"^\s*Stream #\d+:\d+.*?: (Video|Audio): (.*)$")
_DURATION = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
_ROTATION = re.compile(r"rotation of (-?[\d.]+) degrees")
_SIZE = re.compile(r"^(\d+)x(\d+)")
_RATE = re.compile(r"^([\d.]+)(k?) (fps|tbr)$")


def _split_top(s: str) -> list[str]:
    """괄호 밖의 쉼표로만 나눈다. "yuv420p(tv, bt709), 1920x1080" → ["yuv420p(tv, bt709)", "1920x1080"]"""
    out, depth, cur = [], 0, ""
    for ch in s:
        depth += ch == "(" or -(ch == ")")
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return out + [cur.strip()]


def _rate(num: str, k: str) -> Fraction:
    """ffmpeg가 반올림해 찍은 값(29.97, 23.98)은 snap_fps가 표준값으로 되돌린다."""
    return Fraction(num).limit_denominator(1001) * (1000 if k else 1)


def _parse_video(desc: str) -> dict:
    parts = _split_top(desc)
    v = {"codec": parts[0].split()[0], "pix_fmt": "?", "space": "", "trc": "", "width": 0, "height": 0,
         "fps": None, "tbr": None}
    for p in parts[1:]:
        if (m := _SIZE.match(p)) and not v["width"]:
            v["width"], v["height"] = int(m[1]), int(m[2])
        elif m := _RATE.match(p):
            v["fps" if m[3] == "fps" else "tbr"] = _rate(m[1], m[2])
        elif v["pix_fmt"] == "?" and re.match(r"^[a-z0-9_]+(\(|$)", p):
            v["pix_fmt"] = p.split("(")[0]
            # 괄호 안: "tv, bt2020nc/bt2020/arib-std-b67" 또는 셋이 같으면 "tv, bt709"
            for item in (p[p.index("(") + 1:-1].split(", ") if "(" in p else []):
                if "/" in item:
                    v["space"], _, v["trc"] = item.split("/")
                elif item.startswith(("bt", "smpte", "arib")):
                    v["space"] = v["trc"] = item
    return v


def _parse_info(stderr: str) -> tuple[dict | None, str | None, float, int]:
    """(첫 영상 스트림, 첫 오디오 코덱, 길이 초, 회전 각도)."""
    v = a = None
    duration, rotation, in_video = 0.0, 0, False
    for line in stderr.splitlines():
        if m := _DURATION.search(line):
            duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
        elif m := _STREAM.match(line):
            in_video = False
            if m[1] == "Video" and v is None and "attached pic" not in line:
                v, in_video = _parse_video(m[2]), True
            elif m[1] == "Audio" and a is None:
                a = m[2].split()[0].rstrip(",")
        elif in_video and (m := _ROTATION.search(line)):
            rotation = int(round(float(m[1])))
    return v, a, duration, rotation


def validate_decodable(path: str | Path) -> None:
    """첫 프레임을 실제로 디코드해 본다. 헤더만 멀쩡한 손상 파일을 걸러낸다."""
    r = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(path), "-map", "0:v:0", "-frames:v", "1",
                        "-f", "null", "-"], capture_output=True, text=True)
    if r.returncode != 0:
        raise VideoError(f"영상을 디코드할 수 없습니다. 코덱을 지원하지 않거나 파일이 손상됐습니다. ({_last(r.stderr, path)})")


def _last(stderr: str, path: str | Path = "") -> str:
    lines = [l for l in (stderr or "").strip().splitlines() if l.strip()]
    msg = lines[-1] if lines else "알 수 없는 오류"
    if path:
        msg = msg.replace(f"{path}: ", "").replace(str(path), Path(path).name)
    return msg[:200]


_encoder_cache: dict[str, bool] = {}


def encoder_works(name: str) -> bool:
    """하드웨어 인코더가 실제로 동작하는지 작은 인코드로 확인(결과 캐시)."""
    if name not in _encoder_cache:
        r = subprocess.run([ffmpeg_bin(), "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=256x256:d=0.2",
                            "-c:v", name, "-b:v", "1M", "-f", "null", "-"], capture_output=True, text=True)
        _encoder_cache[name] = r.returncode == 0
    return _encoder_cache[name]


def health() -> dict:
    try:
        ffmpeg_bin()
    except VideoError as e:
        return {"ffmpeg": False, "error": str(e), "encoders": {}}
    encs = {n: encoder_works(n) for n in ("h264_videotoolbox", "hevc_videotoolbox", "libx264", "libx265")}
    return {"ffmpeg": True, "encoders": encs}
