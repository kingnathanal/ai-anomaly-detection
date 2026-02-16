#!/usr/bin/env bash
set -euo pipefail

# ── Raspberry Pi Setup Script ────────────────────────────────────
# Combines OS package install, Homebrew, dev tools, and edge-agent
# Python venv into a single script.  Run as root (sudo).
# ─────────────────────────────────────────────────────────────────

INSTALL_DIR="/opt/edge-agent"
RUN_USER="${RUN_USER:-kingnathanal}"

log()  { printf "\n\033[1;32m[setup]\033[0m %s\n" "$*"; }
die()  { printf "\n\033[1;31m[setup]\033[0m %s\n" "$*"; exit 1; }
step() { printf "\n\033[1;34m── Step %s ──\033[0m\n" "$*"; }

# ── Pre-flight checks ───────────────────────────────────────────
[[ "$OSTYPE" == linux-gnu* ]] || die "This script is designed for Linux systems."
[[ $EUID -eq 0 ]]            || die "Run as root: sudo bash setup-rpi.sh"

# ── Step 1: System packages ─────────────────────────────────────
step "1: Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  build-essential \
  ca-certificates \
  curl \
  dnsutils \
  file \
  git \
  htop \
  iputils-ping \
  iproute2 \
  mosquitto-clients \
  net-tools \
  procps \
  python3 python3-venv python3-pip \
  tmux \
  vim \
  wget
log "System packages installed."

# ── Step 2: Homebrew ─────────────────────────────────────────────
step "2: Installing Homebrew"
if sudo -u "${RUN_USER}" bash -c 'command -v brew' &>/dev/null; then
  log "Homebrew already installed."
else
  sudo -u "${RUN_USER}" -H bash -lc \
    'NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  log "Homebrew installed."
fi

# Configure PATH for the run user
BREW_SHELLENV='eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"'
USER_HOME=$(eval echo "~${RUN_USER}")

for rc in "${USER_HOME}/.bashrc" "${USER_HOME}/.zshrc"; do
  [[ -f "$rc" ]] || continue
  if ! grep -q "brew shellenv" "$rc"; then
    printf '\n# Homebrew\n%s\n' "$BREW_SHELLENV" >> "$rc"
    log "Added Homebrew to $(basename "$rc")"
  fi
done

# ── Step 3: GCC via Homebrew ────────────────────────────────────
step "3: Installing GCC via Homebrew"
sudo -u "${RUN_USER}" -H bash -lc '
  eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
  if brew list gcc &>/dev/null; then
    echo "GCC already installed"
  else
    brew install gcc
  fi
'
log "GCC ready."

# ── Step 4: Edge-agent directory & Python venv ──────────────────
step "4: Setting up ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
chown -R "${RUN_USER}:${RUN_USER}" "${INSTALL_DIR}"

sudo -u "${RUN_USER}" -H bash -lc "
  set -euo pipefail
  python3 -m venv '${INSTALL_DIR}/venv'
  '${INSTALL_DIR}/venv/bin/pip' install --upgrade pip wheel setuptools
  '${INSTALL_DIR}/venv/bin/pip' install requests paho-mqtt
"
log "Python venv created at ${INSTALL_DIR}/venv"

# ── Done ─────────────────────────────────────────────────────────
cat <<EOF

========================================
  Setup Complete!
========================================

Homebrew  → run 'brew install <pkg>' as ${RUN_USER}
Python    → source ${INSTALL_DIR}/venv/bin/activate
Pip libs  → requests, paho-mqtt

To reload your shell: source ${USER_HOME}/.bashrc

EOF
echo "To search packages: brew search <keyword>"
echo ""
