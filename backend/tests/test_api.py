import time
from urllib.parse import quote

from fastapi.testclient import TestClient

from eva95.api import app

client = TestClient(app)


def upload(path):
    r = client.post(f"/api/clips?filename={quote(path.name)}", content=path.read_bytes())
    assert r.status_code == 200, r.text
    return r.json()


def wait_jobs(ids, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        js = {j["id"]: j for j in client.get("/api/jobs").json()}
        if all(js[i]["status"] in ("done", "failed", "cancelled") for i in ids):
            return js
        time.sleep(0.3)
    raise TimeoutError


def test_health_and_schema():
    h = client.get("/api/health").json()
    assert h["ffmpeg"] and h["encoders"]["libx264"]
    s = client.get("/api/schema").json()
    keys = {p["key"] for p in s["params"]}
    assert {"shot_matching", "grain_strength", "contrast", "cadence_12fps"} <= keys
    assert s["default_preset"] == "iphone17_natural"


def test_upload_preview_analyze(media):
    clip = upload(media["unicode"])
    assert clip["name"] == "여행 클립 ①.mp4"
    o = client.get(f"/api/clips/{clip['id']}/frame?t=1")
    assert o.headers["content-type"] == "image/jpeg"
    p1 = client.post(f"/api/clips/{clip['id']}/preview", json={"t": 1, "params": {"grain_strength": 0.4}})
    p2 = client.post(f"/api/clips/{clip['id']}/preview", json={"t": 1, "params": {"grain_strength": 0.4, "contrast": 0.8}})
    assert p1.status_code == p2.status_code == 200 and p1.content != p2.content != o.content
    a = client.post(f"/api/clips/{clip['id']}/analyze").json()
    assert "exposure_ev" in a["correction"]


def test_bad_upload_message(media):
    r = client.post("/api/clips?filename=garbage.mkv", content=media["garbage"].read_bytes())
    assert r.status_code == 422 and "영상" in r.json()["detail"]
    assert str(media["garbage"].parent) not in r.json()["detail"]


def test_presets_crud():
    names = [p["id"] for p in client.get("/api/presets").json()]
    assert names[:7] == ["iphone17_natural", "iphone17_vivid", "iphone17_soft", "eva95_original_tv", "eva95_cel_color", "eva95_cinematic", "eva95_archival"]
    r = client.post("/api/presets", json={"name": "내 프리셋", "params": {"grain_strength": 0.9, "bogus": 1}})
    pid = r.json()["id"]
    got = next(p for p in client.get("/api/presets").json() if p["id"] == pid)
    assert got["params"]["grain_strength"] == 0.9 and "bogus" not in got["params"]
    assert client.delete("/api/presets/eva95_original_tv").status_code == 400
    assert client.delete(f"/api/presets/{pid}").status_code == 200


def test_batch_export_cancel_retry(media, tmp_path):
    ids = [upload(media[k])["id"] for k in ("land", "portrait", "silent")]
    params = client.get("/api/presets").json()[0]["params"]
    jobs = client.post("/api/jobs", json={"clip_ids": ids, "params": params,
                                          "export": {"output_dir": str(tmp_path)}}).json()
    assert len(jobs) == 3
    client.post(f"/api/jobs/{jobs[2]['id']}/cancel")  # 대기 중 취소
    js = wait_jobs([j["id"] for j in jobs])
    assert js[jobs[0]["id"]]["status"] == "done" and js[jobs[1]["id"]]["status"] == "done"
    assert js[jobs[2]["id"]]["status"] == "cancelled"
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["land_EVA95.mp4", "portrait_EVA95.mp4"]
    client.post(f"/api/jobs/{jobs[2]['id']}/retry")
    js = wait_jobs([jobs[2]["id"]])
    assert js[jobs[2]["id"]]["status"] == "done"
    assert (tmp_path / "silent_EVA95.mp4").exists()


def test_failed_job_reports_error(media, tmp_path):
    clip = upload(media["land"])
    blocker = tmp_path / "file"
    blocker.write_text("x")
    job = client.post("/api/jobs", json={"clip_ids": [clip["id"]], "params": {},
                                         "export": {"output_dir": str(blocker / "sub")}}).json()[0]
    js = wait_jobs([job["id"]])
    assert js[job["id"]]["status"] == "failed" and js[job["id"]]["error"]


def test_preview_clip(media):
    clip = upload(media["land"])
    job = client.post(f"/api/clips/{clip['id']}/preview-clip", json={"start": 0.5, "seconds": 1, "params": {"grain_strength": 0.3}}).json()
    t0 = time.time()
    while job["status"] not in ("done", "failed") and time.time() - t0 < 60:
        time.sleep(0.3)
        job = client.get(f"/api/preview-jobs/{job['id']}").json()
    assert job["status"] == "done", job
    r = client.get(f"/api/cache/{clip['id']}/{job['processed']}")
    assert r.status_code == 200 and len(r.content) > 1000


def test_invalid_export_settings(media):
    clip = upload(media["land"])
    r = client.post("/api/jobs", json={"clip_ids": [clip["id"]], "params": {}, "export": {"codec": "vp9"}})
    assert r.status_code == 400
