"""FFmpeg 스트리밍 디코드/인코드. 영상 전체를 메모리에 올리지 않는다."""
from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from .probe import VideoError, VideoInfo, encoder_works, ffmpeg_bin

# ---------------------------------------------------------------- 크기·FPS


def even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def fit_short_side(w: int, h: int, short: int) -> tuple[int, int]:
    """짧은 변을 short로 맞추고 비율 유지(세로·가로 모두)."""
    s = short / min(w, h)
    return even(w * s), even(h * s)


def output_size(info: VideoInfo, resolution: str) -> tuple[int, int]:
    if resolution == "1080p":
        return fit_short_side(info.width, info.height, 1080)
    if resolution == "4k":
        return fit_short_side(info.width, info.height, 2160)
    return even(info.width), even(info.height)


def output_fps(info: VideoInfo, fps_setting: str, cadence_12fps: bool) -> Fraction:
    table = {"23.976": Fraction(24000, 1001), "24": Fraction(24), "30": Fraction(30)}
    if fps_setting in table:
        return table[fps_setting]
    if cadence_12fps:
        # 12fps 시뮬레이션은 24fps 컨테이너가 기준. 원본이 23.976이면 그대로 둔다.
        return info.fps if info.fps == Fraction(24000, 1001) else Fraction(24)
    return info.fps


# ---------------------------------------------------------------- HDR → SDR

_BT2020_TO_709 = np.array([[1.6605, -0.5876, -0.0728],
                           [-0.1246, 1.1329, -0.0083],
                           [-0.0182, -0.1006, 1.1187]], dtype=np.float32)


_HDR_IN: dict[str, np.ndarray] = {}
_OUT_SCALE = 4095 / 3.0  # 숄더 LUT 입력 범위: 선형 0~3
_HDR_OUT: np.ndarray | None = None


def _hdr_luts(kind: str) -> tuple[np.ndarray, np.ndarray]:
    """신호(u16) → 장면 선형값 LUT, 선형값 → SDR 감마 출력 LUT(숄더 포함). 한 번만 만든다."""
    global _HDR_OUT
    if kind not in _HDR_IN:
        e = np.arange(65536, dtype=np.float64) / 65535.0
        if kind == "hlg":
            a, b, c = 0.17883277, 0.28466892, 0.55991073
            lin = np.where(e <= 0.5, (e * e) / 3.0, (np.exp((e - c) / a) + b) / 12.0) * (0.7 / 0.2649)
        else:
            m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
            pw = np.power(e, 1 / m2)
            lin = 10000.0 * np.power(np.maximum(pw - c1, 0) / (c2 - c3 * pw), 1 / m1) / 203.0 * 0.7
        _HDR_IN[kind] = lin.astype(np.float32)
    if _HDR_OUT is None:
        x = np.arange(4096, dtype=np.float64) / _OUT_SCALE
        k = 0.6
        y = np.where(x < k, x, k + (1 - k) * (1 - np.exp(-(x - k) / (1 - k))))
        _HDR_OUT = (np.power(np.clip(y, 0, 1), 1 / 2.4) * 255.0 + 0.5).astype(np.uint8)
    return _HDR_IN[kind], _HDR_OUT


def hdr_to_sdr(rgb16: np.ndarray, kind: str) -> np.ndarray:
    """BT.2020 HLG/PQ 신호(rgb48)를 BT.709 SDR uint8로. 기준 백색을 선형 0.7에 두고 하이라이트는 숄더로 압축."""
    lut_in, lut_out = _hdr_luts(kind)
    lin = cv2.transform(lut_in[rgb16], _BT2020_TO_709)
    q = np.clip(lin * _OUT_SCALE, 0, 4095).astype(np.uint16)
    return lut_out[q]


# ---------------------------------------------------------------- 디코드


def _decode_cmd(info: VideoInfo, w: int, h: int, fps: Fraction | None, start: float | None,
                duration: float | None, frames: int | None, hwaccel: bool = False) -> tuple[list[str], str]:
    pix = "rgb48le" if info.hdr else "rgb24"
    vf = []
    if fps is not None:
        vf.append(f"fps={fps.numerator}/{fps.denominator}")
    vf.append(f"scale={w}:{h}:flags=lanczos:in_color_matrix={info.color_matrix}")
    vf.append(f"format={pix}")
    cmd = [ffmpeg_bin(), "-v", "error", "-nostdin"]
    if hwaccel:  # 전체 렌더에서만: VideoToolbox 디코드(실패하면 ffmpeg가 소프트웨어로 대체)
        cmd += ["-hwaccel", "videotoolbox"]
    if start:
        cmd += ["-ss", f"{start:.4f}"]
    cmd += ["-i", info.path]
    if duration:
        cmd += ["-t", f"{duration:.4f}"]
    cmd += ["-map", "0:v:0", "-vf", ",".join(vf), "-an", "-sn"]
    if frames:
        cmd += ["-frames:v", str(frames)]
    cmd += ["-f", "rawvideo", "-pix_fmt", pix, "-"]
    return cmd, pix


class FrameReader:
    """ffmpeg stdout에서 프레임을 하나씩 읽는다(메모리는 프레임 1장 크기)."""

    def __init__(self, info: VideoInfo, w: int, h: int, fps: Fraction | None = None,
                 start: float | None = None, duration: float | None = None, frames: int | None = None,
                 hwaccel: bool = False, raw: bool = False):
        """raw=True면 HDR 프레임을 변환하지 않고 u16 그대로 넘긴다(변환은 호출 측 병렬 워커에서)."""
        self.info, self.w, self.h, self.raw = info, w, h, raw
        cmd, self.pix = _decode_cmd(info, w, h, fps, start, duration, frames, hwaccel)
        self.bpp = 6 if self.pix == "rgb48le" else 3
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)

    def __iter__(self) -> Iterator[np.ndarray]:
        n = self.w * self.h * self.bpp
        while True:
            buf = bytearray(n)
            view, got = memoryview(buf), 0
            while got < n:
                k = self.proc.stdout.readinto(view[got:])
                if not k:
                    break
                got += k
            if got < n:
                break
            if self.info.hdr and self.raw:
                yield np.frombuffer(buf, dtype="<u2").reshape(self.h, self.w, 3)
            elif self.info.hdr:
                yield hdr_to_sdr(np.frombuffer(buf, dtype="<u2").reshape(self.h, self.w, 3), self.info.hdr)
            else:
                yield np.frombuffer(buf, dtype=np.uint8).reshape(self.h, self.w, 3)

    def close(self) -> str:
        """프로세스를 정리하고 stderr를 돌려준다."""
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            err = self.proc.stderr.read().decode("utf-8", "replace")
        except (OSError, ValueError):
            err = ""
        self.proc.wait()
        return err


def grab_frame(info: VideoInfo, t: float, short: int | None = None) -> np.ndarray:
    w, h = fit_short_side(info.width, info.height, short) if short else (even(info.width), even(info.height))
    t = max(0.0, min(t, max(0.0, info.duration - 0.05)))
    r = FrameReader(info, w, h, start=t, frames=1)
    frame = next(iter(r), None)
    err = r.close()
    if frame is None and t > 0:  # 끝부분 시킹 실패 시 조금 앞에서 재시도
        r = FrameReader(info, w, h, start=max(0, t - 0.5), frames=1)
        frame = next(iter(r), None)
        err = r.close()
    if frame is None:
        raise VideoError(f"프레임을 읽을 수 없습니다 ({err.strip()[-200:] or 't=%.2f' % t})")
    return frame.copy()


# ---------------------------------------------------------------- 인코드

# 품질별 비트/픽셀/프레임 (VideoToolbox용). H.265는 0.65배.
_BPP = {"standard": 0.09, "high": 0.15, "maximum": 0.26}
_CRF = {"standard": 21, "high": 18, "maximum": 15}


def pick_encoder(codec: str) -> str:
    hw = "h264_videotoolbox" if codec == "h264" else "hevc_videotoolbox"
    if encoder_works(hw):
        return hw
    sw = "libx264" if codec == "h264" else "libx265"
    if encoder_works(sw):
        return sw
    raise VideoError(f"{codec.upper()} 인코더를 사용할 수 없습니다. FFmpeg 설치를 확인하세요.")


def video_codec_args(encoder: str, w: int, h: int, fps: Fraction, quality: str) -> list[str]:
    if encoder.endswith("videotoolbox"):
        bpp = _BPP[quality] * (0.65 if encoder.startswith("hevc") else 1.0)
        rate = int(w * h * float(fps) * bpp)
        args = ["-c:v", encoder, "-b:v", str(rate), "-maxrate", str(int(rate * 1.5)),
                "-bufsize", str(int(rate * 2)), "-allow_sw", "1"]
        args += ["-profile:v", "high"] if encoder.startswith("h264") else ["-profile:v", "main", "-tag:v", "hvc1"]
        return args
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", "medium" if quality != "maximum" else "slow",
                "-crf", str(_CRF[quality]), "-profile:v", "high"]
    if encoder == "libx265":
        return ["-c:v", "libx265", "-preset", "medium", "-crf", str(_CRF[quality] + 3), "-tag:v", "hvc1",
                "-x265-params", "log-level=error"]
    if encoder == "preview":
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-tune", "fastdecode"]
    raise ValueError(encoder)


def encode_cmd(out_path: str | Path, w: int, h: int, fps: Fraction, encoder: str, quality: str,
               audio_src: VideoInfo | None, start: float | None = None, duration: float | None = None,
               sharpen: float = 0.0) -> list[str]:
    """stdin rawvideo(rgb24) + 원본 오디오 → MP4. CFR, yuv420p, BT.709, faststart(CapCut 호환)."""
    cmd = [ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-framerate", f"{fps.numerator}/{fps.denominator}", "-i", "-"]
    if audio_src is not None and audio_src.has_audio:
        if start:
            cmd += ["-ss", f"{start:.4f}"]
        if duration:
            cmd += ["-t", f"{duration:.4f}"]
        cmd += ["-i", audio_src.path, "-map", "0:v:0", "-map", "1:a:0",
                "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-af", "aresample=async=1:first_pts=0"]
    else:
        cmd += ["-map", "0:v:0"]
    cas = f"cas=strength={sharpen:.2f}," if sharpen > 0 else ""  # 업스케일용 대비 적응 선명화
    cmd += ["-vf", cas + "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"]
    cmd += video_codec_args(encoder, w, h, fps, quality)
    cmd += ["-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv", "-fps_mode", "cfr", "-r", f"{fps.numerator}/{fps.denominator}",
            "-movflags", "+faststart", "-f", "mp4", str(out_path)]
    return cmd


