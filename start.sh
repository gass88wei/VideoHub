#!/usr/bin/env bash
# VideoHub 绿色版启动器：不安装、不写系统目录，双击或命令行运行都行。
#
# 数据（学习库、笔记、进度）存在程序目录旁的 data/ 里，整个文件夹可以
# 随便移动、复制、删除，不会弄脏系统。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${VH_PORT:-8767}"
RUN="$ROOT/data"
LOG="$RUN/learning.log"
PIDFILE="$RUN/learning.pid"
mkdir -p "$RUN"

# 依赖包放在 runtime/，通过 PYTHONPATH 注入，不污染用户的 PYTHONPATH 和 site-packages。
export PYTHONPATH="$ROOT/runtime${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

find_python() {
  for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        command -v "$candidate"; return 0
      fi
    fi
  done
  return 1
}

# runtime/ 里是预装好的依赖。空的话（比如只拿了源码）就地装一份到 runtime，
# 仍然不碰系统 site-packages。
pip_install() {
  local python="$1"; shift
  # 系统 Python 常常没有 pip（Debian/Deepin 默认不带）。依次尝试：pip → ensurepip → uv。
  if "$python" -m pip --version >/dev/null 2>&1; then
    "$python" -m pip install --quiet --disable-pip-version-check --target "$ROOT/runtime" "$@"
    return
  fi
  if "$python" -m ensurepip --default-pip >/dev/null 2>&1 && "$python" -m pip --version >/dev/null 2>&1; then
    "$python" -m pip install --quiet --disable-pip-version-check --target "$ROOT/runtime" "$@"
    return
  fi
  if command -v uv >/dev/null 2>&1; then
    uv pip install --quiet --target "$ROOT/runtime" "$@"
    return
  fi
  echo "系统 Python 没有 pip。" >&2
  echo "装一个再运行：sudo apt install python3-pip" >&2
  echo "或者装上 uv：curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  return 1
}

ensure_deps() {
  local python="$1"
  if [ -f "$ROOT/runtime/flask/__init__.py" ]; then
    return 0
  fi
  echo "→ 首次运行，正在安装依赖到 runtime/（只装一次，需要联网）"
  if [ -f "$ROOT/requirements.txt" ]; then
    pip_install "$python" -r "$ROOT/requirements.txt"
  else
    pip_install "$python" flask requests python-dotenv
  fi
}

healthy() {
  curl -sf --max-time 2 "http://127.0.0.1:$PORT/api/learning/health" 2>/dev/null | grep -q videohub-learning
}

ensure_service() {
  healthy && return 0
  # 端口被别的程序占着时不要盲目启动，先给出明确原因。
  if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$PORT "; then
    echo "端口 $PORT 已被占用。可用 VH_PORT=8768 ./start.sh 换一个端口。" >&2
    return 1
  fi
  local python
  python="$(find_python)" || {
    echo "未找到 Python 3.10 或更新版本。" >&2
    echo "请先安装：sudo apt install python3" >&2
    return 1
  }
  ensure_deps "$python" || return 1
  echo "→ 启动学习服务（$python）"
  setsid env PYTHONPATH="$PYTHONPATH" PYTHONUNBUFFERED=1 \
    "$python" -m src.learning_server --data "$RUN/learning" --port "$PORT" \
    >>"$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  for _ in $(seq 1 80); do
    healthy && return 0
    sleep 0.25
  done
  echo "服务未能启动。日志：$LOG" >&2
  tail -20 "$LOG" >&2 || true
  return 1
}

open_window() {
  local url="http://127.0.0.1:$PORT/learn"
  local profile="$RUN/window-profile"
  # Deepin 上 Edge 是 linglong 包，必须在沙箱里跑；app 模式去掉地址栏和标签页。
  if command -v ll-cli >/dev/null 2>&1 && ll-cli list 2>/dev/null | grep -q "com.browser.softedge.stable"; then
    setsid ll-cli run com.browser.softedge.stable -- \
      /opt/apps/com.browser.softedge.stable/files/bin/microsoft/msedge/microsoft-edge \
      --app="$url" --window-size=1560,980 --class=videohub-learning \
      --user-data-dir="$profile" >/dev/null 2>&1 &
    return 0
  fi
  for bin in google-chrome-stable google-chrome chromium chromium-browser brave-browser microsoft-edge; do
    if command -v "$bin" >/dev/null 2>&1; then
      setsid "$bin" --app="$url" --window-size=1560,980 --class=videohub-learning \
        --user-data-dir="$profile" >/dev/null 2>&1 &
      return 0
    fi
  done
  echo "未找到支持 app 模式的浏览器，改用系统默认浏览器（会是普通标签页）。"
  xdg-open "$url" >/dev/null 2>&1 || { echo "请手动打开：$url"; return 1; }
}

stop_service() {
  if [ -f "$PIDFILE" ]; then
    local pid
    pid="$(cat "$PIDFILE")"
    if kill "$pid" 2>/dev/null; then
      # 等它真正退出，WAL 才会合并回主库；否则直接拷贝目录会丢最后一次写入。
      for _ in $(seq 1 40); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.25
      done
      echo "已停止服务（$pid）"
    else
      echo "服务本来就没在跑"
    fi
    rm -f "$PIDFILE"
  else
    echo "没有找到本绿色版的运行记录。"
  fi
}

# 端口是公共资源：装了系统服务的机器上，健康检查会被别的实例应答。
# 判断"是不是本绿色版在跑"必须看自己的 PID 文件。
owning_pid() {
  [ -f "$PIDFILE" ] || return 1
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null)" || return 1
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 1
  echo "$pid"
}

case "${1:-}" in
  --url)   ensure_service; echo "http://127.0.0.1:$PORT/learn" ;;
  --stop)  stop_service ;;
  --status)
    if pid="$(owning_pid)"; then
      echo "本绿色版运行中（PID $pid）：http://127.0.0.1:$PORT/learn"
    elif healthy; then
      echo "本绿色版没在跑，但 $PORT 端口上有另一个 VideoHub 在应答："
      echo "  http://127.0.0.1:$PORT/learn"
      echo "（可能是系统安装的版本，或另一个绿色版副本）"
    else
      echo "服务未运行"
    fi ;;
  -*) echo "未知参数：$1（可用：--url --stop --status）" >&2; exit 2 ;;
  *) ensure_service; open_window ;;
esac
