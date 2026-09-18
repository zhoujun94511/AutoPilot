#!/usr/bin/env bash
# AutoPilot 新设备一键安装（macOS / Linux）。
# 借鉴 Artemis scripts/install_deps.sh 的 PATH 归一化、brew/apt 与用户态回退，
# 但只安装本项目真正需要的宿主工具；本仓库 resources/ 已有的二进制一律跳过。
#
# 用法:
#   ./scripts/install_deps.sh
#   ./scripts/install_deps.sh --skip-python --skip-appium
#   ./scripts/install_deps.sh --playwright --all-python
#   ./scripts/install_deps.sh --check

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

SKIP_PYTHON=false
SKIP_APPIUM=false
WITH_PLAYWRIGHT=false
WITH_ALL_PYTHON=false
CHECK_ONLY=false
for arg in "$@"; do
    case "${arg}" in
        --skip-python) SKIP_PYTHON=true ;;
        --skip-appium) SKIP_APPIUM=true ;;
        --playwright|--with-playwright) WITH_PLAYWRIGHT=true ;;
        --all-python) WITH_ALL_PYTHON=true ;;
        --check|--check-only) CHECK_ONLY=true ;;
        -h|--help)
            sed -n '1,12p' "$0"
            exit 0
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_RES="${ROOT_DIR}/resources"
cd "${ROOT_DIR}"

OS_TYPE="$(uname -s)"
ARCH_TYPE="$(uname -m)"
NODE_VER="v22.23.2"
MIN_NODE_MAJOR=18
MIN_JAVA_MAJOR=17

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

normalize_path() {
    local STANDARD_PATHS=(
        "/opt/homebrew/bin"
        "/opt/homebrew/sbin"
        "/usr/local/bin"
        "/usr/local/sbin"
        "${HOME}/.local/bin"
        "${HOME}/.local/share/node/bin"
        "${HOME}/.local/share/platform-tools"
        "${HOME}/.cargo/bin"
        "${HOME}/Library/Android/sdk/platform-tools"
        "${HOME}/Android/Sdk/platform-tools"
    )
    local p
    for p in "${STANDARD_PATHS[@]}"; do
        if [ -d "${p}" ] && [[ ":${PATH}:" != *":${p}:"* ]]; then
            export PATH="${p}:${PATH}"
        fi
    done
    if [ -n "${ANDROID_HOME:-}" ] && [ -d "${ANDROID_HOME}/platform-tools" ]; then
        export PATH="${ANDROID_HOME}/platform-tools:${PATH}"
    fi
    if [ -n "${JAVA_HOME:-}" ] && [ -d "${JAVA_HOME}/bin" ]; then
        export PATH="${JAVA_HOME}/bin:${PATH}"
    fi
}

local_resource() {
    [ -e "${LOCAL_RES}/$1" ]
}

adb_zip_name() {
    case "${OS_TYPE}" in
        Darwin) echo "platform-tools-latest-darwin.zip" ;;
        Linux) echo "platform-tools-latest-linux.zip" ;;
        *) echo "platform-tools-latest-linux.zip" ;;
    esac
}

aapt_zip_name() {
    case "${OS_TYPE}" in
        Darwin) echo "aapt-macos.zip" ;;
        Linux) echo "aapt-linux.zip" ;;
        *) echo "aapt-linux.zip" ;;
    esac
}

go_ios_bin() {
    case "${OS_TYPE}" in
        Darwin) echo "re_go_ios/executable/mac/ios" ;;
        Linux) echo "re_go_ios/executable/linux/ios" ;;
        *) echo "re_go_ios/executable/linux/ios" ;;
    esac
}

node_major() {
    has_cmd node || { echo 0; return; }
    node -v 2>/dev/null | tr -d 'v' | cut -d. -f1
}

java_major() {
    has_cmd java || { echo 0; return; }
    local raw
    raw="$(java -version 2>&1 || true)"
    if echo "${raw}" | grep -Eq 'version "1\.'; then
        echo "${raw}" | sed -n 's/.*version "1\.\([0-9]*\).*/\1/p' | head -n1
        return
    fi
    echo "${raw}" | sed -n 's/.*version "\([0-9]*\).*/\1/p' | head -n1
}

node_ready() {
    local maj
    maj="$(node_major)"
    [ "${maj:-0}" -ge "${MIN_NODE_MAJOR}" ] && has_cmd npm
}

request_sudo() {
    [ "$(id -u)" -eq 0 ] && return 0
    has_cmd sudo || return 1
    sudo -n true >/dev/null 2>&1 && return 0
    if [ -t 0 ]; then
        echo -e "   ${CYAN}需要管理员权限：${1:-install packages}${NC}"
        sudo -v && return 0
    fi
    return 1
}

install_portable_adb() {
    if has_cmd adb; then
        return 0
    fi
    local os_sys
    os_sys="$(echo "${OS_TYPE}" | tr '[:upper:]' '[:lower:]')"
    [ "${os_sys}" = "darwin" ] && os_sys="darwin"
    [ "${os_sys}" = "linux" ] || [ "${os_sys}" = "darwin" ] || return 1
    local pt_dir="${HOME}/.local/share/platform-tools"
    if [ ! -x "${pt_dir}/adb" ]; then
        echo -e "   ${CYAN}内置 re_adb 不在仓库中，安装用户态 platform-tools...${NC}"
        mkdir -p "${HOME}/.local/share" "${HOME}/.local/bin"
        local zip="/tmp/platform-tools-$$.zip"
        if curl -fsSL --connect-timeout 8 --max-time 90 \
            "https://dl.google.com/android/repository/platform-tools-latest-${os_sys}.zip" -o "${zip}"; then
            if has_cmd unzip; then
                unzip -q -o "${zip}" -d "${HOME}/.local/share" || true
            else
                python3 -m zipfile -e "${zip}" "${HOME}/.local/share" 2>/dev/null || true
            fi
            rm -f "${zip}"
        fi
    fi
    if [ -x "${pt_dir}/adb" ]; then
        ln -sf "${pt_dir}/adb" "${HOME}/.local/bin/adb"
        export PATH="${pt_dir}:${PATH}"
        echo -e "   ${GREEN}✓ adb 已装到用户目录（未写入 resources/）${NC}"
        return 0
    fi
    echo -e "   ${YELLOW}⚠ 便携 adb 安装失败${NC}"
    return 1
}

install_portable_node() {
    if node_ready; then
        return 0
    fi
    local node_arch=""
    case "${ARCH_TYPE}" in
        x86_64|amd64) node_arch="x64" ;;
        aarch64|arm64) node_arch="arm64" ;;
    esac
    local os_sys
    os_sys="$(uname -s | tr '[:upper:]' '[:lower:]')"
    [ -n "${node_arch}" ] || return 1
    local node_dir="${HOME}/.local/share/node"
    echo -e "   ${CYAN}安装便携 Node.js ${NODE_VER}...${NC}"
    mkdir -p "${node_dir}" "${HOME}/.local/bin"
    if curl -fsSL --connect-timeout 8 --max-time 90 \
        "https://nodejs.org/dist/${NODE_VER}/node-${NODE_VER}-${os_sys}-${node_arch}.tar.gz" \
        | tar -xz -C "${node_dir}" --strip-components=1; then
        ln -sf "${node_dir}/bin/node" "${HOME}/.local/bin/node"
        ln -sf "${node_dir}/bin/npm" "${HOME}/.local/bin/npm"
        ln -sf "${node_dir}/bin/npx" "${HOME}/.local/bin/npx"
        export PATH="${node_dir}/bin:${HOME}/.local/bin:${PATH}"
        echo -e "   ${GREEN}✓ 便携 Node.js ${NODE_VER} 已就绪${NC}"
        return 0
    fi
    return 1
}

install_jdk() {
    local maj
    maj="$(java_major)"
    if [ "${maj:-0}" -ge "${MIN_JAVA_MAJOR}" ]; then
        echo -e "   ${GREEN}✓ Java $(java -version 2>&1 | head -n1)${NC}"
        return 0
    fi
    if [ "${OS_TYPE}" = "Darwin" ] && has_cmd brew; then
        echo -e "   ${CYAN}brew install openjdk@17 ...${NC}"
        brew install openjdk@17 || true
        if [ -d "/opt/homebrew/opt/openjdk@17" ]; then
            export JAVA_HOME="/opt/homebrew/opt/openjdk@17"
            export PATH="${JAVA_HOME}/bin:${PATH}"
        fi
    elif [ "${OS_TYPE}" = "Linux" ]; then
        if request_sudo "install JDK 17"; then
            local sudo_p=""
            [ "$(id -u)" -ne 0 ] && sudo_p="sudo"
            if has_cmd apt-get; then
                DEBIAN_FRONTEND=noninteractive ${sudo_p} apt-get install -y -qq openjdk-17-jdk || true
            elif has_cmd dnf; then
                ${sudo_p} dnf install -y java-17-openjdk-devel || true
            fi
        fi
    fi
    maj="$(java_major)"
    if [ "${maj:-0}" -ge "${MIN_JAVA_MAJOR}" ]; then
        return 0
    fi
    echo -e "   ${YELLOW}⚠ JDK 17+ 未就绪（Android Appium 需要）${NC}"
    return 1
}

install_appium_stack() {
    export NVM_DIR="${HOME}/.nvm"
    if [ -s "${NVM_DIR}/nvm.sh" ]; then
        # shellcheck disable=SC1090
        . "${NVM_DIR}/nvm.sh" 2>/dev/null || true
        nvm use 22 >/dev/null 2>&1 || true
    fi
    if ! node_ready && [ "${OS_TYPE}" = "Darwin" ] && has_cmd brew; then
        brew install node || brew upgrade node || true
    fi
    if ! node_ready; then
        install_portable_node || true
    fi
    if ! node_ready; then
        echo -e "   ${RED}✗ Node.js >= ${MIN_NODE_MAJOR} 未就绪，跳过 Appium${NC}"
        return 1
    fi
    echo -e "   ${GREEN}✓ Node.js $(node -v) / npm $(npm -v)${NC}"
    if ! has_cmd appium; then
        echo -e "   ${CYAN}npm install -g appium ...${NC}"
        npm install -g appium --no-fund --no-audit
    fi
    if ! has_cmd appium; then
        echo -e "   ${RED}✗ Appium CLI 安装失败${NC}"
        return 1
    fi
    echo -e "   ${GREEN}✓ Appium $(appium --version)${NC}"
    echo -e "   ${CYAN}appium driver install uiautomator2 ...${NC}"
    appium driver install uiautomator2 || true
    if [ "${OS_TYPE}" = "Darwin" ]; then
        echo -e "   ${CYAN}appium driver install xcuitest（仅 macOS）...${NC}"
        appium driver install xcuitest || true
    fi
}

install_python_env() {
    local py=""
    if has_cmd python3; then
        py="python3"
    elif has_cmd python; then
        py="python"
    else
        echo -e "   ${RED}✗ 未找到 Python 3.10+${NC}"
        return 1
    fi
    if [ ! -x "${ROOT_DIR}/.venv/bin/python" ]; then
        echo -e "   ${CYAN}创建 .venv ...${NC}"
        "${py}" -m venv "${ROOT_DIR}/.venv"
    fi
    local vpy="${ROOT_DIR}/.venv/bin/python"
    echo -e "   ${CYAN}pip install -e .[mirror] ...${NC}"
    "${vpy}" -m pip install --upgrade pip
    local spec=".[mirror]"
    if [ "${WITH_ALL_PYTHON}" = true ]; then
        spec=".[data,mirror,secure,web_playwright]"
    fi
    "${vpy}" -m pip install -e "${spec}"
    if [ "${WITH_PLAYWRIGHT}" = true ] || [ "${WITH_ALL_PYTHON}" = true ]; then
        "${vpy}" -m playwright install chromium || true
    fi
}

init_dotenv() {
    if [ -f "${ROOT_DIR}/.env" ]; then
        echo -e "   ${GREEN}✓ .env 已存在${NC}"
        return
    fi
    if [ -f "${ROOT_DIR}/.env.example" ]; then
        cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
        echo -e "   ${GREEN}✓ 已从 .env.example 生成 .env${NC}"
    fi
}

show_resources() {
    echo -e "\n${BOLD}1. 内置设备资源（本仓库 resources/ 已有则跳过）${NC}"
    local adbzip aaptzip goios
    adbzip="re_adb/$(adb_zip_name)"
    aaptzip="re_aapt/$(aapt_zip_name)"
    goios="$(go_ios_bin)"
    local items=(
        "re_adb (platform-tools zip)|${adbzip}"
        "re_aapt|${aaptzip}"
        "re_scrcpy/scrcpy-server.jar|re_scrcpy/scrcpy-server.jar"
        "re_uiautomator 设备侧 apk|re_uiautomator/app-uiautomator.apk"
        "re_go_ios/executable|${goios}"
        "re_go_ios/devimages|re_go_ios/devimages"
    )
    local item name rel
    for item in "${items[@]}"; do
        name="${item%%|*}"
        rel="${item#*|}"
        if local_resource "${rel}"; then
            echo -e "   ${GREEN}[SKIP]${NC} ${name} 已在 resources/，不重复下载"
        else
            echo -e "   ${YELLOW}[MISS]${NC} ${name} 未找到"
        fi
    done
}

show_summary() {
    echo -e "\n${BOLD}就绪摘要${NC}"
    local t loc
    for t in adb java node npm appium; do
        if has_cmd "${t}"; then
            loc="$(command -v "${t}")"
            echo -e "   ${GREEN}✔ ${t}${NC} ${DIM}-> ${loc}${NC}"
        else
            echo -e "   ${YELLOW}○ ${t}${NC} 不在 PATH"
        fi
    done
    if [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
        echo -e "   ${GREEN}✔ Python venv${NC} ${DIM}-> ${ROOT_DIR}/.venv/bin/python${NC}"
    else
        echo -e "   ${YELLOW}○ .venv 未创建${NC}"
    fi
}

normalize_path

echo -e "${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${CYAN}   AutoPilot 新设备一键安装 (${OS_TYPE} ${ARCH_TYPE})${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}"
echo -e "   仓库: ${DIM}${ROOT_DIR}${NC}"
echo -e "   resources: ${DIM}${LOCAL_RES}${NC}"

show_resources

if [ "${CHECK_ONLY}" = true ]; then
    echo -e "\n${CYAN}[--check] 仅体检，不安装${NC}"
    show_summary
    exit 0
fi

echo -e "\n${BOLD}2. Android 设备层 adb${NC}"
if local_resource "re_adb/$(adb_zip_name)"; then
    echo -e "   ${GREEN}[SKIP] 使用仓库 resources/re_adb，不安装系统 adb${NC}"
elif has_cmd adb; then
    echo -e "   ${GREEN}✓ PATH 上已有 adb${NC}"
else
    install_portable_adb || true
fi

echo -e "\n${BOLD}3. JDK 17+（Appium Android）${NC}"
install_jdk || true

if [ "${SKIP_APPIUM}" = true ]; then
    echo -e "\n${BOLD}4. [SKIP] 按参数跳过 Node / Appium${NC}"
else
    echo -e "\n${BOLD}4. Node.js + Appium + uiautomator2${NC}"
    install_appium_stack || true
fi

echo -e "\n${BOLD}5. 环境文件 .env${NC}"
init_dotenv

if [ "${SKIP_PYTHON}" = true ]; then
    echo -e "\n${BOLD}6. [SKIP] 按参数跳过 Python 依赖${NC}"
else
    echo -e "\n${BOLD}6. Python 虚拟环境与项目依赖${NC}"
    install_python_env || true
fi

if has_cmd adb; then
    (unset ADB_SERVER_SOCKET; adb start-server >/dev/null 2>&1 || true)
fi

show_summary

echo -e "\n${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${GREEN}   安装流程结束。建议再跑一次预检：${NC}"
echo -e "     ${CYAN}.venv/bin/python tools/preflight.py${NC}"
echo -e "     ${CYAN}.venv/bin/python tools/preflight.py --install-drivers${NC}"
echo -e "   启动 IDE：  ${CYAN}.venv/bin/python run.py${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}"
