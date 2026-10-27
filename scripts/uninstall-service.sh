#!/usr/bin/env bash
# EVA-95 자동 실행(LaunchAgent) 해제
LABEL="com.eva95.processor"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "[EVA-95] 자동 실행을 해제했습니다. 필요할 때 ./start.sh 로 켜세요."
