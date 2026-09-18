@echo off
chcp 65001 >nul
title 社区先知 CommunityInsight - 演示启动

echo.
echo   ============================================
echo     社区先知 CommunityInsight 演示启动
echo   ============================================
echo.

cd /d "%~dp0"

:: ===== Step 1: 检查 Python =====
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10 或更高版本
    echo        下载地址: https://www.python.org/downloads/
    echo        安装时请务必勾选 "Add Python to PATH"
    pause
    exit /b 1
)

python -c "import sys; assert sys.version_info >= (3,10)" 2>nul
if %errorlevel% neq 0 (
    echo [错误] Python 版本过低，请使用 Python 3.10 或更高版本
    pause
    exit /b 1
)
echo [OK] Python 环境正常

:: ===== Step 2: 检查依赖，缺失则自动安装 =====
python -c "import fastapi, uvicorn, dotenv, requests, cryptography, pydantic" 2>nul
if %errorlevel% neq 0 (
    echo [..] 正在安装依赖（首次运行约 1-3 分钟，请耐心等待）...
    python -m pip install -r requirements-web.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if %errorlevel% neq 0 (
        echo [提示] 镜像源安装失败，正在尝试官方源...
        python -m pip install -r requirements-web.txt
    )
    echo [OK] 依赖安装完成
) else (
    echo [OK] 依赖已就绪
)

:: ===== Step 3: 检查 .env 配置 =====
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [提示] 已自动生成 .env 配置文件
        echo        不填 API Key 也不影响核心功能演示（规则兜底）
    )
)

:: ===== Step 4: 检查前端产物（缺失会白屏，2026-09-15 新增）=====
if not exist "web\dist\index.html" (
    echo [警告] 未找到前端产物 web\dist —— 页面会白屏打不开
    where npm >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] 本机没有 Node.js，无法自动构建前端。
        echo        处理：在有 Node 的机器上执行  cd web  ^&^&  npm ci  ^&^&  npm run build
        echo        然后把生成的 web\dist 目录一起拷过来。
        pause
        exit /b 1
    )
    echo [..] 正在构建前端（约 30 秒）...
    pushd web
    call npm run build
    popd
    if not exist "web\dist\index.html" (
        echo [错误] 前端构建失败，请手动执行  cd web ^&^& npm run build  查看报错
        pause
        exit /b 1
    )
    echo [OK] 前端构建完成
) else (
    echo [OK] 前端产物已就绪
)

:: ===== Step 5: 检查 8000 端口 =====
netstat -ano | findstr ":8000.*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [警告] 8000 端口已被占用，可能已有服务在运行
    echo        处理：关掉占用 8000 的程序（可能是上次启动的本项目）后重试
    echo        查看占用：netstat -ano ^| findstr :8000
    pause
    exit /b 1
)

:: ===== Step 6: 启动服务（先起服务，探活成功后再开浏览器）=====
echo.
echo [启动] 正在启动主服务（首次会建库+迁移+灌演示数据，约 10-20 秒）...
echo.

start "社区先知-服务（关闭本窗口即停止服务）" /min cmd /c "python -m uvicorn api_web:app --host 127.0.0.1 --port 8000"

set /a tries=0
:waitloop
set /a tries+=1
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "try{Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/web/health' -TimeoutSec 3 | Out-Null; exit 0}catch{exit 1}" >nul 2>&1
if %errorlevel% equ 0 goto ready
if %tries% lss 25 goto waitloop

echo [警告] 等待 50 秒仍未就绪，仍尝试打开浏览器。
echo        若显示"无法访问"：稍等几秒按 F5；仍不行请看 .shots\logs\uvicorn.log 的报错。
start "" http://127.0.0.1:8000/login
pause
exit /b 1

:ready
echo [OK] 服务已就绪（第 %tries% 次探活通过）
start "" http://127.0.0.1:8000/login
echo.
echo   ============================================
echo     已打开：http://127.0.0.1:8000/login
echo     演示账号：居民/老年 点按钮免密 · 网格员 demo_grid / demo123
echo     属地化对比：demo_resident_cy / demo123（朝阳试点社区）
echo     停止服务：关闭那个最小化的"社区先知-服务"窗口
echo   ============================================
echo.
pause
