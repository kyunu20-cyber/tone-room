#!/usr/bin/env bash
# EVA-95를 macOS 로그인 항목(LaunchAgent)으로 등록한다.
# 로그인하면 자동으로 켜지고, 꺼지면 다시 켜진다. 접속: http://localhost:3095 (이 Mac에서만)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.eva95.processor"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/Library/Logs/EVA95"
mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

# 이미 직접 실행 중인 서버가 있으면 먼저 끈다(포트 충돌 방지)
for port in 8095 3095; do
  lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null | xargs kill 2>/dev/null || true
done

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$ROOT/start.sh</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>EVA95_SERVICE</key><string>1</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>LANG</key><string>ko_KR.UTF-8</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOGDIR/eva95.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/eva95.log</string>
</dict>
</plist>
PL

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "[EVA-95] 자동 실행을 등록했습니다. 잠시 후 http://localhost:3095 에 접속하세요."
echo "         로그: $LOGDIR/eva95.log   해제: ./scripts/uninstall-service.sh"
