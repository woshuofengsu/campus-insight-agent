# scripts/demo_start.ps1 — 一键启动演示环境（U5）
#
# 用法（在项目根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -SkipPreflight
#
# 做三件事：
#   1) 跑演示前自检（--fast），有问题先提示
#   2) 启动 FastAPI 主服务（后台）
#   3) 打开浏览器到登录页，并打印三角色演示账号
param(
    [switch]$SkipPreflight,
    [int]$Port = 8000
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "=== 社区先知 CommunityInsight · 一键演示启动 ===" -ForegroundColor Cyan

if (-not $SkipPreflight) {
    Write-Host "[1/3] 演示前自检（fast）..." -ForegroundColor Yellow
    python scripts/demo_preflight.py --fast
    if ($LASTEXITCODE -ne 0) {
        Write-Host "自检有未通过项，按上面提示修复后重试（或加 -SkipPreflight 跳过）。" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[1/3] 已跳过自检" -ForegroundColor DarkGray
}

# 端口占用检查
$busy = (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count
if ($busy -gt 0) {
    Write-Host "[2/3] 端口 $Port 已被占用，服务可能已在运行（跳过启动）" -ForegroundColor Yellow
} else {
    Write-Host "[2/3] 启动主服务（后台，端口 $Port）..." -ForegroundColor Yellow
    Start-Process -FilePath "python" `
        -ArgumentList "-m", "uvicorn", "api_web:app", "--host", "0.0.0.0", "--port", "$Port" `
        -WorkingDirectory $Root -WindowStyle Minimized
    Start-Sleep -Seconds 8
}

Write-Host "[3/3] 打开浏览器并打印演示账号" -ForegroundColor Yellow
Start-Process "http://127.0.0.1:$Port/login"

Write-Host ""
Write-Host "演示地址：http://127.0.0.1:$Port/login" -ForegroundColor Green
Write-Host "演示账号（DEMO_MODE=true 时免密登录）：" -ForegroundColor Green
Write-Host "  居民端  ：demo_resident（无密码）"
Write-Host "  老年端  ：demo_elderly（无密码）"
Write-Host "  网格员端：demo_grid / demo123"
Write-Host ""
Write-Host "演示要点：治理大屏 /stability 数据屏、网格员工作台红黑榜、工单批量操作、政策问答（含知识库命中率）" -ForegroundColor DarkCyan
Write-Host '停止服务：Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }' -ForegroundColor DarkGray
