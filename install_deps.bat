@echo off
rem AutoPilot 新设备一键安装：宿主侧 JDK / Node / Appium，以及 Python 依赖。
rem 仓库内 resources/（re_adb、re_go_ios、re_scrcpy 等）已有则跳过，不重复下载。

chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title AutoPilot 设备依赖安装

cd /d "%~dp0"

echo ======================================================
echo       AutoPilot 新设备一键安装
echo ======================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_deps.ps1" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 安装过程出现错误，请查看上方输出。
    pause
    exit /b %ERRORLEVEL%
)
