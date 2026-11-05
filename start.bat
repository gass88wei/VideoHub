@echo off
REM VideoHub 绿色版启动器（Windows）
REM 不安装、不写注册表；数据存在程序目录下的 data\ 里。
setlocal enabledelayedexpansion
cd /d "%~dp0"

if "%VH_PORT%"=="" set VH_PORT=8767
set "RUN=%~dp0data"
set "LOG=%RUN%\learning.log"
if not exist "%RUN%" mkdir "%RUN%"

set "PYTHONPATH=%~dp0runtime;%PYTHONPATH%"

REM 找一个能用的 Python 3.10+
set "PY="
for %%C in (py python python3) do (
  if not defined PY (
    %%C -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
    if !errorlevel! equ 0 set "PY=%%C"
  )
)
if not defined PY (
  echo 未找到 Python 3.10 或更新版本。
  echo 请从 https://www.python.org/downloads/ 安装，安装时勾选 "Add Python to PATH"。
  pause
  exit /b 1
)
REM py 启动器要带 -3，否则可能是 Python 2
if "%PY%"=="py" set "PY=py -3"

REM runtime\ 里是预装好的依赖；空的话就地装一份进去，不污染系统 Python。
if not exist "%~dp0runtime\flask\__init__.py" (
  echo → 首次运行，正在安装依赖到 runtime\（只装一次，需要联网）
  if exist "%~dp0requirements.txt" (
    %PY% -m pip install --quiet --disable-pip-version-check --target "%~dp0runtime" -r "%~dp0requirements.txt"
  ) else (
    %PY% -m pip install --quiet --disable-pip-version-check --target "%~dp0runtime" flask requests python-dotenv
  )
  if errorlevel 1 (
    echo.
    echo 依赖安装失败。Python 安装包一般都带 pip，如果没有请先修好：
    echo   %PY% -m ensurepip --upgrade
    echo 再重新运行 start.bat。
    pause
    exit /b 1
  )
)

if "%1"=="--status" goto status
if "%1"=="--stop" goto stop

REM 已经在跑就不重复启动
call :check
if not errorlevel 1 goto open

echo → 启动学习服务（%PY%）
start "" /b %PY% -m src.learning_server --data "%RUN%\learning" --port %VH_PORT% >>"%LOG%" 2>&1

for /l %%i in (1,1,80) do (
  timeout /t 1 /nobreak >nul
  call :check
  if not errorlevel 1 goto open
)
echo 服务未能启动，日志：%LOG%
pause
exit /b 1

:open
set "URL=http://127.0.0.1:%VH_PORT%/learn"
echo 已就绪：%URL%
REM 用 Edge/Chrome 的 app 模式开独立窗口，没有就用默认浏览器
set "BROWSER="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if defined BROWSER (
  start "" "%BROWSER%" --app="%URL%" --window-size=1560,980 --user-data-dir="%RUN%\window-profile"
) else (
  start "" "%URL%"
)
exit /b 0

:check
curl -sf --max-time 2 "http://127.0.0.1:%VH_PORT%/api/learning/health" 2>nul | findstr /c:"videohub-learning" >nul
exit /b %errorlevel%

:status
call :check
if errorlevel 1 (echo 服务未运行) else (echo 服务运行中：http://127.0.0.1:%VH_PORT%/learn)
exit /b 0

:stop
REM 只杀本绿色版自己的进程：命令行里带本目录路径的 python
set "FOUND="
for /f "tokens=2 delims=," %%P in ('wmic process where "name='python.exe'" get processid^,commandline /format:csv ^| findstr /c:"src.learning_server"') do (
  taskkill /pid %%P /f >nul 2>&1
  set "FOUND=1"
)
if defined FOUND (echo 已停止服务) else (echo 没有找到本绿色版的运行进程)
exit /b 0
