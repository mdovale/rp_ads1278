#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

TARGET_USER="root"
REDPITAYA_IP="${REDPITAYA_IP:-}"
SSH_PORT="22"
ASSUME_YES=0
DO_REBOOT=1
FPGAUTIL_PATH="/opt/redpitaya/bin/fpgautil"
SERVER_PATH="/usr/local/bin/ads1278-server"
BITSTREAM_PATH="/root/ads1278.bit.bin"
SERVICE_NAME="ads1278-server"
REMOTE_DIR="/root"

usage() {
  cat <<EOF
Usage: $(basename "$0") --ip <address> [OPTIONS]

Deploys a systemd service on a RedPitaya that loads an FPGA bitstream and
starts the ads1278 server on boot.

Options:
  --ip IP               RedPitaya IP or hostname (or use RP_IP/REDPITAYA_IP env)
  --user USER           SSH user [default: root]
  --port PORT           SSH port [default: 22]
  --bitstream PATH      Path to bitstream on RedPitaya [default: /root/ads1278.bit.bin]
  --yes                 Skip confirmation prompts
  --no-reboot           Do not reboot the RedPitaya after enabling the service
  --help                Show this help

Examples:
  ./$(basename "$0") --ip 169.254.97.245
  ./$(basename "$0") --ip rp-foo.local
  ./$(basename "$0") --ip 169.254.97.245 --no-reboot
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ip)
      if [[ $# -lt 2 ]]; then echo -e "${RED}Error: --ip requires an argument.${NC}" >&2; usage >&2; exit 1; fi
      REDPITAYA_IP="$2"
      shift 2
      ;;
    --user)
      if [[ $# -lt 2 ]]; then echo -e "${RED}Error: --user requires an argument.${NC}" >&2; usage >&2; exit 1; fi
      TARGET_USER="$2"
      shift 2
      ;;
    --port)
      if [[ $# -lt 2 ]]; then echo -e "${RED}Error: --port requires an argument.${NC}" >&2; usage >&2; exit 1; fi
      SSH_PORT="$2"
      shift 2
      ;;
    --bitstream)
      if [[ $# -lt 2 ]]; then echo -e "${RED}Error: --bitstream requires an argument.${NC}" >&2; usage >&2; exit 1; fi
      BITSTREAM_PATH="$2"
      shift 2
      ;;
    --yes)
      ASSUME_YES=1
      shift
      ;;
    --no-reboot)
      DO_REBOOT=0
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$REDPITAYA_IP" ]]; then
  REDPITAYA_IP="${RP_IP:-${REDPITAYA_IP:-${RP_HOST:-}}}"
fi

if [[ -z "$REDPITAYA_IP" ]]; then
  echo -e "${RED}Error: --ip is required (or set RP_IP/REDPITAYA_IP).${NC}" >&2
  exit 1
fi

START_SCRIPT_PATH="${REMOTE_DIR}/start_ads1278.sh"

# --- SSH setup (reusable control socket) ---

CONTROL_SOCKET="/tmp/ssh_rp_${REDPITAYA_IP//./_}_${RANDOM}${RANDOM}"
rm -f "$CONTROL_SOCKET" 2>/dev/null || true
SSH_OPTS="-p $SSH_PORT -o ControlMaster=auto -o ControlPath=$CONTROL_SOCKET -o ControlPersist=60"

cleanup_ssh() {
  if [[ -S "$CONTROL_SOCKET" ]]; then
    ssh -p "$SSH_PORT" -o ControlPath="$CONTROL_SOCKET" -O exit "$TARGET_USER@$REDPITAYA_IP" &>/dev/null || true
    rm -f "$CONTROL_SOCKET"
  fi
}
trap cleanup_ssh EXIT INT TERM

run_remote() {
  ssh $SSH_OPTS "$TARGET_USER@$REDPITAYA_IP" "$@"
}

echo -e "${GREEN}Deploying systemd service '${SERVICE_NAME}.service' to RedPitaya...${NC}"
echo "  Target:    $TARGET_USER@$REDPITAYA_IP"
echo "  Bitstream: $BITSTREAM_PATH"
echo "  Server:    $SERVER_PATH"

echo -e "${BLUE}Testing SSH connection...${NC}"
if ! ssh $SSH_OPTS -o ConnectTimeout=5 "$TARGET_USER@$REDPITAYA_IP" "echo ok" &>/dev/null; then
  echo -e "${RED}Error: Cannot connect to $TARGET_USER@$REDPITAYA_IP${NC}" >&2
  exit 1
fi

# --- Pre-flight checks on the remote host ---

echo -e "${BLUE}Running pre-flight checks...${NC}"

errors=0

if ! run_remote "[ -x '$FPGAUTIL_PATH' ]"; then
  echo -e "${RED}Error: fpgautil not found or not executable at $FPGAUTIL_PATH${NC}" >&2
  errors=$((errors + 1))
fi

if ! run_remote "[ -x '$SERVER_PATH' ]"; then
  echo -e "${RED}Error: server binary not found or not executable at $SERVER_PATH${NC}" >&2
  errors=$((errors + 1))
fi

if ! run_remote "[ -f '$BITSTREAM_PATH' ]"; then
  echo -e "${RED}Error: bitstream not found at $BITSTREAM_PATH${NC}" >&2
  errors=$((errors + 1))
fi

if [[ "$errors" -gt 0 ]]; then
  echo -e "${RED}Pre-flight checks failed ($errors error(s)). Aborting.${NC}" >&2
  exit 1
fi

echo -e "${GREEN}All pre-flight checks passed.${NC}"

# --- Confirmation ---

if [[ "$ASSUME_YES" == "0" ]]; then
  echo ""
  echo -e "${YELLOW}This will install and enable ${SERVICE_NAME}.service on the RedPitaya.${NC}"
  if [[ "$DO_REBOOT" == "1" ]]; then
    echo -e "${YELLOW}The board will reboot after the service is enabled.${NC}"
  fi
  read -p "Continue? (y/N) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 0
  fi
fi

# --- Generate and deploy the start script ---

START_SCRIPT=$(cat <<SCRIPT
#!/bin/bash
${FPGAUTIL_PATH} -b ${BITSTREAM_PATH} -f Full
${SERVER_PATH}
SCRIPT
)

echo -e "${BLUE}Deploying ${START_SCRIPT_PATH}...${NC}"
run_remote "cat > '${START_SCRIPT_PATH}' && chmod 755 '${START_SCRIPT_PATH}'" <<< "$START_SCRIPT"

# --- Generate and deploy the systemd unit ---

UNIT_FILE=$(cat <<UNIT
[Unit]
Description=Load FPGA image and start ADS1278 server
After=network-online.target redpitaya_nginx.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root
ExecStart=${START_SCRIPT_PATH}
Restart=on-failure
RestartSec=2
TimeoutStartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT
)

UNIT_DEST="/etc/systemd/system/${SERVICE_NAME}.service"

echo -e "${BLUE}Deploying ${UNIT_DEST}...${NC}"
run_remote "cat > '${UNIT_DEST}'" <<< "$UNIT_FILE"

# --- Enable the service (RedPitaya recommended sequence) ---

echo -e "${BLUE}Enabling ${SERVICE_NAME}.service...${NC}"
run_remote "mount -o remount,rw /opt/redpitaya && systemctl daemon-reload && systemctl disable '${SERVICE_NAME}.service' && systemctl enable '${SERVICE_NAME}.service' && mount -o remount,ro /opt/redpitaya"

# Verify the service is enabled
if run_remote "systemctl is-enabled '${SERVICE_NAME}.service' | grep -q enabled"; then
  echo -e "${GREEN}${SERVICE_NAME}.service is enabled.${NC}"
else
  echo -e "${RED}Error: ${SERVICE_NAME}.service does not appear to be enabled.${NC}" >&2
  exit 1
fi

# --- Reboot ---

if [[ "$DO_REBOOT" == "1" ]]; then
  echo -e "${BLUE}Rebooting RedPitaya...${NC}"
  run_remote "reboot" || true
  echo -e "${GREEN}Reboot command sent. The board will come back up with ${SERVICE_NAME}.service running.${NC}"
else
  echo -e "${GREEN}Done. Reboot the RedPitaya manually to start the service, or run:${NC}"
  echo "  ssh ${TARGET_USER}@${REDPITAYA_IP} 'systemctl start ${SERVICE_NAME}.service'"
fi
