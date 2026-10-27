"""맥 앱 진입점. 로컬 서버를 빈 포트에 띄우고 그 화면을 앱 창(WKWebView)에 연다.
개발용 ./start.sh(:8095 + :3095)와 따로 돌아서, 둘을 동시에 켜도 부딪히지 않는다."""
import os
import platform
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "TONE ROOM"


def _resources() -> tuple[Path, Path]:
    """(프론트엔드 정적 빌드, vtsr) 위치. 앱 안이면 번들 폴더, 개발 중이면 저장소."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # noqa: SLF001 — PyInstaller가 넣어 주는 값
        return base / "web", base / "vtsr"
    root = Path(__file__).resolve().parents[2]
    return root / "frontend" / ".next-export", root / "tools" / "vtsr" / "vtsr"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    if platform.machine() != "arm64":
        raise SystemExit(f"{APP_NAME}은 Apple Silicon(M1 이후) 맥에서만 동작합니다.")
    web, vtsr = _resources()
    # eva95 모듈이 임포트될 때 읽는 값이라 그 전에 정한다
    os.environ.setdefault("EVA95_DATA", str(Path.home() / "Library" / "Application Support" / APP_NAME))
    os.environ["EVA95_WEB"] = str(web)
    os.environ.setdefault("EVA95_VTSR", str(vtsr))

    import uvicorn
    import webview

    from .api import app as api_app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(api_app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(150):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5)
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("내부 서버가 시작되지 않았습니다.")

    webview.create_window(APP_NAME, f"http://127.0.0.1:{port}/", width=1600, height=1000,
                          min_size=(1200, 760), background_color="#000000")
    webview.start()


if __name__ == "__main__":
    main()
