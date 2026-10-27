"""전체 렌더: ffmpeg 디코드 → 프레임 병렬 보정 → ffmpeg 인코드(원본 오디오 포함).

메모리는 처리 중인 프레임 몇 장(워커 수 × 2)으로 제한된다. 중간 영상 파일을 만들지 않고,
출력은 임시 파일에 쓴 뒤 성공했을 때만 최종 경로로 옮긴다.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import cv2

from .grade import Grader
from .params import ExportSettings, normalize
from .presets import DATA_DIR
from .probe import VideoError, VideoInfo, probe
from .shotmatch import correction_for
from .video_io import (FrameReader, hdr_to_sdr, encode_cmd, even, fit_short_side, output_fps, output_size,
                       pick_encoder)

WORKERS = max(2, min(8, (os.cpu_count() or 4) - 2))
MEM_BUDGET = float(os.environ.get("EVA95_MEM_GB", "3")) * 1024**3  # 프레임 처리용 메모리 상한(대략)
VTSR_BIN = Path(os.environ.get("EVA95_VTSR", Path(__file__).resolve().parents[2] / "tools" / "vtsr" / "vtsr"))
_superres_ok: bool | None = None


def superres_available() -> bool:
    """애플 초해상도 도구가 빌드돼 있고 이 Mac에서 동작하는지(첫 호출 때 모델도 준비). 결과는 캐시."""
    global _superres_ok
    if _superres_ok is None:
        try:
            r = subprocess.run([str(VTSR_BIN), "--check"], capture_output=True, timeout=300)
            _superres_ok = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _superres_ok = False
    return _superres_ok


def workers_for(w: int, h: int) -> int:
    """워커 하나가 float32 프레임 8장 분량을 쓴다고 보고, 메모리 예산 안에서 워커 수를 정한다."""
    per_worker = w * h * 3 * 4 * 8
    return int(max(2, min(WORKERS, MEM_BUDGET // per_worker)))
cv2.setNumThreads(2)  # 프레임 단위 병렬과 겹쳐 과포화되지 않게


class Cancelled(Exception):
    pass


def tmp_dir() -> Path:
    d = DATA_DIR / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup_tmp(max_age_s: float = 0) -> int:
    """이전 실행이 남긴 임시 파일 정리."""
    n, now = 0, time.time()
    for p in tmp_dir().glob("*"):
        if p.is_file() and now - p.stat().st_mtime >= max_age_s:
            p.unlink(missing_ok=True)
            n += 1
    return n


def cleanup_cache(max_age_days: float = 3) -> int:
    """미리보기 구간 파일(data/cache)은 며칠 지나면 지운다. 다시 필요하면 새로 만든다."""
    n, now = 0, time.time()
    for p in (DATA_DIR / "cache").glob("*/*.mp4"):
        if now - p.stat().st_mtime > max_age_days * 86400:
            p.unlink(missing_ok=True)
            n += 1
    return n


def unique_output_path(out_dir: str | Path, source_name: str) -> Path:
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(source_name).stem
    p = out_dir / f"{stem}_EVA95.mp4"
    i = 2
    while p.exists():
        p = out_dir / f"{stem}_EVA95_{i}.mp4"
        i += 1
    return p


ProgressCb = Callable[[int, int, float], None]


def render(info: VideoInfo, params: dict, settings: ExportSettings, out_path: str | Path, *,
           shot_stats: dict | None = None, progress: ProgressCb | None = None,
           cancel: threading.Event | None = None, start: float | None = None, duration: float | None = None,
           preview_short: int | None = None, original_out: str | Path | None = None) -> Path:
    """original_out을 주면 같은 디코드에서 보정 전 프레임도 함께 인코드한다(미리보기 비교용, 디코드 1회)."""
    p = normalize(params)
    cancel = cancel or threading.Event()
    if preview_short:
        w, h = fit_short_side(info.width, info.height, min(preview_short, min(info.width, info.height)))
        encoder = "preview"
    else:
        w, h = output_size(info, settings.resolution)
        encoder = pick_encoder(settings.codec)
    # 업스케일: 출력이 원본보다 클 때만. ai는 1/4 크기에서 보정한 뒤 애플 초해상도로 4배
    up = not preview_short and min(w, h) > min(info.width, info.height)
    mode = settings.upscale if up else "standard"
    if mode == "ai" and not superres_available():
        raise VideoError("AI 업스케일(애플 초해상도)을 쓸 수 없습니다. macOS 26 이상과 tools/vtsr 빌드가 필요합니다.")
    gw, gh = w, h
    if mode == "ai":
        gw, gh = even(w / 4), even(h / 4)
        w, h = gw * 4, gh * 4
    fps = output_fps(info, settings.fps, p["cadence_12fps"])
    span = duration if duration else max(0.0, info.duration - (start or 0))
    total = max(1, int(round(span * float(fps))))
    shot = correction_for(shot_stats, p) if (shot_stats and p["shot_matching"]) else None
    outs = [Path(out_path)] + ([Path(original_out)] if original_out else [])

    try:
        return _render_once(info, p, shot, w, h, fps, total, encoder, settings.quality, outs,
                            progress, cancel, start, duration, use_hw_decode=True, grade_size=(gw, gh), mode=mode)
    except VideoError:
        if cancel.is_set() or not encoder.endswith("videotoolbox"):
            raise
        # 하드웨어 인코더가 도중에 실패하면 CPU 인코더로 한 번 더
        sw = "libx264" if settings.codec == "h264" else "libx265"
        return _render_once(info, p, shot, w, h, fps, total, sw, settings.quality, outs,
                            progress, cancel, start, duration, use_hw_decode=False, grade_size=(gw, gh), mode=mode)


class _Encoder:
    """stdin으로 rgb24 프레임을 받는 ffmpeg 인코더 하나. 임시 파일에 쓰고 finish()에서 최종 경로로 옮긴다."""

    def __init__(self, cmd_args: tuple, out_path: Path):
        self.out_path = out_path
        self.tmp = tmp_dir() / f"{uuid.uuid4().hex}.mp4"
        self.proc = subprocess.Popen(encode_cmd(self.tmp, *cmd_args), stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.err: list[bytes] = []
        self.err_thread = threading.Thread(target=lambda: self.err.append(self.proc.stderr.read()), daemon=True)
        self.err_thread.start()

    def write(self, arr) -> None:
        try:
            self.proc.stdin.write(memoryview(arr).cast("B"))
        except (BrokenPipeError, OSError):
            raise VideoError("인코더가 중단됐습니다: " + _tail(self.err, self.proc, self.err_thread))

    def finish(self, need_audio: bool) -> Path:
        self.proc.stdin.close()
        rc = self.proc.wait()
        self.err_thread.join(timeout=5)
        if rc != 0:
            raise VideoError("인코딩 실패: " + _tail(self.err, self.proc, self.err_thread))
        if need_audio and not probe(self.tmp).has_audio:
            raise VideoError("출력에 오디오가 없습니다. 원본 오디오를 보존하지 못해 실패로 처리합니다.")
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.tmp, self.out_path) if _same_fs(self.tmp, self.out_path) else _move(self.tmp, self.out_path)
        return self.out_path

    def abort(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.tmp.unlink(missing_ok=True)


class _SuperRes:
    """보정된 프레임을 vtsr(애플 초해상도 4배)에 넣고, 나오는 프레임을 인코더로 넘긴다."""

    def __init__(self, gw: int, gh: int, enc: "_Encoder"):
        self.size = gw * 4 * gh * 4 * 3
        self.enc, self.err = enc, []
        self.proc = subprocess.Popen([str(VTSR_BIN), str(gw), str(gh)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.err_thread = threading.Thread(target=lambda: self.err.append(self.proc.stderr.read()), daemon=True)
        self.err_thread.start()
        self.fail: BaseException | None = None
        self.pump = threading.Thread(target=self._pump, daemon=True)
        self.pump.start()

    def _pump(self) -> None:
        try:
            while True:
                buf = self.proc.stdout.read(self.size)
                if not buf:
                    return
                while len(buf) < self.size:
                    more = self.proc.stdout.read(self.size - len(buf))
                    if not more:
                        raise VideoError("초해상도 출력이 중간에 끊겼습니다")
                    buf += more
                self.enc.write(buf)
        except BaseException as e:  # 인코더 오류 등은 finish()에서 다시 던짐
            self.fail = e

    def write(self, arr) -> None:
        if self.fail:
            raise self.fail
        try:
            self.proc.stdin.write(memoryview(arr).cast("B"))
        except (BrokenPipeError, OSError):
            raise VideoError("초해상도가 중단됐습니다: " + _tail(self.err, self.proc, self.err_thread))

    def finish(self) -> None:
        self.proc.stdin.close()
        self.pump.join()
        rc = self.proc.wait()
        if self.fail:
            raise self.fail
        if rc != 0:
            raise VideoError("초해상도 실패: " + _tail(self.err, self.proc, self.err_thread))

    def abort(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()


def _render_once(info, p, shot, w, h, fps, total, encoder, quality, outs: list[Path], progress, cancel,
                 start, duration, use_hw_decode, grade_size=None, mode="standard") -> Path:
    gw, gh = grade_size or (w, h)
    grader = Grader(p, gw, gh, float(fps), shot)
    reader = FrameReader(info, gw, gh, fps, start=start, duration=duration, hwaccel=use_hw_decode, raw=True)
    encs: list[_Encoder] = []
    sr: _SuperRes | None = None
    cadence = p["cadence_12fps"]
    pair = len(outs) > 1
    done, t0, last = 0, time.time(), None
    pending: deque = deque()
    workers = workers_for(gw, gh)

    def write(frames) -> None:
        nonlocal done
        if sr:
            sr.write(frames[0])
        else:
            for e, arr in zip(encs, frames):
                e.write(arr)
        done += 1
        if progress and (done % 5 == 0 or done == total):
            el = time.time() - t0
            progress(done, total, done / el if el > 0 else 0.0)

    def drain(keep: int) -> None:
        nonlocal last
        while len(pending) > keep:
            item = pending.popleft()
            if item is not None:  # None이면 12fps 시뮬레이션: 직전 프레임 반복
                last = item.result()
            write(last)

    try:
        sharpen = 0.45 if mode == "sharp" else 0.0
        for o in outs:
            encs.append(_Encoder((w, h, fps, encoder, quality, info, start, duration, sharpen), o))
        if mode == "ai":
            sr = _SuperRes(gw, gh, encs[0])
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, frame in enumerate(reader):
                if cancel.is_set():
                    raise Cancelled()
                if cadence and i % 2 == 1:
                    pending.append(None)
                else:
                    pending.append(pool.submit(_grade, grader, frame, i, info.hdr, pair))
                drain(workers + 2)
            drain(0)
        if cancel.is_set():
            raise Cancelled()
        if sr:
            sr.finish()
        dec_err = reader.close()
        if done == 0:
            raise VideoError("영상 프레임을 하나도 읽지 못했습니다. " + (dec_err.strip()[-200:] or ""))
        results = [e.finish(info.has_audio) for e in encs]
        if progress:
            progress(total, total, 0.0)
        return results[0]
    except BaseException:
        reader.close()
        if sr:
            sr.abort()
        for e in encs:
            e.abort()
        raise


def _grade(grader: Grader, frame, i: int, hdr: str | None, with_original: bool):
    """(보정 결과,) 또는 (보정 결과, 보정 전 SDR 프레임)."""
    src = hdr_to_sdr(frame, hdr) if hdr else frame
    out = grader.process(src, i)
    return (out, src) if with_original else (out,)


def _tail(buf: list[bytes], proc, th: threading.Thread) -> str:
    if proc.poll() is None:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    th.join(timeout=2)
    text = b"".join(buf).decode("utf-8", "replace").strip()
    return text.splitlines()[-1][:300] if text else f"종료 코드 {proc.returncode}"


def _same_fs(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_dev == b.parent.stat().st_dev
    except OSError:
        return False


def _move(src: Path, dst: Path) -> None:
    import shutil
    part = dst.with_suffix(".part.mp4")
    shutil.copyfile(src, part)
    os.replace(part, dst)
    src.unlink(missing_ok=True)
