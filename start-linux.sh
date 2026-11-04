#!/usr/bin/env bash
# VideoHub 视频学习工作台 —— Linux 启动脚本（仅学习模块，最小依赖）
# 用法：./start-linux.sh          后台启动服务并打开浏览器
#       ./start-linux.sh --fg     前台运行（看日志）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${VH_PORT:-8767}"
PY="$ROOT/.venv/bin/python"
URL="http://127.0.0.1:$PORT/learn"
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/videohub/learning.log"
PIDFILE="${XDG_STATE_HOME:-$HOME/.local/state}/videohub/learning.pid"

mkdir -p "$(dirname "$LOG")"

if [ ! -x "$PY" ]; then
  echo "错误：未找到虚拟环境 $PY" >&2
  echo "修复：uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python flask requests python-dotenv" >&2
  exit 1
fi

if [ ! -f "$ROOT/frontend/dist/learning.html" ]; then
  echo "错误：前端未构建（frontend/dist 缺失）" >&2
  echo "修复：cd frontend && npm install && npm run build" >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "警告：未找到 ffmpeg，视频预览/转码会受限（sudo apt install ffmpeg）" >&2
fi

healthy() {
  curl -sf --max-time 2 "http://127.0.0.1:$PORT/api/learning/health" 2>/dev/null | grep -q videohub-learning
}

open_ui() {
  xdg-open "$URL" >/dev/null 2>&1 || echo "请手动打开：$URL"
}

# 已有实例：直接开页面
if healthy; then
  echo "VideoHub 学习模块已在运行：$URL"
  [ "${1:-}" = "--fg" ] && { echo "已在运行，跳过前台启动"; exit 0; }
  open_ui
  exit 0
fi

if [ "${1:-}" = "--fg" ]; then
  echo "前台启动：$URL"
  exec "$PY" -m src.learning_server --port "$PORT"
fi

# 后台启动
setsid nohup "$PY" -m src.learning_server --port "$PORT" >"$LOG" 2>&1 &
echo $! > "$PIDFILE"

for _ in $(seq 1 40); do
  if healthy; then
    echo "已启动：$URL（日志：$LOG）"
    open_ui
    exit 0
  fi
  sleep 0.25
done

echo "启动失败，请查看日志：$LOG" >&2
tail -20 "$LOG" >&2
exit 1
