#!/usr/bin/env bash
# VideoHub 视频学习工作台 —— Linux 启动器（只开窗口，不托管服务）
#
# 服务由独立的 systemd 用户服务管理：
#   systemctl --user start|stop|status videohub-learning.service
# 这样它不属于任何桌面应用的 scope，桌面或助手重启都不会影响它。
#
# 用法：./start-linux.sh      确保服务在跑，然后打开独立应用窗口
#       ./start-linux.sh --url 只打印地址
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${VH_PORT:-8767}"
URL="http://127.0.0.1:$PORT/learn"
UNIT="videohub-learning.service"
PROFILE="${XDG_DATA_HOME:-$HOME/.local/share}/videohub/window-profile"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/videohub"

healthy() {
  curl -sf --max-time 2 "http://127.0.0.1:$PORT/api/learning/health" 2>/dev/null | grep -q videohub-learning
}

ensure_service() {
  healthy && return 0
  if systemctl --user list-unit-files 2>/dev/null | grep -q "^${UNIT}"; then
    systemctl --user start "$UNIT" 2>/dev/null || true
    for _ in $(seq 1 60); do healthy && return 0; sleep 0.25; done
  fi
  echo "服务未能启动。" >&2
  echo "排查：systemctl --user status $UNIT" >&2
  echo "日志：$STATE/learning.log" >&2
  return 1
}

open_window() {
  # Deepin 上 Edge 是 linglong 包，必须在沙箱里跑；app 模式去掉地址栏和标签页。
  if command -v ll-cli >/dev/null 2>&1 && ll-cli list 2>/dev/null | grep -q "com.browser.softedge.stable"; then
    setsid ll-cli run com.browser.softedge.stable -- \
      /opt/apps/com.browser.softedge.stable/files/bin/microsoft/msedge/microsoft-edge \
      --app="$URL" --window-size=1560,980 --class=videohub-learning \
      --user-data-dir="$PROFILE" >/dev/null 2>&1 &
    return 0
  fi
  for bin in google-chrome-stable google-chrome chromium chromium-browser brave-browser microsoft-edge; do
    command -v "$bin" >/dev/null 2>&1 && {
      setsid "$bin" --app="$URL" --window-size=1560,980 --class=videohub-learning \
        --user-data-dir="$PROFILE" >/dev/null 2>&1 &
      return 0
    }
  done
  echo "未找到支持 app 模式的浏览器，改用系统默认浏览器（会是普通标签页）。"
  xdg-open "$URL" >/dev/null 2>&1 || echo "请手动打开：$URL"
}

case "${1:-}" in
  --url) ensure_service; echo "$URL" ;;
  -*) echo "未知参数：$1（可用：--url）" >&2; exit 2 ;;
  *) ensure_service; open_window ;;
esac
