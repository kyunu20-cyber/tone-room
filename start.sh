#!/usr/bin/env bash
# EVA-95 VIDEO PROCESSOR 실행 스크립트 (macOS)
# 최초 실행 시 Python 가상환경과 npm 패키지를 설치하고, 백엔드(:8095)와 프론트엔드(:3095)를 띄운다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "[EVA-95] FFmpeg가 없습니다. 먼저 설치하세요:  brew install ffmpeg"
  exit 1
fi
if ! command -v node >/dev/null; then
  echo "[EVA-95] Node.js가 없습니다. 먼저 설치하세요:  brew install node"
  exit 1
fi

PY=""
for c in python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="$c"; break
  fi
done
[ -z "$PY" ] && { echo "[EVA-95] Python 3.10 이상이 필요합니다:  brew install python@3.11"; exit 1; }

if [ ! -x backend/.venv/bin/python ]; then
  echo "[EVA-95] Python 환경 설치 중..."
  "$PY" -m venv backend/.venv
  backend/.venv/bin/pip install -q --upgrade pip
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi
if [ ! -d frontend/node_modules ]; then
  echo "[EVA-95] 프론트엔드 패키지 설치 중..."
  (cd frontend && npm install --silent)
fi
# 애플 초해상도 도구(AI 업스케일용). macOS 26 + Xcode 명령행 도구가 있을 때만, 실패해도 앱은 실행
if [ ! -x tools/vtsr/vtsr ] || [ tools/vtsr/main.swift -nt tools/vtsr/vtsr ]; then
  if command -v swiftc >/dev/null 2>&1; then
    swiftc -O tools/vtsr/main.swift -o tools/vtsr/vtsr 2>/dev/null || echo "[TONE ROOM] AI 업스케일 도구 빌드 실패(SHARP 업스케일은 사용 가능)"
  fi
fi
# 빌드가 없거나, 프론트엔드 코드·설명서가 마지막 빌드보다 새로우면 다시 빌드
STAMP=frontend/.next/BUILD_ID
if [ ! -f "$STAMP" ] || [ "${EVA95_REBUILD:-0}" = "1" ] || \
   [ -n "$(find frontend/app frontend/components frontend/lib 사용설명서.md -newer "$STAMP" -type f 2>/dev/null | head -1)" ]; then
  echo "[EVA-95] 프론트엔드 빌드 중..."
  (cd frontend && npm run build >/dev/null)
fi

for port in 8095 3095; do
  if lsof -nP -iTCP:$port -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "[EVA-95] 포트 $port 가 이미 사용 중입니다. 기존 프로세스를 종료하세요:  lsof -nP -iTCP:$port -sTCP:LISTEN -t | xargs kill"
    exit 1
  fi
done

cleanup() { kill "${BACK_PID:-}" "${FRONT_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd backend && exec .venv/bin/uvicorn eva95.api:app --host 127.0.0.1 --port 8095 --log-level warning) &
BACK_PID=$!
(cd frontend && exec npm run start --silent) &
FRONT_PID=$!

for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:3095 >/dev/null 2>&1 && curl -sf http://127.0.0.1:8095/api/health >/dev/null 2>&1 && break
  sleep 0.5
done
echo ""
echo "  EVA-95 VIDEO PROCESSOR  →  http://localhost:3095"
echo "  출력 폴더: ~/Movies/EVA95   (종료: Ctrl+C)"
echo ""
[ "${EVA95_SERVICE:-0}" = "1" ] || open "http://localhost:3095" 2>/dev/null || true

# 둘 중 하나라도 죽으면 함께 종료(서비스 모드에서는 launchd가 다시 띄운다)
while kill -0 "$BACK_PID" 2>/dev/null && kill -0 "$FRONT_PID" 2>/dev/null; do sleep 3; done
echo "[EVA-95] 서버 하나가 종료됐습니다. 전체를 종료합니다."
exit 1
