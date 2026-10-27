import json
import subprocess
import threading

import numpy as np
import pytest

from eva95.params import ExportSettings
from eva95.presets import get_preset
from eva95.probe import VideoError, probe
from eva95.render import Cancelled, render, tmp_dir, unique_output_path
from eva95.shotmatch import analyze_clip
from eva95.video_io import FrameReader

P = get_preset("eva95_original_tv")["params"]


def streams(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def vstream(d):
    return next(s for s in d["streams"] if s["codec_type"] == "video")


def test_export_preserves_audio_and_sync(media, tmp_path):
    info = probe(media["land"])
    out = render(info, P, ExportSettings(), tmp_path / "land_EVA95.mp4", shot_stats=analyze_clip(info, 4))
    d = streams(out)
    v = vstream(d)
    a = [s for s in d["streams"] if s["codec_type"] == "audio"]
    assert a and a[0]["codec_name"] == "aac"
    assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p"
    assert v["r_frame_rate"] == v["avg_frame_rate"] == "30/1"
    assert abs(float(v["duration"]) - 2.0) < 0.1
    assert abs(float(a[0]["duration"]) - float(v["duration"])) < 0.1
    assert v.get("color_space") == "bt709"


def test_portrait_aspect_preserved_1080p(media, tmp_path):
    info = probe(media["portrait"])
    out = render(info, P, ExportSettings(resolution="1080p"), tmp_path / "p.mp4")
    v = vstream(streams(out))
    assert (v["width"], v["height"]) == (1080, 1920)


def test_video_without_audio(media, tmp_path):
    info = probe(media["silent"])
    assert not info.has_audio
    out = render(info, P, ExportSettings(), tmp_path / "s.mp4")
    d = streams(out)
    assert not [s for s in d["streams"] if s["codec_type"] == "audio"]
    assert vstream(d)["r_frame_rate"] == "25/1"


def test_vfr_becomes_cfr(media, tmp_path):
    info = probe(media["vfr"])
    assert info.is_vfr
    out = render(info, P, ExportSettings(fps="24"), tmp_path / "v.mp4")
    v = vstream(streams(out))
    assert v["r_frame_rate"] == v["avg_frame_rate"] == "24/1"
    assert abs(float(v["duration"]) - info.duration) < 0.15


def test_unicode_paths(media, tmp_path):
    info = probe(media["unicode"])
    out = unique_output_path(tmp_path / "출력 폴더", media["unicode"].name)
    assert out.name == "여행 클립 ①_EVA95.mp4"
    render(info, P, ExportSettings(), out)
    assert out.exists()
    assert unique_output_path(out.parent, media["unicode"].name).name == "여행 클립 ①_EVA95_2.mp4"


def frames_of(path, n):
    info = probe(path)
    r = FrameReader(info, info.width, info.height)
    out = [f.astype(np.int16) for _, f in zip(range(n), r)]
    r.close()
    return out


def test_12fps_simulation_in_24fps_container(media, tmp_path):
    info = probe(media["land"])
    p = {**P, "cadence_12fps": True, "grain_strength": 0.6}
    out = render(info, p, ExportSettings(quality="maximum"), tmp_path / "c.mp4")
    v = vstream(streams(out))
    assert v["r_frame_rate"] == "24/1"
    f = frames_of(out, 6)
    same = [np.abs(f[i] - f[i + 1]).mean() for i in (0, 2, 4)]   # 반복 쌍
    diff = [np.abs(f[i] - f[i + 1]).mean() for i in (1, 3)]      # 새 프레임
    assert max(same) < min(diff) * 0.5, (same, diff)


def test_h265_export(media, tmp_path):
    out = render(probe(media["land"]), P, ExportSettings(codec="h265", quality="standard"), tmp_path / "h.mp4")
    v = vstream(streams(out))
    assert v["codec_name"] == "hevc" and v["codec_tag_string"] == "hvc1"


def test_cancel_cleans_up(media, tmp_path):
    info = probe(media["land"])
    cancel = threading.Event()
    before = set(tmp_dir().iterdir())
    out = tmp_path / "x.mp4"

    def prog(done, total, fps):
        if done >= 10:
            cancel.set()

    with pytest.raises(Cancelled):
        render(info, P, ExportSettings(), out, progress=prog, cancel=cancel)
    assert not out.exists()
    assert set(tmp_dir().iterdir()) <= before


@pytest.mark.parametrize("key", ["truncated", "garbage"])
def test_corrupted_files_rejected(media, key):
    with pytest.raises(VideoError):
        info = probe(media[key])
        from eva95.probe import validate_decodable
        validate_decodable(info.path)


def test_unsupported_extension(tmp_path):
    f = tmp_path / "a.avi"
    f.write_bytes(b"x")
    with pytest.raises(VideoError, match="지원하지 않는 형식"):
        probe(f)


@pytest.mark.parametrize("mode", ["standard", "sharp", "ai"])
def test_upscale_modes(media, tmp_path, mode):
    """640x360 → 1080p. ai는 1/4 크기에서 보정 후 애플 초해상도로 4배(지원하는 Mac에서만)."""
    from eva95.render import superres_available
    if mode == "ai" and not superres_available():
        pytest.skip("애플 초해상도를 쓸 수 없는 환경")
    info = probe(media["land"])
    out = render(info, P, ExportSettings(resolution="1080p", upscale=mode), tmp_path / f"{mode}.mp4")
    v = vstream(streams(out))
    assert (v["width"], v["height"]) == (1920, 1080)
    assert abs(float(v["duration"]) - 2.0) < 0.1


def test_upscale_setting_validated():
    with pytest.raises(ValueError):
        ExportSettings.from_dict({"upscale": "magic"})
