#!/usr/bin/env bash
# 打包成绿色解压版：解压后运行 ./start.sh 即可，不需要安装。
#
# 依赖用户系统里的 python3（3.10+）和 python3-tk 或 zenity（原生目录选择框）。
# 依赖包全部放在 runtime/ 里，不写系统 site-packages，不碰 ~/.local。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

NAME="VideoHub"
VERSION="$(grep -m1 '^version' pyproject.toml | sed 's/.*= *"\(.*\)"/\1/' || echo "0.1.0")"
OUT="${1:-$HOME/Desktop}"
STAGE="$ROOT/build/$NAME-$VERSION"

[ -f frontend/dist/learning.html ] || { echo "请先构建前端：cd frontend && npm run build" >&2; exit 1; }
[ -x .venv/bin/python ] || { echo "缺少 .venv，请先创建虚拟环境并安装依赖" >&2; exit 1; }

rm -rf "$STAGE"
mkdir -p "$STAGE/runtime"

echo "→ 复制运行时代码"
# 只带运行学习工作台所需的文件，测试、会议、录播等模块一律不进包。
# src/ 必须留在根目录：启动脚本以本目录为工作目录运行 python -m src.learning_server。
cp -r src "$STAGE/"
mkdir -p "$STAGE/frontend"
cp -r frontend/dist "$STAGE/frontend/dist"
cp start.sh start.bat "$STAGE/"
cp README-绿色版.md "$STAGE/说明.md" 2>/dev/null || true
cp requirements-learning.txt "$STAGE/requirements.txt" 2>/dev/null || true
chmod +x "$STAGE/start.sh"

echo "→ 复制依赖包"
# 依赖装进包里而不是系统，解压即用；纯 Python 包，跨发行版可用。
cp -r .venv/lib/python3*/site-packages/* "$STAGE/runtime/"
find "$STAGE/runtime" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/runtime" -name '*.pyc' -delete 2>/dev/null || true
rm -rf "$STAGE"/runtime/*.dist-info/RECORD 2>/dev/null || true

echo "→ 写版本信息"
cat > "$STAGE/version.txt" <<EOF
$NAME $VERSION
打包时间：$(date '+%Y-%m-%d %H:%M:%S')
提交：$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
EOF

echo "→ 压缩"
TARBALL="$OUT/$NAME-$VERSION-linux-x86_64.tar.gz"
mkdir -p "$OUT"
tar -czf "$TARBALL" -C "$ROOT/build" "$NAME-$VERSION"

# 通用包：不带预编译的 .so，解压后第一次运行自己装依赖，因此 Windows/macOS/
# 其它架构都能用同一份压缩包。体积也小很多。
PORTABLE="$OUT/$NAME-$VERSION-portable.zip"
echo "→ 打包通用版（首次运行自动装依赖）"
rm -rf "$STAGE/runtime"
mkdir -p "$STAGE/runtime"
rm -f "$STAGE"/start.sh.bak
(cd "$ROOT/build" && zip -qr "$PORTABLE" "$NAME-$VERSION")

echo
echo "已生成两个包："
echo "  $TARBALL"
echo "    体积 $(du -h "$TARBALL" | cut -f1)  sha256 $(sha256sum "$TARBALL" | cut -d' ' -f1)"
echo "    依赖已内置，Linux x86_64 解压即用"
echo "  $PORTABLE"
echo "    体积 $(du -h "$PORTABLE" | cut -f1)  sha256 $(sha256sum "$PORTABLE" | cut -d' ' -f1)"
echo "    不带依赖，首次运行自动 pip install；Windows / 其它平台用这个"
