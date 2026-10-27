# PyInstaller 설정: TONE ROOM.app 만들기.  실행: packaging/build.sh
import os
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 — PyInstaller가 넣어 주는 값
VERSION = os.environ["TONEROOM_VERSION"]
if platform.machine() != "arm64":
    raise SystemExit("TONE ROOM은 Apple Silicon 전용입니다. arm64 맥에서 빌드하세요.")

datas = [(str(ROOT / "frontend" / ".next-export"), "web"),
         (str(ROOT / "backend" / "eva95" / "presets"), "eva95/presets")]
binaries = [(os.environ["TONEROOM_VTSR"], ".")] if os.environ.get("TONEROOM_VTSR") else []
hidden = []
# 동봉 ffmpeg, OpenCV, 앱 창은 데이터·바이너리까지 통째로
for pkg in ["imageio_ffmpeg", "cv2", "webview"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
hidden += collect_submodules("uvicorn") + ["eva95.api"]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT / "backend")],
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="TONE ROOM",
    console=False, upx=False, target_arch="arm64",
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="TONE ROOM")  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name="TONE ROOM.app",
    icon=str(ROOT / "packaging" / "TONEROOM.icns"),
    bundle_identifier="io.github.toneroom",
    info_plist={
        "CFBundleDisplayName": "TONE ROOM",
        "CFBundleShortVersionString": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
        "LSArchitecturePriority": ["arm64"],  # arm64 전용 바이너리라 Intel 맥에서는 macOS가 실행을 거부
        "NSRequiresAquaSystemAppearance": False,
    },
)
