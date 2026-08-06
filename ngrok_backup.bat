@echo off
chcp 65001 >nul
title 校园先知 - 备用公网链接

echo.
echo   ╔══════════════════════════════════════════════╗
echo   ║  🏛️  校园先知 - 备用公网链接               ║
echo   ║     Streamlit Cloud 休眠时使用              ║
echo   ╚══════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

echo   [..] 检查本地 Streamlit...
curl -s -o nul http://localhost:8501 2>nul
if %errorlevel% neq 0 (
    echo   [!] localhost:8501 未响应，正在启动 Streamlit...
    start "Streamlit" streamlit run app.py --server.port 8501
    echo   [..] 等待启动 (10s)...
    timeout /t 10 /nobreak >nul
)

where ngrok >nul 2>&1
if %errorlevel% neq 0 (
    echo   [X] 未找到 ngrok，请先安装: https://ngrok.com/download
    pause
    exit /b 1
)

echo   [>>] 启动 ngrok 隧道...
echo   [>>] 下方链接即为公网地址，手机扫码可访问
echo.

ngrok http 8501
pause
