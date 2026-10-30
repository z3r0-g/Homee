#!/usr/bin/env bash

set -Eeuo pipefail

################################---------
# COLORS
#########################################

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[ OK ]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[FAIL]${NC} $1"; }

################################---------
# PROGRESS BAR
################################---------

TOTAL_STEPS=16
CURRENT_STEP=0

progress() {
    CURRENT_STEP=$((CURRENT_STEP+1))
    if (( CURRENT_STEP > TOTAL_STEPS )); then
        CURRENT_STEP=$TOTAL_STEPS
    fi

    local percent=$((CURRENT_STEP * 100 / TOTAL_STEPS))
    local filled=$((percent / 2))
    local empty=$((50 - filled))

    printf "\r"
    printf "${CYAN}Progress [${NC}"
    printf "%0.s█" $(seq 1 ${filled}) 2>/dev/null || true
    printf "%0.s░" $(seq 1 ${empty}) 2>/dev/null || true
    printf "${CYAN}] ${GREEN}%3d%%${NC}" "${percent}"
    echo
}

################################---------
# CONFIG
#########################################

APP_ROOT="$(pwd)"

UI_PORT=5001
MCP_PORT=5002

# Default model, RAM-aware (same rule as UI/model_catalog.py): llama3.2:3b
# is the default for all hosts — at ~2 GB it fits even a minimal 8 GB host
# and runs fastest on the CPU-only hardware Homee targets.
# An explicitly exported MODEL_NAME always wins.
if [ -z "${MODEL_NAME:-}" ]; then
    TOTAL_GB=$(free -g 2>/dev/null | awk '/^Mem:/{print $2}')
    if [ -n "$TOTAL_GB" ] && [ "$TOTAL_GB" -lt 12 ]; then
        MODEL_NAME="llama3.2:3b"
    else
        MODEL_NAME="llama3.2:3b"
    fi
fi

MIN_RAM_MB=8192
RECOMMENDED_RAM_MB=16384

MIN_CPU=4
RECOMMENDED_CPU=8

MIN_DISK_GB=20

################################---------
# FIND GUNICORN ENTRYPOINTS
#########################################

find_entrypoint() {
    local SEARCH_DIR="$1"

    if [[ -f "$SEARCH_DIR/app.py" ]]; then
        local rel
        rel=$(realpath --relative-to="$APP_ROOT" "$SEARCH_DIR/app.py")
        rel="${rel%.py}"
        rel="${rel//\//.}"
        echo "${rel}:app"
        return 0
    fi

    while IFS= read -r file
    do
        if grep -qE "(Flask)\(" "$file"; then
            local rel
            rel=$(realpath --relative-to="$APP_ROOT" "$file")
            rel="${rel%.py}"
            rel="${rel//\//.}"
            echo "${rel}:app"
            return 0
        fi
    done < <(find "$SEARCH_DIR" -name "*.py")

    return 1
}

UI_ENTRY=$(find_entrypoint UI || true)
MCP_ENTRY=$(find_entrypoint MCP || true)

if [[ -z "$UI_ENTRY" ]]; then
    error "Could not find Flask entrypoint in UI directory"
    exit 1
fi

if [[ -z "$MCP_ENTRY" ]]; then
    error "Could not find Flask entrypoint in MCP directory"
    exit 1
fi

################################---------
# HEADER
#########################################

clear

echo -e "${MAGENTA}"
echo "===================================================="
echo "                   HOMEE INSTALLER"
echo "===================================================="
echo -e "${NC}"

################################---------
# ROOT CHECK
#########################################

# Check if root is required (opt-in via REQUIRE_ROOT=1)
if [[ "${REQUIRE_ROOT:-0}" == "1" ]] && [[ $EUID -ne 0 ]]; then
    error "This operation requires root. Run with: sudo ./install.sh"
    exit 1
fi

################################---------
# OS VALIDATION
#########################################

info "Checking operating system..."

# Support both Ubuntu and Debian-based distributions (e.g., Debian Trixie in devcontainers)
if ! grep -qiE "^(ID|NAME)=.*(ubuntu|debian)" /etc/os-release; then
   error "Ubuntu/Debian required"
   exit 1
fi

success "Ubuntu/Debian detected"
progress

################################---------
# HARDWARE VALIDATION
#########################################

TOTAL_RAM=$(free -m | awk '/Mem:/ {print $2}')
CPU_CORES=$(nproc)
FREE_DISK=$(df -BG "$APP_ROOT" | awk 'NR==2 {gsub("G","",$4);print $4}')

echo
echo -e "${BOLD}Hardware Detection${NC}"
echo "RAM:       ${TOTAL_RAM} MB"
echo "CPU:       ${CPU_CORES} cores"
echo "FreeDisk:  ${FREE_DISK} GB"

if (( TOTAL_RAM < MIN_RAM_MB )); then
    error "Minimum RAM is 8GB"
    exit 1
fi

if (( CPU_CORES < MIN_CPU )); then
    error "Minimum CPU is 4 cores"
    exit 1
fi

if (( FREE_DISK < MIN_DISK_GB )); then
    error "Minimum free disk is 20GB"
    exit 1
fi

success "Hardware minimums satisfied"
progress

################################---------
# READINESS SCORE
#########################################

SCORE="B"

if (( TOTAL_RAM >= 32768 )) && (( CPU_CORES >= 12 )); then
    SCORE="A+"
elif (( TOTAL_RAM >= 16384 )) && (( CPU_CORES >= 8 )); then
    SCORE="A"
elif (( TOTAL_RAM >= 12288 )) && (( CPU_CORES >= 6 )); then
    SCORE="B+"
elif (( TOTAL_RAM >= 8192 )) && (( CPU_CORES >= 4 )); then
    SCORE="B"
else
    SCORE="C"
fi

echo
echo -e "${GREEN}Hardware Readiness Score: ${BOLD}${SCORE}${NC}"
progress

################################---------
# DEPENDENCIES
#########################################

info "Checking packages..."

apt update

apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    jq \
    net-tools \
    zstd

################################---------
# PYTHON VERSION
#########################################

PYVER=$(python3 -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')")

info "Python Version ${PYVER}"
progress

################################---------
# NODE
#########################################

if ! command -v node >/dev/null 2>&1; then
    warn "NodeJS missing"
else
    success "NodeJS found"
fi
progress

################################---------
# OLLAMA
#########################################

if ! command -v ollama >/dev/null 2>&1; then
    info "Ollama not found — installing automatically..."
    curl -fsSL https://ollama.com/install.sh | sh || {
        error "Ollama installation failed"
        exit 1
    }
    success "Ollama installed"
fi

success "Ollama installed"
progress

################################---------
# OLLAMA SERVICE
#########################################

if ! curl -fs http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    warn "Ollama API not responding — starting it..."
    # Stop any existing ollama processes first
    pkill -f "ollama serve" 2>/dev/null || true
    sleep 2

    # Start ollama server in background
    nohup ollama serve >/tmp/ollama-serve.log 2>&1 &

    # Wait up to 30 seconds for the API to respond
    for i in $(seq 1 30); do
        if curl -fs http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
            success "Ollama API is responding"
            break
        fi
        sleep 1
    done

    if ! curl -fs http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        error "Ollama failed to start. Check: tail /tmp/ollama-serve.log"
        exit 1
    fi
else
    success "Ollama service already running"
fi
progress

################################---------
# OLLAMA API TEST
#########################################

if ! curl -fs localhost:11434/api/tags >/dev/null; then
    error "Ollama not responding on 11434"
    exit 1
fi

success "Ollama API responding"
progress

################################---------
# MODEL CHECK
#########################################

if ! ollama list | grep -q "$MODEL_NAME"; then
    warn "$MODEL_NAME missing"
    read -p "Pull model now? [Y/n] " yn
    if [[ ! "$yn" =~ ^[Nn]$ ]]; then
        ollama pull "$MODEL_NAME"
    fi
fi

success "Model available"
progress

################################---------
# LLM BENCHMARK
#########################################

echo
echo -e "${BOLD}Running inference benchmark...${NC}"

START=$(date +%s)
ollama run "$MODEL_NAME" "reply only with OK" >/tmp/homee-test.out 2>/dev/null || true
END=$(date +%s)

LATENCY=$((END-START))

echo "Inference Time: ${LATENCY}s"

if (( LATENCY < 5 )); then
    success "Excellent response performance"
elif (( LATENCY < 15 )); then
    success "Acceptable response performance"
else
    warn "Model appears slower than expected"
fi

################################---------
# APP VALIDATION
#########################################

[[ -d UI ]] || { error "UI folder missing"; exit 1; }
[[ -d MCP ]] || { error "MCP folder missing"; exit 1; }

success "Application folders found"
progress

################################---------
# PORTS
#########################################

if ss -tulpn | grep -q ":5001 "; then
    error "Port 5001 already in use"
    exit 1
fi

if ss -tulpn | grep -q ":5002 "; then
    error "Port 5002 already in use"
    exit 1
fi

################################---------
# PYTHON ENVIRONMENT
#########################################

if [[ ! -d venv ]]; then
    info "Creating virtual environment"
    python3 -m venv venv
fi

source venv/bin/activate

pip install --upgrade pip

if [[ -f requirements.txt ]]; then
    pip install -r requirements.txt
fi

if ! command -v gunicorn >/dev/null 2>&1; then
    pip install gunicorn
fi

success "Python environment ready"
progress

################################---------
# FIREWALL
#########################################

if command -v ufw >/dev/null 2>&1 && [[ $EUID -eq 0 ]]; then
    ufw allow ${UI_PORT}/tcp || true
    ufw allow ${MCP_PORT}/tcp || true
    success "Firewall configured"
fi
progress

################################---------
# GUNICORN WORKERS
#########################################

WORKERS=$((CPU_CORES/2))

if (( WORKERS < 2 )); then
   WORKERS=2
fi

################################---------
# SYSTEMD MCP
#########################################

cat >/etc/systemd/system/homee-mcp.service <<EOF
[Unit]
Description=Homee MCP
After=network.target ollama.service

[Service]
Type=simple
WorkingDirectory=${APP_ROOT}
Environment=PATH=${APP_ROOT}/venv/bin
Environment=MCP_PORT=5002

ExecStart=${APP_ROOT}/venv/bin/gunicorn \\
 --workers ${WORKERS} \\
 --bind 0.0.0.0:5002 \\
 --timeout 300 \\
 ${MCP_ENTRY}

Restart=always
RestartSec=5
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
EOF

################################---------
# SYSTEMD UI
#########################################

cat >/etc/systemd/system/homee-ui.service <<EOF
[Unit]
Description=Homee UI
After=network.target homee-mcp.service
Requires=homee-mcp.service

[Service]
Type=simple
WorkingDirectory=${APP_ROOT}
Environment=PATH=${APP_ROOT}/venv/bin
Environment=UI_PORT=5001
Environment=MCP_SERVICE_URL=http://127.0.0.1:5002

ExecStart=${APP_ROOT}/venv/bin/gunicorn \\
 --workers ${WORKERS} \\
 --bind 0.0.0.0:5001 \\
 --timeout 300 \\
 ${UI_ENTRY}

Restart=always
RestartSec=5
StartLimitIntervalSec=0

[Install]
WantedBy=multi-user.target
EOF

success "Systemd services generated"
progress

################################---------
# SYSTEMD SERVICE MANAGEMENT
#########################################

# Only manage services via systemd if it is actually available
if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    info "Managing services via systemd..."
    systemctl daemon-reload

    systemctl enable homee-mcp
    systemctl enable homee-ui

    systemctl restart homee-mcp
    progress

    sleep 5

    systemctl restart homee-ui
    progress
else
    warn "systemd not detected — skipping service start."
    warn "Systemd unit files created at /etc/systemd/system/homee-*.service"
    warn "Use 'sudo systemctl enable --now homee-ui homee-mcp' when systemd is available."
fi

################################---------
# HEALTH CHECKS
#########################################

echo
echo -e "${BOLD}Health Checks${NC}"

sleep 5

curl -fs http://127.0.0.1:5002 >/dev/null \
    && success "MCP responding" \
    || warn "MCP not responding"

curl -fs http://127.0.0.1:5001 >/dev/null \
    && success "UI responding" \
    || warn "UI not responding"
progress

################################---------
# SUMMARY
#########################################

IP=$(hostname -I | awk '{print $1}')

echo
echo -e "${GREEN}"
echo "===================================================="
echo "          HOMEE INSTALLATION COMPLETE"
echo "===================================================="
echo -e "${NC}"

echo "Host:              $(hostname)"
echo "IP:                ${IP}"

echo
echo "CPU Cores:         ${CPU_CORES}"
echo "RAM:               ${TOTAL_RAM} MB"
echo "Free Disk:         ${FREE_DISK} GB"

echo
echo "Readiness Score:   ${SCORE}"

echo
echo "Model:             ${MODEL_NAME}"
echo "Inference Time:    ${LATENCY}s"

echo
echo "UI URL:"
echo "http://${IP}:5001"

echo
echo "MCP URL:"
echo "http://${IP}:5002"

echo
echo "Logs:"
echo "journalctl -fu homee-ui"
echo "journalctl -fu homee-mcp"
progress

echo
success "Deployment complete."