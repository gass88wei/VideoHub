#!/usr/bin/env bash
# VideoHub 视频学习工作台 —— Linux 启动脚本
# 以「独立应用窗口」打开（Edge app 模式），不是浏览器标签页。
# 用法：./start-linux.sh          启动服务并打开独立窗口
#       ./start-linux.sh --fg     前台运行服务（调试用）
#       ./start-linux.sh --url    只启动服务并打印地址（不弹窗）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${VH_PORT:-8767}"
PY="$ROOT/.venv/bin/python"
URL="http://127.0.0.1:$PORT/learn"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/videohub"
LOG="$STATE/learning.log"
PIDFILE="$STATE/learning.pid"
PROFILE="${XDG_DATA_HOME:-$HOME/.local/share}/videohub/window-profile"

mkdir -p "$STATE"

die() { echo "错误：$*" >&2; exit 1; }

[ -x "$PY" ] || die "未找到虚拟环境 $PY
修复：uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python flask requests python-dotenv"
[ -f "$ROOT/frontend/dist/learning.html" ] || die "前端未构建（frontend/dist 缺失）
修复：cd frontend && npm install && npm run build"

command -v ffmpeg >/dev/null 2>&1 || echo "警告：未找到 ffmpeg，视频预览/转码会受限（sudo apt install ffmpeg）" >&2

healthy() {
  curl -sf --max-time 2 "http://127.0.0.1:$PORT/api/learning/health" 2>/dev/null | grep -q videohub-learning
}

start_server() {
  setsid nohup "$PY" -m src.learning_server --port "$PORT" >"$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  for _ in $(seq 1 60); do
    healthy && return 0
    sleep 0.25
  done
  echo "启动失败，日志：$LOG" >&2
  tail -20 "$LOG" >&2
  return 1
}

# 找一个能跑 Chromium app 模式的浏览器：优先本机 Edge（linglong 沙箱内），
# 其次 Chrome/Chromium。都找不到就退回系统默认浏览器。
open_window() {
  command -v ll-cli >/dev/null 2>&1 && ll-cli list 2>/dev/null | grep -q "com.browser.softedge.stable" && {
    # app 模式：无地址栏、无标签页，独立窗口 + 独立配置目录
    setsid ll-cli run com.browser.softedge.stable -- \
      /opt/apps/com.browser.softedge.stable/files/bin/microsoft/msedge/microsoft-edge \
      --app="$URL" --window-size=1560,980 --class=videohub-learning \
      --user-data-dir="$PROFILE" >/dev/null 2>&1 &
    return 0
  }
  for bin in google-chrome-stable google-chrome chromium chromium-browser brave-browser microsoft-edge; do
    command -v "$bin" >/dev/null 2>&1 && {
      setsid "$bin" --app="$URL" --window-size=1560,980 --class=videohub-learning \
        --user-data-dir="$PROFILE" >/dev/null 2>&1 &
      return 0
    }
  done
  echo "未找到支持 app 模式的浏览器，改用系统默认浏览器打开（会是普通标签页）。"
  xdg-open "$URL" >/dev/null 2>&1 || echo "请手动打开：$URL"
}

case "${1:-}" in
  --fg)
    healthy && { echo "已在运行：$URL"; exit 0; }
    echo "前台启动：$URL"
    exec "$PY" -m src.learning_server --port "$PORT"
    ;;
  --url)
    healthy || start_server
    echo "$URL"
    exit 0
    ;;
  -*)
    die "未知参数：$1（可用：--fg / --url）"
    ;;
esac

if healthy; then
  echo "服务已在运行：$URL"
else
  start_server
  echo "服务已启动：$URL（日志：$LOG）"
fi

open_window
