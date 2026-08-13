@echo off
chcp 65001 >nul
title 社区先知 CommunityInsight - 一键安装

echo.
echo   ╔══════════════════════════════════════════════╗
echo   ║  🏘️  社区先知 CommunityInsight Agent            ║
echo   ║     一键安装脚本                              ║
echo   ╚══════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: ── Step 0: 检查 Python ──
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [X] 未检测到 Python，请先安装 Python 3.10 或更高版本
    echo       下载: https://www.python.org/downloads/   ^(勾选 "Add to PATH"^)
    pause
    exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if %errorlevel% neq 0 (
    echo   [X] Python 版本过低，需要 3.10 或更高版本
    pause
    exit /b 1
)
echo   [OK] 检测到 Python

:: ── Step 1: 创建虚拟环境 ──
if exist "venv\Scripts\activate.bat" (
    echo   [OK] 虚拟环境已存在，跳过创建
) else (
    echo   [..] 创建虚拟环境 venv ...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo   [X] 虚拟环境创建失败
        pause
        exit /b 1
    )
)

:: ── Step 2: 激活虚拟环境 ──
call venv\Scripts\activate.bat

:: ── Step 3: 安装依赖 ──
echo   [..] 升级 pip ...
python -m pip install --upgrade pip -q
echo   [..] 安装项目依赖（首次约 2-5 分钟，请保持网络畅通）...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo   [X] 依赖安装失败，请检查网络后重试
    pause
    exit /b 1
)

:: ── Step 4: 初始化配置 ──
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo   [!] 已生成 .env 配置文件
    echo       请用记事本打开 .env 填入你的 API Key（DEEPSEEK_API_KEY / HEFENG_API_KEY）
    echo       不想申请 Key 也可以：把 .env 里的 OFFLINE_MODE 设为 true 即可离线演示
)

:: ── Step 5: 完成 ──
echo.
echo   ✅ 安装完成！
echo.
echo   [>>] 启动：双击 start.bat，浏览器会自动打开
echo        http://localhost:8501
echo.
echo   演示账号：居民 demo_resident（免密）/ 网格员 demo_grid（密码 demo123）/ 老年关怀版 demo_elderly（免密）
echo.
pause
