# AutoPilot 新设备一键安装（Windows）。
# 借鉴 Artemis scripts/install_deps.ps1 的 PATH 刷新、WinGet 与用户态便携安装，
# 但只安装本项目真正需要的宿主工具；本仓库 resources/ 已有的二进制一律跳过。

<#
.SYNOPSIS
    为新电脑安装 AutoPilot 跑 Android/iOS/Web 所需的宿主依赖。
.PARAMETER SkipPython
    不创建 .venv、不 pip install。
.PARAMETER SkipAppium
    不安装 Node/Appium（仅 iOS WDA-direct 或纯 Web 时可跳过）。
.PARAMETER WithPlaywright
    额外安装 Playwright Chromium。
.PARAMETER WithAllPython
    Python 额外安装 data/secure/web_playwright。
.PARAMETER CheckOnly
    只体检，不安装。
#>

[CmdletBinding()]
param(
    [switch]$SkipPython = $false,
    [switch]$SkipAppium = $false,
    [switch]$WithPlaywright = $false,
    [switch]$WithAllPython = $false,
    [switch]$CheckOnly = $false
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

try {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
} catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir = Split-Path -Parent $ScriptDir
Set-Location $RootDir

$LocalRes = Join-Path $RootDir "resources"

$NodeVer = "v22.23.2"
$MinNodeMajor = 18
$MinJavaMajor = 17

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "   AutoPilot 新设备一键安装（Windows）" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "   仓库: $RootDir"
Write-Host "   resources: $LocalRes" -ForegroundColor DarkGray

function Test-CommandExists {
    param([string]$Command)
    return $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Update-EnvironmentPath {
    $standardDirs = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
        "$env:LOCALAPPDATA\Programs\node",
        "$env:USERPROFILE\.local\share\node",
        "$env:LOCALAPPDATA\Programs\platform-tools",
        "$env:USERPROFILE\.local\share\platform-tools",
        "$env:USERPROFILE\.local\bin",
        "$env:USERPROFILE\scoop\shims",
        "C:\ProgramData\chocolatey\bin",
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools",
        "$env:LOCALAPPDATA\Android\android-sdk\platform-tools",
        "$env:ProgramFiles\Android\platform-tools",
        "${env:ProgramFiles(x86)}\Android\android-sdk\platform-tools",
        "$env:ProgramFiles\nodejs",
        "${env:ProgramFiles(x86)}\nodejs",
        "$env:APPDATA\npm",
        "$env:ProgramFiles\Microsoft\jdk-17*",
        "$env:ProgramFiles\Eclipse Adoptium\jdk-17*"
    )
    if ($env:ANDROID_HOME) { $standardDirs += "$env:ANDROID_HOME\platform-tools" }
    if ($env:ANDROID_SDK_ROOT) { $standardDirs += "$env:ANDROID_SDK_ROOT\platform-tools" }
    if ($env:JAVA_HOME) { $standardDirs += "$env:JAVA_HOME\bin" }
    if ($env:NVM_SYMLINK) { $standardDirs = @($env:NVM_SYMLINK) + $standardDirs }

    $regPath = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $currentPaths = ($env:PATH -split ";") + ($regPath -split ";") + $standardDirs |
        Where-Object { $_ -and (Test-Path $_) } |
        Select-Object -Unique
    $env:PATH = $currentPaths -join ";"

    foreach ($portable in @(
        "$env:LOCALAPPDATA\Programs\node",
        "$env:LOCALAPPDATA\Programs\platform-tools"
    )) {
        if (Test-Path $portable) {
            $env:PATH = "$portable;$env:PATH"
        }
    }
}

function Add-UserPath {
    param([Parameter(Mandatory=$true)][string]$Dir)
    if (-not (Test-Path $Dir)) { return }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    $parts = @($userPath -split ";" | Where-Object { $_ })
    if ($parts -contains $Dir) { return }
    [Environment]::SetEnvironmentVariable("Path", ($Dir + ";" + $userPath).Trim(";"), "User")
    $env:PATH = "$Dir;$env:PATH"
    Write-Host "   [OK] 已写入用户 PATH: $Dir" -ForegroundColor Green
}

function Test-LocalResource {
    param([Parameter(Mandatory=$true)][string]$RelativePath)
    return Test-Path (Join-Path $LocalRes $RelativePath)
}

function Invoke-DownloadFile {
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [Parameter(Mandatory=$true)][string]$OutFile,
        [int]$TimeoutSec = 90
    )
    if (Test-Path $OutFile) {
        Remove-Item -Path $OutFile -Force -ErrorAction SilentlyContinue
    }
    if (Test-CommandExists "curl.exe") {
        try {
            & curl.exe -f -sSL --connect-timeout 8 --max-time $TimeoutSec "$Uri" -o "$OutFile" 2>$null
            if ($LASTEXITCODE -eq 0 -and (Test-Path $OutFile) -and ((Get-Item $OutFile).Length -gt 0)) {
                return $true
            }
        } catch {}
        if (Test-Path $OutFile) { Remove-Item -Path $OutFile -Force -ErrorAction SilentlyContinue }
    }
    try {
        $prevProgress = $ProgressPreference
        $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri $Uri -OutFile $OutFile -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
        $ProgressPreference = $prevProgress
        if ((Test-Path $OutFile) -and ((Get-Item $OutFile).Length -gt 0)) {
            return $true
        }
    } catch {
        $ProgressPreference = $prevProgress
    }
    if (Test-Path $OutFile) { Remove-Item -Path $OutFile -Force -ErrorAction SilentlyContinue }
    return $false
}

function Get-NodeMajor {
    if (-not (Test-CommandExists "node")) { return 0 }
    try {
        $ver = (& node -v 2>$null).ToString().Trim().TrimStart("v")
        return [int]($ver.Split(".")[0])
    } catch {
        return 0
    }
}

function Test-NodeReady {
    $hasNpm = (Test-CommandExists "npm") -or (Test-CommandExists "npm.cmd")
    return ((Get-NodeMajor) -ge $MinNodeMajor) -and $hasNpm
}

function Get-JavaMajor {
    if (-not (Test-CommandExists "java")) { return 0 }
    try {
        $raw = & java -version 2>&1 | Out-String
        if ($raw -match 'version "1\.(\d+)') { return [int]$Matches[1] }
        if ($raw -match 'version "(\d+)') { return [int]$Matches[1] }
    } catch {}
    return 0
}

function Install-PortablePlatformTools {
    $ptDir = "$env:LOCALAPPDATA\Programs\platform-tools"
    if (Test-Path "$ptDir\adb.exe") {
        Add-UserPath $ptDir
        return $true
    }
    Write-Host "   [INFO] 内置 re_adb 不在仓库中，安装用户态 Android platform-tools..." -ForegroundColor Cyan
    $zipPath = "$env:TEMP\platform-tools-windows.zip"
    if (Invoke-DownloadFile -Uri "https://dl.google.com/android/repository/platform-tools-latest-windows.zip" -OutFile $zipPath -TimeoutSec 90) {
        New-Item -ItemType Directory -Path "$env:LOCALAPPDATA\Programs" -Force | Out-Null
        Expand-Archive -Path $zipPath -DestinationPath "$env:LOCALAPPDATA\Programs" -Force
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        if (Test-Path "$ptDir\adb.exe") {
            Add-UserPath $ptDir
            Write-Host "   [OK] adb 已装到用户目录（未写入 resources/）。" -ForegroundColor Green
            return $true
        }
    }
    Write-Host "   [WARN] 便携 adb 安装失败。可稍后把 platform-tools zip 放到 resources/re_adb/。" -ForegroundColor DarkYellow
    return $false
}

function Install-PortableNode {
    $nodeDir = "$env:LOCALAPPDATA\Programs\node"
    if ((Test-Path "$nodeDir\node.exe") -and (Test-NodeReady)) {
        Add-UserPath $nodeDir
        return $true
    }
    Write-Host "   [INFO] 安装便携 Node.js $NodeVer 到用户目录..." -ForegroundColor Cyan
    $arch = if ($env:PROCESSOR_ARCHITECTURE -match "ARM64") { "arm64" } else { "x64" }
    $zipPath = "$env:TEMP\node-$NodeVer-win-$arch.zip"
    $uri = "https://nodejs.org/dist/$NodeVer/node-$NodeVer-win-$arch.zip"
    if (Invoke-DownloadFile -Uri $uri -OutFile $zipPath -TimeoutSec 90) {
        $extractDir = "$env:TEMP\node_extract"
        if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue }
        New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
        $extractedFolder = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
        if ($extractedFolder) {
            if (-not (Test-Path $nodeDir)) {
                New-Item -ItemType Directory -Path $nodeDir -Force | Out-Null
            }
            Copy-Item -Path "$($extractedFolder.FullName)\*" -Destination $nodeDir -Recurse -Force
        }
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path "$nodeDir\node.exe") {
            Add-UserPath $nodeDir
            Write-Host "   [OK] 便携 Node.js $NodeVer 已就绪。" -ForegroundColor Green
            return $true
        }
    }
    Write-Host "   [WARN] 便携 Node.js 安装失败。" -ForegroundColor DarkYellow
    return $false
}

function Install-JdkIfNeeded {
    if ((Get-JavaMajor) -ge $MinJavaMajor) {
        if (-not $env:JAVA_HOME) {
            $guess = Get-ChildItem "$env:ProgramFiles\Microsoft","$env:ProgramFiles\Eclipse Adoptium","$env:ProgramFiles\Java" -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match "jdk-?1[7-9]|jdk-2" } |
                Select-Object -First 1
            if ($guess) {
                $env:JAVA_HOME = $guess.FullName
                Add-UserPath (Join-Path $guess.FullName "bin")
            }
        }
        return $true
    }
    if (-not (Test-CommandExists "winget")) {
        Write-Host "   [WARN] 未找到 JDK 17+，且没有 WinGet。请手工安装 Temurin/Microsoft OpenJDK 17 并设 JAVA_HOME。" -ForegroundColor DarkYellow
        return $false
    }
    Write-Host "   [INFO] 通过 WinGet 安装 Microsoft OpenJDK 17..." -ForegroundColor Cyan
    winget install --id Microsoft.OpenJDK.17 -e --accept-source-agreements --accept-package-agreements --silent 2>$null | Out-Null
    Update-EnvironmentPath
    if ((Get-JavaMajor) -ge $MinJavaMajor) { return $true }
    Write-Host "   [WARN] JDK 仍未就绪。Android Appium 需要 JDK 17+。" -ForegroundColor DarkYellow
    return $false
}

function Get-NpmExe {
    if (Test-CommandExists "npm.cmd") { return "npm.cmd" }
    if (Test-CommandExists "npm") { return "npm" }
    return $null
}

function Install-AppiumStack {
    if (-not (Test-NodeReady)) {
        if (Test-CommandExists "nvm") {
            Write-Host "   [INFO] 通过 nvm 安装 Node 22..." -ForegroundColor Cyan
            & nvm install 22.23.2 | Out-Null
            & nvm use 22.23.2 | Out-Null
            Update-EnvironmentPath
        }
        if (-not (Test-NodeReady) -and (Test-CommandExists "winget")) {
            Write-Host "   [INFO] 通过 WinGet 安装 Node.js LTS..." -ForegroundColor Cyan
            winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements --silent 2>$null | Out-Null
            Update-EnvironmentPath
        }
        if (-not (Test-NodeReady)) {
            Install-PortableNode | Out-Null
            Update-EnvironmentPath
        }
    }
    if (-not (Test-NodeReady)) {
        Write-Host "   [FAIL] Node.js >= $MinNodeMajor 未就绪，跳过 Appium。" -ForegroundColor Red
        return $false
    }
    $nodeVer = & node -v 2>$null
    Write-Host "   [OK] Node.js $nodeVer" -ForegroundColor Green

    $npm = Get-NpmExe
    if (-not $npm) {
        Write-Host "   [FAIL] 未找到 npm。" -ForegroundColor Red
        return $false
    }
    if (-not (Test-CommandExists "appium")) {
        Write-Host "   [INFO] npm install -g appium ..." -ForegroundColor Cyan
        & $npm install -g appium --no-fund --no-audit
        Update-EnvironmentPath
        Add-UserPath "$env:APPDATA\npm"
    }
    if (-not (Test-CommandExists "appium")) {
        Write-Host "   [FAIL] Appium CLI 安装失败。" -ForegroundColor Red
        return $false
    }
    $aver = (& appium --version 2>$null)
    Write-Host "   [OK] Appium $aver" -ForegroundColor Green
    Write-Host "   [INFO] appium driver install uiautomator2 ..." -ForegroundColor Cyan
    & appium driver install uiautomator2
    return $true
}

function Install-PythonEnv {
    $py = $null
    foreach ($cand in @("py", "python", "python3")) {
        if (Test-CommandExists $cand) { $py = $cand; break }
    }
    if (-not $py) {
        Write-Host "   [FAIL] 未找到 Python。请先安装 Python 3.10+ 并勾选 Add to PATH。" -ForegroundColor Red
        return $false
    }
    $venvPy = Join-Path $RootDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Host "   [INFO] 创建 .venv ..." -ForegroundColor Cyan
        if ($py -eq "py") {
            & py -3 -m venv (Join-Path $RootDir ".venv")
        } else {
            & $py -m venv (Join-Path $RootDir ".venv")
        }
    }
    if (-not (Test-Path $venvPy)) {
        Write-Host "   [FAIL] 创建虚拟环境失败。" -ForegroundColor Red
        return $false
    }
    Write-Host "   [INFO] pip install -e .[mirror] ..." -ForegroundColor Cyan
    & $venvPy -m pip install --upgrade pip
    $spec = if ($WithAllPython) { ".[data,mirror,secure,web_playwright]" } else { ".[mirror]" }
    & $venvPy -m pip install -e $spec
    if ($LASTEXITCODE -ne 0) { return $false }
    if ($WithPlaywright -or $WithAllPython) {
        Write-Host "   [INFO] playwright install chromium ..." -ForegroundColor Cyan
        & $venvPy -m playwright install chromium
    }
    return $true
}

function Initialize-DotEnv {
    $envFile = Join-Path $RootDir ".env"
    $example = Join-Path $RootDir ".env.example"
    if (Test-Path $envFile) {
        Write-Host "   [OK] .env 已存在" -ForegroundColor Green
        return
    }
    if (Test-Path $example) {
        Copy-Item $example $envFile
        Write-Host "   [OK] 已从 .env.example 生成 .env" -ForegroundColor Green
    }
}

function Show-ResourceSkipReport {
    Write-Host "`n1. 内置设备资源（本仓库 resources/ 已有则跳过）..." -ForegroundColor Yellow
    $adbtag = "windows"
    $items = @(
        @{ Name = "re_adb (platform-tools zip)"; Rel = "re_adb\platform-tools-latest-$adbtag.zip" },
        @{ Name = "re_aapt"; Rel = "re_aapt\aapt-windows.zip" },
        @{ Name = "re_scrcpy/scrcpy-server.jar"; Rel = "re_scrcpy\scrcpy-server.jar" },
        @{ Name = "re_uiautomator 设备侧 apk"; Rel = "re_uiautomator\app-uiautomator.apk" },
        @{ Name = "re_go_ios/executable"; Rel = "re_go_ios\executable\win\ios.exe" },
        @{ Name = "re_go_ios/devimages"; Rel = "re_go_ios\devimages" }
    )
    foreach ($it in $items) {
        if (Test-LocalResource $it.Rel) {
            Write-Host "   [SKIP] $($it.Name) 已在 resources/，不重复下载" -ForegroundColor Green
        } else {
            Write-Host "   [MISS] $($it.Name) 未找到（运行期对应能力可能不可用）" -ForegroundColor DarkYellow
        }
    }
}

function Show-Summary {
    Write-Host "`n就绪摘要:" -ForegroundColor Yellow
    $tools = @(
        @{ Name = "adb"; Need = "Android 设备层；有 re_adb 时运行期会自解压" },
        @{ Name = "java"; Need = "Appium uiautomator2" },
        @{ Name = "node"; Need = "Appium CLI" },
        @{ Name = "appium"; Need = "Android 会话" }
    )
    foreach ($t in $tools) {
        if (Test-CommandExists $t.Name) {
            $src = (Get-Command $t.Name).Source
            Write-Host "   [OK] $($t.Name) -> $src" -ForegroundColor Green
        } else {
            Write-Host "   [--] $($t.Name) 不在 PATH（$($t.Need)）" -ForegroundColor DarkYellow
        }
    }
    $venvPy = Join-Path $RootDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        Write-Host "   [OK] Python venv -> $venvPy" -ForegroundColor Green
    } else {
        Write-Host "   [--] .venv 未创建" -ForegroundColor DarkYellow
    }
}

# ---- 执行 ----
Update-EnvironmentPath
Show-ResourceSkipReport

if ($CheckOnly) {
    Write-Host "`n[CheckOnly] 仅体检，不安装。" -ForegroundColor Cyan
    Show-Summary
    exit 0
}

Write-Host "`n2. Android 设备层 adb ..." -ForegroundColor Yellow
if (Test-LocalResource "re_adb\platform-tools-latest-windows.zip") {
    Write-Host "   [SKIP] 使用仓库 resources/re_adb，不安装系统 adb。" -ForegroundColor Green
} elseif (Test-CommandExists "adb") {
    Write-Host "   [OK] PATH 上已有 adb" -ForegroundColor Green
} else {
    Install-PortablePlatformTools | Out-Null
}

Write-Host "`n3. JDK 17+（Appium Android）..." -ForegroundColor Yellow
Install-JdkIfNeeded | Out-Null

if ($SkipAppium) {
    Write-Host "`n4. [SKIP] 按参数跳过 Node / Appium" -ForegroundColor DarkYellow
} else {
    Write-Host "`n4. Node.js + Appium + uiautomator2 ..." -ForegroundColor Yellow
    Install-AppiumStack | Out-Null
}

Write-Host "`n5. 环境文件 .env ..." -ForegroundColor Yellow
Initialize-DotEnv

if ($SkipPython) {
    Write-Host "`n6. [SKIP] 按参数跳过 Python 依赖" -ForegroundColor DarkYellow
} else {
    Write-Host "`n6. Python 虚拟环境与项目依赖 ..." -ForegroundColor Yellow
    Install-PythonEnv | Out-Null
}

if (Test-CommandExists "adb") {
    try {
        $orig = $env:ADB_SERVER_SOCKET
        Remove-Item Env:\ADB_SERVER_SOCKET -ErrorAction SilentlyContinue
        & adb start-server 2>$null | Out-Null
        if ($orig) { $env:ADB_SERVER_SOCKET = $orig }
    } catch {}
}

Show-Summary

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "   安装流程结束。建议再跑一次预检：" -ForegroundColor Green
Write-Host "     .venv\Scripts\python.exe tools\preflight.py" -ForegroundColor Cyan
Write-Host "     .venv\Scripts\python.exe tools\preflight.py --install-drivers" -ForegroundColor Cyan
Write-Host "   启动 IDE：  .venv\Scripts\python.exe run.py" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
