#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BINARY_NAME="server"
RPDEVMEM_NAME="rpdevmem"
BUILD_DIR=""
BINARY_PATH=""
RPDEVMEM_PATH=""
TARGET_USER="root"
TARGET_DIR="/usr/local/bin"
TARGET_BINARY_NAME="ads1278-server"
TARGET_RPDEVMEM_NAME="ads1278-rpdevmem"
REDPITAYA_IP="${REDPITAYA_IP:-}"
SSH_PORT="22"
FORCE=0

usage() {
  cat <<EOF
Usage: $(basename "$0") --ip <address> [OPTIONS]

Options:
  --ip IP            RedPitaya IP or hostname (or use RP_IP/REDPITAYA_IP env)
  --build-dir DIR    Build directory [default: auto-detect]
  --binary PATH      Explicit path to server binary
  --rpdevmem PATH    Explicit path to rpdevmem (default: DIR/rpdevmem next to server)
  --user USER        SSH user [default: root]
  --target-dir DIR   Target directory on RedPitaya [default: /usr/local/bin]
  --target-name NAME Deployed server name [default: ads1278-server]
  --target-rpdevmem-name NAME  Deployed rpdevmem name [default: ads1278-rpdevmem]
  --port PORT        SSH port [default: 22]
  --force            Deploy even if binary format looks wrong
  --help             Show this help

Examples:
  ./server-deploy.sh --ip 169.254.97.245
  ./server-deploy.sh --ip rp-foo.local --build-dir build-cross
  ./server-deploy.sh --ip 169.254.97.245 --binary /tmp/server
EOF
}

resolve_path() {
  if [[ "$1" = /* ]]; then
    echo "$1"
  else
    echo "$SCRIPT_DIR/$1"
  fi
}

auto_detect_binary() {
  local candidates=(
    "$SCRIPT_DIR/build-cross/$BINARY_NAME"
    "$SCRIPT_DIR/build-docker/$BINARY_NAME"
    "$SCRIPT_DIR/server/$BINARY_NAME"
  )
  for cand in "${candidates[@]}"; do
    [[ -f "$cand" ]] || continue
    if command -v file &>/dev/null; then
      cand_type="$(file "$cand" 2>/dev/null || true)"
      if echo "$cand_type" | grep -Eqi 'ELF.*(ARM|aarch64)'; then
        echo "$cand"
        return
      fi
    else
      echo "$cand"
      return
    fi
  done

  for cand in "${candidates[@]}"; do
    [[ -f "$cand" ]] || continue
    echo "$cand"
    return
  done
}

default_rpdevmem_path() {
  local server_path="$1"
  echo "$(cd "$(dirname "$server_path")" && pwd)/$RPDEVMEM_NAME"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ip)
      REDPITAYA_IP="$2"
      shift 2
      ;;
    --build-dir)
      BUILD_DIR="$2"
      shift 2
      ;;
    --binary)
      BINARY_PATH="$2"
      shift 2
      ;;
    --rpdevmem)
      RPDEVMEM_PATH="$2"
      shift 2
      ;;
    --user)
      TARGET_USER="$2"
      shift 2
      ;;
    --target-dir)
      TARGET_DIR="$2"
      shift 2
      ;;
    --target-name)
      TARGET_BINARY_NAME="$2"
      shift 2
      ;;
    --target-rpdevmem-name)
      TARGET_RPDEVMEM_NAME="$2"
      shift 2
      ;;
    --port)
      SSH_PORT="$2"
      shift 2
      ;;
    --force)
      FORCE=1
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

if [[ -n "$BUILD_DIR" && -z "$BINARY_PATH" ]]; then
  BUILD_DIR="$(resolve_path "$BUILD_DIR")"
  BINARY_PATH="$BUILD_DIR/$BINARY_NAME"
fi

if [[ -z "$BINARY_PATH" ]]; then
  BINARY_PATH="$(auto_detect_binary || true)"
fi

if [[ -z "$BINARY_PATH" || ! -f "$BINARY_PATH" ]]; then
  echo -e "${RED}Error: server binary not found.${NC}" >&2
  echo "Build it with:" >&2
  echo "  ./server-build-cross.sh" >&2
  echo "  ./server-build-docker.sh" >&2
  exit 1
fi

if [[ -z "$RPDEVMEM_PATH" ]]; then
  RPDEVMEM_PATH="$(default_rpdevmem_path "$BINARY_PATH")"
else
  RPDEVMEM_PATH="$(resolve_path "$RPDEVMEM_PATH")"
fi

if [[ ! -f "$RPDEVMEM_PATH" ]]; then
  echo -e "${RED}Error: rpdevmem binary not found at $RPDEVMEM_PATH${NC}" >&2
  echo "Rebuild so both server and rpdevmem are produced, or pass --rpdevmem PATH." >&2
  exit 1
fi

if [[ -z "$REDPITAYA_IP" ]]; then
  echo -e "${RED}Error: --ip is required (or set RP_IP/REDPITAYA_IP).${NC}" >&2
  exit 1
fi

if ! command -v ssh &>/dev/null || ! command -v scp &>/dev/null; then
  echo -e "${RED}Error: ssh/scp not found in PATH.${NC}" >&2
  exit 1
fi

check_arm_elf() {
  local path="$1"
  local label="$2"
  if ! command -v file &>/dev/null; then
    return 0
  fi
  local binary_type
  binary_type="$(file "$path" 2>/dev/null || true)"
  if echo "$binary_type" | grep -Eqi 'ELF.*(ARM|aarch64)'; then
    return 0
  fi
  if [[ "$FORCE" == "1" ]]; then
    echo -e "${YELLOW}Warning: $label does not appear to be an ELF ARM executable; deploying anyway (--force).${NC}" >&2
    echo -e "${YELLOW}Type: $binary_type${NC}" >&2
    return 0
  fi
  echo -e "${RED}Error: $label does not appear to be an ELF ARM executable.${NC}" >&2
  echo -e "${RED}Type: $binary_type${NC}" >&2
  echo -e "${YELLOW}Rebuild with: ./server-build-cross.sh --rebuild${NC}" >&2
  echo -e "${YELLOW}Or override with: ./server-deploy.sh ... --force${NC}" >&2
  return 1
}

if ! check_arm_elf "$BINARY_PATH" "server binary"; then
  exit 1
fi
if ! check_arm_elf "$RPDEVMEM_PATH" "rpdevmem binary"; then
  exit 1
fi

echo -e "${GREEN}Deploying server and rpdevmem to RedPitaya...${NC}"
echo "Server source: $BINARY_PATH"
echo "Server target: $TARGET_USER@$REDPITAYA_IP:$TARGET_DIR/$TARGET_BINARY_NAME"
echo "rpdevmem source: $RPDEVMEM_PATH"
echo "rpdevmem target: $TARGET_USER@$REDPITAYA_IP:$TARGET_DIR/$TARGET_RPDEVMEM_NAME"

echo -e "${BLUE}Creating target directory...${NC}"
ssh -p "$SSH_PORT" "$TARGET_USER@$REDPITAYA_IP" "mkdir -p '$TARGET_DIR'"

echo -e "${BLUE}Copying binaries...${NC}"
scp -P "$SSH_PORT" "$BINARY_PATH" "$TARGET_USER@$REDPITAYA_IP:$TARGET_DIR/$TARGET_BINARY_NAME"
scp -P "$SSH_PORT" "$RPDEVMEM_PATH" "$TARGET_USER@$REDPITAYA_IP:$TARGET_DIR/$TARGET_RPDEVMEM_NAME"

echo -e "${BLUE}Setting permissions...${NC}"
ssh -p "$SSH_PORT" "$TARGET_USER@$REDPITAYA_IP" "chmod +x '$TARGET_DIR/$TARGET_BINARY_NAME' '$TARGET_DIR/$TARGET_RPDEVMEM_NAME'"

echo -e "${GREEN}Deployment completed successfully.${NC}"
echo "Run on device:"
echo "  ssh -p $SSH_PORT $TARGET_USER@$REDPITAYA_IP '$TARGET_DIR/$TARGET_BINARY_NAME'"
echo "  ssh -p $SSH_PORT $TARGET_USER@$REDPITAYA_IP '$TARGET_DIR/$TARGET_RPDEVMEM_NAME snapshot'"
