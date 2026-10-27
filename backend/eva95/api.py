"""FastAPI 서버. 모든 처리는 로컬에서 이뤄지고 외부로 아무것도 보내지 않는다."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import presets
from .jobs import DEFAULT_OUTPUT, JobManager
from .params import normalize, schema
from .presets import DATA_DIR
from .probe import SUPPORTED_EXT, VideoError, health
from .render import cleanup_cache, cleanup_tmp
from .shotmatch import correction_for
from .store import ClipStore

app = FastAPI(title="TONE ROOM")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3095", "http://127.0.0.1:3095"],
                   allow_methods=["*"], allow_headers=["*"])
WEB_DIR = os.environ.get("EVA95_WEB")  # 맥 앱: 정적 빌드한 프론트엔드 폴더

cleanup_tmp()  # 이전 실행에서 중단된 렌더의 임시 파일 정리
cleanup_cache()  # 오래된 미리보기 구간 파일 정리
store = ClipStore()
jobs = JobManager(store)


@app.exception_handler(VideoError)
async def _video_error(_: Request, e: VideoError):
    return JSONResponse({"detail": str(e)}, status_code=422)


@app.exception_handler(KeyError)
async def _key_error(_: Request, e: KeyError):
    return JSONResponse({"detail": str(e.args[0]) if e.args else "찾을 수 없습니다"}, status_code=404)


@app.exception_handler(ValueError)
async def _value_error(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)


# ---------------------------------------------------------------- 기본


@app.get("/api/health")
def api_health():
    return {**health(), "default_output": str(DEFAULT_OUTPUT)}


@app.get("/api/schema")
def api_schema():
    return {"params": schema(), "default_preset": presets.DEFAULT_PRESET,
            "export": {"resolution": ["original", "1080p", "4k"], "fps": ["original", "23.976", "24", "30"],
                       "codec": ["h264", "h265"], "quality": ["standard", "high", "maximum"],
                       "upscale": ["standard", "sharp", "ai"]}}


# ---------------------------------------------------------------- 클립


@app.post("/api/clips")
async def upload_clip(request: Request, filename: str):
    """본문 전체가 파일(raw). 청크 단위로 디스크에 써서 큰 파일도 메모리에 올리지 않는다."""
    name = Path(unquote(filename)).name
    if Path(name).suffix.lower() not in SUPPORTED_EXT:
        raise VideoError(f"지원하지 않는 형식입니다({Path(name).suffix or '확장자 없음'}). MP4, MOV, MKV, WEBM만 가능합니다.")
    path = store.new_upload_path(name)
    try:
        with open(path, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
        raise VideoError("업로드가 중단됐습니다.")
    return await run_in_threadpool(store.register, path, name, True)


class ImportBody(BaseModel):
    path: str


@app.post("/api/clips/import")
def import_clip(body: ImportBody):
    """로컬 경로를 복사 없이 등록(대용량 파일용)."""
    p = Path(body.path).expanduser()
    return store.register(p, p.name, False)


@app.get("/api/clips")
def list_clips():
    return store.list()


@app.get("/api/clips/{cid}")
def get_clip(cid: str):
    return store.get(cid)


@app.delete("/api/clips/{cid}")
def delete_clip(cid: str):
    store.remove(cid)
    return {"ok": True}


@app.get("/api/clips/{cid}/frame")
def clip_frame(cid: str, t: float = 0.0):
    return Response(store.preview_jpeg(cid, t, None), media_type="image/jpeg",
                    headers={"Cache-Control": "max-age=3600"})


class PreviewBody(BaseModel):
    t: float = 0.0
    params: dict[str, Any] = {}
    fps: str = "original"


@app.post("/api/clips/{cid}/preview")
def clip_preview(cid: str, body: PreviewBody):
    return Response(store.preview_jpeg(cid, body.t, body.params, body.fps), media_type="image/jpeg")


@app.post("/api/clips/{cid}/analyze")
def clip_analyze(cid: str, body: PreviewBody | None = None):
    stats = store.stats(cid)
    p = normalize((body.params if body else None) or presets.get_preset(presets.DEFAULT_PRESET)["params"])
    return {"stats": stats, "correction": correction_for(stats, p)}


class PreviewClipBody(BaseModel):
    start: float = 0.0
    seconds: float = 3.0
    params: dict[str, Any] = {}


@app.post("/api/clips/{cid}/preview-clip")
def preview_clip(cid: str, body: PreviewClipBody):
    return jobs.preview_clip(cid, body.params, body.start, min(max(body.seconds, 1.0), 12.0))


@app.get("/api/preview-jobs/{key}")
def preview_job(key: str):
    return jobs._job(key)


@app.get("/api/cache/{cid}/{name}")
def cache_file(cid: str, name: str):
    p = (DATA_DIR / "cache" / cid / name).resolve()
    if not p.is_relative_to((DATA_DIR / "cache").resolve()) or not p.exists():
        raise KeyError("파일이 없습니다")
    return FileResponse(p, media_type="video/mp4")


# ---------------------------------------------------------------- 프리셋


@app.get("/api/presets")
def list_presets():
    return presets.list_presets()


class PresetBody(BaseModel):
    name: str
    params: dict[str, Any]
    description: str = ""


@app.post("/api/presets")
def save_preset(body: PresetBody):
    return presets.save_preset(body.name, body.params, body.description)


@app.delete("/api/presets/{pid}")
def delete_preset(pid: str):
    presets.delete_preset(pid)
    return {"ok": True}


# ---------------------------------------------------------------- 내보내기


class JobBody(BaseModel):
    clip_ids: list[str]
    params: dict[str, Any]
    export: dict[str, Any] = {}


@app.post("/api/jobs")
def create_jobs(body: JobBody):
    if not body.clip_ids:
        raise ValueError("내보낼 클립을 선택하세요")
    return jobs.submit(body.clip_ids, body.params, body.export)


@app.get("/api/jobs")
def list_jobs():
    return [{k: v for k, v in j.items() if k != "params"} for j in jobs.list()]


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    return jobs.cancel(jid)


@app.post("/api/jobs/{jid}/retry")
def retry_job(jid: str):
    return jobs.retry(jid)


@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    jobs.remove(jid)
    return {"ok": True}


class RevealBody(BaseModel):
    path: str


@app.post("/api/reveal")
def reveal(body: RevealBody):
    p = Path(body.path).expanduser()
    if not p.exists():
        raise KeyError("파일이나 폴더가 없습니다")
    subprocess.run(["open", "-R", str(p)] if p.is_file() else ["open", str(p)], check=False)
    return {"ok": True}


if WEB_DIR:  # API 경로를 모두 등록한 뒤에 마운트해야 /api/* 가 가려지지 않는다
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
