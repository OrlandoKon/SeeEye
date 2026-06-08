# SeeEye 打包脚本
# 用法：在虚拟环境激活后运行 .\build.ps1

$ErrorActionPreference = "Stop"

$pyinstaller = Join-Path $PSScriptRoot ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyinstaller)) {
    Write-Error "未找到 pyinstaller，请先激活虚拟环境并安装：pip install pyinstaller"
    exit 1
}

& $pyinstaller `
  --onefile `
  --windowed `
  --name "SeeEye" `
  --add-data "Eye.svg;." `
  --hidden-import "PyQt6.QtSvg" `
  --hidden-import "PyQt6.QtSvgWidgets" `
  --hidden-import "pynput.keyboard._win32" `
  --hidden-import "pynput.mouse._win32" `
  main.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "打包完成，可执行文件在：dist\SeeEye.exe"
} else {
    Write-Host ""
    Write-Error "打包失败，请查看上方错误信息"
}
