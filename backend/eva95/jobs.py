"""내보내기 배치 큐와 미리보기 클립 작업.

내보내기는 한 번에 하나씩 처리한다(각 렌더가 이미 CPU 코어를 모두 쓰기 때문).
미리보기 클립은 별도 워커에서 돌려 긴 내보내기 뒤에 밀리지 않게 한다.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from pathlib import Path

from .params import ExportSettings, normalize, params_hash
from .presets import DATA_DIR
from .probe import VideoError
from .render import Cancelled, render, unique_output_path
from .store import PREVIEW_SHORT, ClipStore

DEFAULT_OUTPUT = Path.home() / "Movies" / "EVA95"


class JobManager:
    def __init__(self, store: ClipStore):
        self.store = store
        self.jobs: dict[str, dict] = {}
        self.cancels: dict[str, threading.Event] = {}
        self.q: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True, name="export-worker").start()
        self.preview_q: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._preview_worker, daemon=True, name="preview-worker").start()

    # ------------------------------------------------------------ 내보내기

    def submit(self, clip_ids: list[str], params: dict, export: dict) -> list[dict]:
        settings = ExportSettings.from_dict(export)  # 잘못된 설정은 여기서 ValueError
        out = []
        for cid in clip_ids:
            clip = self.store.get(cid)
            jid = uuid.uuid4().hex[:10]
            job = {"id": jid, "kind": "export", "clip_id": cid, "name": clip["name"], "status": "queued",
                   "progress": 0.0, "frames_done": 0, "frames_total": 0, "speed_fps": 0.0, "eta_s": None,
                   "output": None, "error": None, "created": time.time(), "started": None, "finished": None,
                   "params": normalize(params), "export": settings.__dict__}
            with self.lock:
                self.jobs[jid] = job
            self.q.put(jid)
            out.append(job)
        return out

    def cancel(self, jid: str) -> dict:
        job = self._job(jid)
        if job["status"] == "queued":
            job["status"] = "cancelled"
        elif job["status"] == "running":
            self.cancels.setdefault(jid, threading.Event()).set()
        return job

    def retry(self, jid: str) -> dict:
        job = self._job(jid)
        if job["status"] not in ("failed", "cancelled"):
            raise ValueError("실패하거나 취소된 작업만 다시 시도할 수 있습니다")
        job.update(status="queued", progress=0.0, error=None, output=None, frames_done=0, eta_s=None,
                   started=None, finished=None)
        self.cancels.pop(jid, None)
        self.q.put(jid)
        return job

    def remove(self, jid: str) -> None:
        job = self._job(jid)
        if job["status"] == "running":
            raise ValueError("진행 중인 작업은 먼저 취소하세요")
        job["status"] = "cancelled" if job["status"] == "queued" else job["status"]
        with self.lock:
            self.jobs.pop(jid, None)

    def list(self, kind: str = "export") -> list[dict]:
        with self.lock:
            return sorted((j for j in self.jobs.values() if j["kind"] == kind), key=lambda j: j["created"])

    def _job(self, jid: str) -> dict:
        job = self.jobs.get(jid)
        if not job:
            raise KeyError(f"작업을 찾을 수 없습니다: {jid}")
        return job

    def _worker(self) -> None:
        while True:
            jid = self.q.get()
            job = self.jobs.get(jid)
            if not job or job["status"] != "queued":
                continue
            cancel = self.cancels.setdefault(jid, threading.Event())
            cancel.clear()
            job.update(status="running", started=time.time())
            try:
                self._run_export(job, cancel)
                job.update(status="done", progress=1.0, eta_s=0)
            except Cancelled:
                job.update(status="cancelled", error=None)
            except (VideoError, ValueError, KeyError, OSError) as e:
                job.update(status="failed", error=str(e))
            except Exception as e:  # 예상 못한 오류도 큐를 멈추지 않게
                job.update(status="failed", error=f"내부 오류: {type(e).__name__}: {e}")
            finally:
                job["finished"] = time.time()

    def _run_export(self, job: dict, cancel: threading.Event) -> None:
        settings = ExportSettings.from_dict(job["export"])
        info = self.store.info(job["clip_id"])
        stats = self.store.stats(job["clip_id"]) if job["params"]["shot_matching"] else None
        out = unique_output_path(settings.output_dir or DEFAULT_OUTPUT, job["name"])

        def progress(done: int, total: int, fps: float) -> None:
            job.update(frames_done=done, frames_total=total, progress=min(done / total, 1.0) if total else 0,
                       speed_fps=round(fps, 1), eta_s=round((total - done) / fps, 1) if fps > 0 else None)

        job["output"] = str(render(info, job["params"], settings, out, shot_stats=stats, progress=progress,
                                   cancel=cancel))

    # ------------------------------------------------------------ 미리보기 클립

    def preview_clip(self, cid: str, params: dict, start: float, seconds: float = 3.0) -> dict:
        p = normalize(params)
        info = self.store.info(cid)
        start = max(0.0, min(start, max(0.0, info.duration - 0.5)))
        dur = min(seconds, info.duration - start)
        key = f"{cid}_{params_hash(p)}_{start:.2f}_{dur:.2f}"
        with self.lock:
            if key in self.jobs and self.jobs[key]["status"] in ("queued", "running", "done"):
                return self.jobs[key]
            job = {"id": key, "kind": "preview", "clip_id": cid, "status": "queued", "progress": 0.0,
                   "params": p, "start": start, "duration": dur, "processed": None, "original": None,
                   "error": None, "created": time.time()}
            self.jobs[key] = job
        self.preview_q.put(key)
        return job

    def _preview_worker(self) -> None:
        while True:
            key = self.preview_q.get()
            job = self.jobs.get(key)
            if not job or job["status"] != "queued":
                continue
            job["status"] = "running"
            try:
                cache = DATA_DIR / "cache" / job["clip_id"]
                cache.mkdir(parents=True, exist_ok=True)
                info = self.store.info(job["clip_id"])
                stats = self.store.stats(job["clip_id"]) if job["params"]["shot_matching"] else None
                s = ExportSettings()
                orig = cache / f"orig_{key}.mp4"
                proc = cache / f"proc_{key}.mp4"
                if not (orig.exists() and proc.exists()):
                    # 한 번 디코드해서 보정 전·후를 함께 만든다
                    render(info, job["params"], s, proc, shot_stats=stats, start=job["start"],
                           duration=job["duration"], preview_short=PREVIEW_SHORT, original_out=orig,
                           progress=lambda d, t, f: job.update(progress=d / max(t, 1)))
                job.update(status="done", progress=1.0, original=orig.name, processed=proc.name)
            except Exception as e:
                job.update(status="failed", error=str(e))
