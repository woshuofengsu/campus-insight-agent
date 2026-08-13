@echo off
chcp 65001 >nul
title 社区先知 CommunityInsight

echo.
echo   ╔══════════════════════════════════════════════╗
echo   ║  🏘️  社区先知 CommunityInsight Agent           ║
echo   ║     竞赛演示启动脚本                         ║
echo   ╚══════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: ── Step 0: Check Python exists ──
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [X] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: ── Step 1: Activate venv if present ──
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo   [OK] venv 已激活
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo   [OK] .venv 已激活
)

:: ── Step 2: Check .env ──
if not exist ".env" (
    echo   [!] 未找到 .env
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo   [!] 已从 .env.example 复制模板，请编辑填入 API Key
    )
)

:: ── Step 3: Kill old Streamlit on port 8501 ──
echo   [..] 检查端口 8501...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501.*LISTENING" 2^>nul') do (
    echo   [..] 结束旧进程 PID=%%a
    taskkill /f /pid %%a >nul 2>&1
    timeout /t 2 /nobreak >nul
)

:: ── Step 4: Quick dependency check ──
python -c "import streamlit, sqlite3" 2>nul
if %errorlevel% neq 0 (
    echo   [X] 缺少依赖，请运行: pip install -r requirements.txt
    pause
    exit /b 1
)

:: ── Step 5: Start ──
echo.
echo   [>>] 启动中... http://localhost:8501
echo   [!!] 关闭此窗口即停止服务
echo.

start "" http://localhost:8501
streamlit run app.py --server.port 8501
pause
