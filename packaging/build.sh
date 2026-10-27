#!/usr/bin/env bash
# TONE ROOM.app과 설치용 dmg 만들기(Apple Silicon 전용). 결과: dist/TONE-ROOM-<버전>-arm64.dmg
# 필요: Python 3.10+ 가상환경(backend/requirements.txt + pyinstaller), Node.js, Xcode 명령행 도구
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-backend/.venv/bin/python}"
[ "$(uname -m)" = arm64 ] || { echo "Apple Silicon 맥에서만 빌드합니다." >&2; exit 1; }
export TONEROOM_VERSION="${TONEROOM_VERSION:-$(cat VERSION)}"

[ -f packaging/TONEROOM.icns ] || "$PY" packaging/make_icon.py

# 프론트엔드를 정적 HTML로(API는 같은 서버라 상대 경로)
(cd frontend && { [ -d node_modules ] || npm ci; } && TONEROOM_EXPORT=1 NEXT_PUBLIC_API="" npx next build >/dev/null)

# 애플 초해상도 도구. macOS 26 SDK(Xcode 26)가 있어야 빌드되고, 없으면 AI 업스케일만 빠진다
mkdir -p build
if swiftc -O -target arm64-apple-macos14.0 tools/vtsr/main.swift -o build/vtsr 2>/dev/null; then
  export TONEROOM_VTSR="$ROOT/build/vtsr"
else
  echo "[TONE ROOM] vtsr 빌드 실패: AI 업스케일 없이 만듭니다" >&2
  unset TONEROOM_VTSR
fi

"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi packaging/toneroom.spec

# 끌어다 놓기 설치용 dmg (앱 + 응용 프로그램 폴더 바로가기)
STAGE="$(mktemp -d)"
cp -R "dist/TONE ROOM.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="dist/TONE-ROOM-$TONEROOM_VERSION-arm64.dmg"
rm -f "$DMG"
hdiutil create -volname "TONE ROOM" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "$DMG"
