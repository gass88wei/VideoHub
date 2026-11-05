# VideoHub 视频学习工作台 · 绿色版

解压后运行 `start.sh` 即可，不安装、不写系统目录、不需要管理员权限。

## 运行环境

需要系统里已有以下东西（绝大多数 Linux 桌面都有）：

| 需求 | 说明 | 没有时的提示 |
|---|---|---|
| Python **3.10+** | 系统自带即可 | `未找到 Python 3.10 或更新版本` |
| 一个支持 app 模式的浏览器 | Edge / Chrome / Chromium / Brave | 会退回普通标签页 |
| `zenity` 或 `python3-tk` | 只在用「选择目录」按钮时需要 | 可以手动粘贴路径代替 |

检查 Python 版本：

```bash
python3 -V
```

没有 Python 就装一个：

```bash
sudo apt install python3 python3-tk zenity
```

依赖包（Flask、requests 等）**已经打包在 `runtime/` 里**，不用 `pip install`，也不会污染系统。

## 使用

```bash
./start.sh            # 启动服务并打开窗口
./start.sh --url      # 只打印地址，自己去浏览器打开
./start.sh --status   # 看服务是否在跑
./start.sh --stop     # 停止服务
```

换端口（默认 8767 被占用时）：

```bash
VH_PORT=8768 ./start.sh
```

第一次在文件管理器里双击 `start.sh` 如果没反应，是因为缺少执行权限：

```bash
chmod +x start.sh
```

## 数据放在哪

全部在程序目录下的 `data/` 里：

```
data/
├── learning/         学习库（视频索引、笔记、章节、脑图、进度）
├── window-profile/   窗口的浏览器配置
└── learning.log      运行日志
```

**整个文件夹可以随便移动、复制、备份、删除**，不会影响系统里其他东西。
想换台机器，把整个目录拷过去就行。

> 备份或搬走之前先执行 `./start.sh --stop`。数据库用 WAL 模式，
> 服务运行中直接复制可能少掉最后一次写入。

## 换台机器用

把整个文件夹拷过去就能用，前提是对方装好了 Python 3.10+：

```bash
# 打包端
./start.sh --stop
tar -czf videohub.tar.gz VideoHub-0.1.0/

# 新机器
tar -xzf videohub.tar.gz
cd VideoHub-0.1.0 && ./start.sh
```

依赖包在 `runtime/` 里跟着走，新机器不需要 `pip install`。
`runtime/` 里有几个 `.so` 是编译好的扩展（`charset_normalizer`、`markupsafe`），
都是 x86_64 Linux + 任意 CPython 3.x 可用；其它架构（ARM）需要重新打包。

## 导入视频

点右上角「导入」，选「视频工程（目录）」，挑一个放视频的文件夹：

- 目录里有几个视频就列几个，勾选后一次全部导入
- 每个视频自动配同名（或名字高度相似）的字幕
- 没字幕的视频也能导入，之后可以手动补
- 字幕放在 `subtitles/` 子文件夹里也能识别

目录里会生成一份 `videohub_learning.json` 记录该目录的视频和字幕对应关系，
删除它不影响已经导入学习库的内容。

## AI 功能（可选）

不配也能用——播放、字幕、笔记、章节跳转都是本地的。

配了之后才能用：AI 问答、生成章节大纲、生成脑图、翻译字幕。

在右侧面板点齿轮图标，填三项：

| 项目 | 例子 |
|---|---|
| API 地址 | `https://api.deepseek.com` |
| 模型名称 | `deepseek-chat` |
| API 密钥 | 你的 key |

支持任意 OpenAI 兼容接口（DeepSeek、Kimi、硅基流动、本地 Ollama 等）。

- 保存后立即生效，不用重启
- 密钥只存在本机的 `data/learning/` 数据库里，页面只会显示末四位
- 远程地址必须用 HTTPS，只有 `localhost` / `127.0.0.1` 允许 HTTP

**「联网补充」只支持 DeepSeek 和 Kimi 官方接口**，第三方兼容地址用不了这个功能。

## 快捷键

| 按键 | 作用 |
|---|---|
| `空格` | 播放 / 暂停 |
| `←` `→` | 后退 / 前进 5 秒 |
| `F` | 全屏 |
| `C` | 切换画面字幕 |
| `X` | 隐藏 / 显示字幕 |
| `S` | 播放速度 |
| `M` | 静音 |

点字幕行任意位置：跳转到该句并继续播放。右侧 ↻ 图标：循环这一句。

## 不包含什么

这个绿色版只打包了「视频学习」模块。以下上游功能**没有**包含，因此不工作：

- 视频下载（yt-dlp）
- 语音识别 / 字幕生成（Whisper）
- 语音合成（TTS）
- 会议录音、直播录制
- 浏览器扩展

字幕请用你惯用的专业工具生成，再和视频放进同一个目录导入。

## 出处

基于 [cacity/VideoHub](https://github.com/cacity/VideoHub)（MIT）修改，
去掉了 ASR 依赖，只保留本地视频 + 外部字幕的学习流程。

本分支：<https://github.com/gass88wei/VideoHub>
