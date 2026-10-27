"""업로드된 클립 저장소와 미리보기 캐시."""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

from .grade import Grader
from .params import normalize, params_hash
from .presets import DATA_DIR
from .probe import VideoError, VideoInfo, probe, validate_decodable
from .shotmatch import analyze_clip, correction_for
from .video_io import grab_frame, output_fps

PREVIEW_SHORT = 540


class LRU(OrderedDict):
    def __init__(self, cap: int):
        super().__init__()
        self.cap = cap
        self.lock = threading.Lock()

    def get_(self, k):
        with self.lock:
            if k in self:
                self.move_to_end(k)
                return self[k]
        return None

    def put(self, k, v):
        with self.lock:
            self[k] = v
            self.move_to_end(k)
            while len(self) > self.cap:
                self.popitem(last=False)


class ClipStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or DATA_DIR)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.index_file = self.root / "clips.json"
        self.lock = threading.RLock()
        self.clips: dict[str, dict] = {}
        self.infos: dict[str, VideoInfo] = {}
        self.frames = LRU(48)  # 원본 미리보기 프레임
        self.previews = LRU(160)  # 처리된 JPEG
        self.analysis_locks: dict[str, threading.Lock] = {}
        self._load()

    # ------------------------------------------------------------ 저장

    def _load(self) -> None:
        if not self.index_file.exists():
            return
        try:
            data = json.loads(self.index_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return
        for c in data:
            if Path(c["path"]).exists():
                self.clips[c["id"]] = c

    def _save(self) -> None:
        tmp = self.index_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(self.clips.values()), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.index_file)

    def register(self, path: Path, name: str, owned: bool) -> dict:
        """경로를 검증해 등록. 실패하면 VideoError(소유 파일이면 삭제)."""
        try:
            info = probe(path)
            validate_decodable(path)
        except VideoError:
            if owned:
                shutil.rmtree(path.parent, ignore_errors=True)
            raise
        cid = path.parent.name if owned else uuid.uuid4().hex[:12]
        clip = {"id": cid, "name": name, "path": str(path), "owned": owned, "info": info.to_json(), "stats": None}
        with self.lock:
            self.clips[cid] = clip
            self.infos[cid] = info
            self._save()
        return clip

    def new_upload_path(self, filename: str) -> Path:
        name = Path(filename).name or "video.mp4"
        d = self.uploads / uuid.uuid4().hex[:12]
        d.mkdir(parents=True)
        return d / name

    def get(self, cid: str) -> dict:
        c = self.clips.get(cid)
        if not c:
            raise KeyError(f"클립을 찾을 수 없습니다: {cid}")
        return c

    def info(self, cid: str) -> VideoInfo:
        if cid not in self.infos:
            self.infos[cid] = probe(self.get(cid)["path"])
        return self.infos[cid]

    def remove(self, cid: str) -> None:
        with self.lock:
            c = self.clips.pop(cid, None)
            self.infos.pop(cid, None)
            self._save()
        if c and c.get("owned"):
            shutil.rmtree(Path(c["path"]).parent, ignore_errors=True)

    def list(self) -> list[dict]:
        return list(self.clips.values())

    # ------------------------------------------------------------ 샷 매칭

    def stats(self, cid: str) -> dict:
        c = self.get(cid)
        if c.get("stats"):
            return c["stats"]
        lock = self.analysis_locks.setdefault(cid, threading.Lock())
        with lock:
            if not c.get("stats"):
                c["stats"] = analyze_clip(self.info(cid))
                with self.lock:
                    self._save()
        return c["stats"]

    # ------------------------------------------------------------ 미리보기

    def frame_index(self, cid: str, t: float, p: dict, fps_setting: str = "original") -> tuple[int, float]:
        info = self.info(cid)
        fps = output_fps(info, fps_setting, p["cadence_12fps"])
        idx = max(0, int(round(t * float(fps))))
        if p["cadence_12fps"]:
            idx -= idx % 2  # 12fps 시뮬레이션: 홀수 프레임은 직전 짝수 프레임과 같다
        return idx, idx / float(fps)

    def source_frame(self, cid: str, t: float) -> np.ndarray:
        key = (cid, round(t, 3))
        hit = self.frames.get_(key)
        if hit is None:
            hit = grab_frame(self.info(cid), t, PREVIEW_SHORT)
            self.frames.put(key, hit)
        return hit

    def preview_jpeg(self, cid: str, t: float, params: dict | None, fps_setting: str = "original") -> bytes:
        """params=None이면 원본 프레임. 처리 결과는 (클립, 프레임, 파라미터) 단위로 캐시."""
        p = normalize(params) if params is not None else normalize({})
        idx, tt = self.frame_index(cid, t, p, fps_setting)
        key = (cid, idx, fps_setting, params_hash(params) if params is not None else "orig")
        hit = self.previews.get_(key)
        if hit is not None:
            return hit
        src = self.source_frame(cid, tt)
        if params is None:
            out = src
        else:
            info = self.info(cid)
            shot = correction_for(self.stats(cid), p) if p["shot_matching"] else None
            h, w = src.shape[:2]
            fps = output_fps(info, fps_setting, p["cadence_12fps"])
            out = Grader(p, w, h, float(fps), shot).process(src, idx)
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(out, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise VideoError("미리보기 인코딩 실패")
        data = buf.tobytes()
        self.previews.put(key, data)
        return data
