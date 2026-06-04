# SeeEye 打包脚本
# 用法：在虚拟环境激活后运行 .\build.ps1

pyinstaller `
  --onefile `
  --windowed `
  --name "SeeEye" `
  --add-data "Eye.svg;." `
  --hidden-import "PyQt6.QtSvg" `
  --hidden-import "PyQt6.QtSvgWidgets" `
  --hidden-import "pynput.keyboard._win32" `
  --hidden-import "pynput.mouse._win32" `
  main.py

Write-Host ""
Write-Host "打包完成，可执行文件在：dist\SeeEye.exe"
